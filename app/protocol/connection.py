import time
import json
import asyncio
from typing import Dict, Optional, Set
from datetime import datetime
import websockets
from websockets.exceptions import ConnectionClosed
from loguru import logger
from sqlalchemy import select

from app.config import settings
from app.core.database import AsyncSessionLocal
from app.core.event_bus import event_bus
from app.models.entities import Account, Conversation, Message
from app.protocol.codec import decrypt_message, encode_chat_payload
from app.protocol.utils import generate_mid, generate_uuid, generate_device_id, trans_cookies
from app.protocol.client import XianyuAsyncClient
from app.engine.workflow import workflow


class XianyuConnectionInstance:
    """单个闲鱼账号的独立异步 WebSocket 运行实例"""

    def __init__(self, seller_id: str, cookies_str: str, proxy_url: Optional[str] = None):
        self.seller_id = seller_id
        self.cookies_str = cookies_str
        self.proxy_url = proxy_url
        self.client = XianyuAsyncClient(cookies_str, proxy_url=proxy_url)
        self.device_id = generate_device_id(seller_id)
        
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.current_token: Optional[str] = None
        self.last_token_refresh_time: float = 0
        self.last_heartbeat_time: float = 0
        self.last_heartbeat_response: float = 0
        
        self.is_running: bool = False
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._token_task: Optional[asyncio.Task] = None

    async def init_session(self):
        """获取初始 Token 并向 WSS 注册设备"""
        token_res = await self.client.get_token(self.device_id)
        if token_res and 'data' in token_res and 'accessToken' in token_res['data']:
            self.current_token = token_res['data']['accessToken']
            self.last_token_refresh_time = time.time()
            logger.info(f"账号 {self.seller_id} 获得有效 Token")
            return True
        return False

    async def send_raw(self, payload: Dict):
        """向长连接通道发送原始 JSON 协议包"""
        if self.ws and not self.ws.closed:
            await self.ws.send(json.dumps(payload))

    async def register_device(self):
        """向闲鱼网关上报 /reg 注册设备"""
        reg_msg = {
            "lwp": "/reg",
            "headers": {
                "cache-header": "app-key token ua wv",
                "app-key": "444e9908a51d1cb236a27862abc769c9",
                "token": self.current_token,
                "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 DingTalk(2.1.5) OS(Windows/10) Browser(Chrome/133.0.0.0) DingWeb/2.1.5 IMPaaS DingWeb/2.1.5",
                "dt": "j",
                "wv": "im:3,au:3,sy:6",
                "sync": "0,0;0;0;",
                "did": self.device_id,
                "mid": generate_mid()
            }
        }
        await self.send_raw(reg_msg)
        await asyncio.sleep(0.5)
        ack_diff = {
            "lwp": "/r/SyncStatus/ackDiff",
            "headers": {"mid": generate_mid()},
            "body": [{
                "pipeline": "sync", "tooLong2Tag": "PNM,1", "channel": "sync", "topic": "sync",
                "highPts": 0, "pts": int(time.time() * 1000) * 1000, "seq": 0, "timestamp": int(time.time() * 1000)
            }]
        }
        await self.send_raw(ack_diff)
        logger.info(f"账号 {self.seller_id} WSS 设备注册与同步确认完毕")

    async def send_chat_message(self, chat_id: str, to_user_id: str, text: str):
        """向买家发送聊天消息"""
        b64_payload = encode_chat_payload(text)
        msg_package = {
            "lwp": "/r/MessageSend/sendByReceiverScope",
            "headers": {
                "mid": generate_mid()
            },
            "body": [
                {
                    "uuid": generate_uuid(),
                    "cid": f"{chat_id}@goofish",
                    "conversationType": 1,
                    "content": {
                        "contentType": 101,
                        "custom": {
                            "type": 1,
                            "data": b64_payload
                        }
                    },
                    "redPointPolicy": 0,
                    "extension": {"extJson": "{}"},
                    "ctx": {"appVersion": "1.0", "platform": "web"},
                    "mtags": {},
                    "msgReadStatusSetting": 1
                },
                {
                    "actualReceivers": [
                        f"{to_user_id}@goofish",
                        f"{self.seller_id}@goofish"
                    ]
                }
            ]
        }
        await self.send_raw(msg_package)

    async def _heartbeat_loop(self):
        """专用心跳协程"""
        while self.is_running:
            try:
                now = time.time()
                if now - self.last_heartbeat_time >= settings.HEARTBEAT_INTERVAL:
                    hb = {"lwp": "/!", "headers": {"mid": generate_mid()}}
                    await self.send_raw(hb)
                    self.last_heartbeat_time = now

                # 心跳响应超时检测
                if (now - self.last_heartbeat_response) > (settings.HEARTBEAT_INTERVAL + settings.HEARTBEAT_TIMEOUT):
                    logger.warning(f"账号 {self.seller_id} 心跳超时，触发自动重连")
                    if self.ws:
                        await self.ws.close()
                    break

                await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"心跳循环异常 ({self.seller_id}): {e}")
                break

    async def _token_refresh_loop(self):
        """Token 定时无感续期协程"""
        while self.is_running:
            try:
                now = time.time()
                if now - self.last_token_refresh_time >= settings.TOKEN_REFRESH_INTERVAL:
                    logger.info(f"账号 {self.seller_id} 即将过期，无感续期 Token...")
                    token_res = await self.client.get_token(self.device_id)
                    if token_res and 'data' in token_res and 'accessToken' in token_res['data']:
                        self.current_token = token_res['data']['accessToken']
                        self.last_token_refresh_time = now
                        logger.info(f"账号 {self.seller_id} Token 续期成功，平滑重新注册通道...")
                        await self.register_device()
                await asyncio.sleep(60)
            except Exception as e:
                logger.error(f"Token 续期异常: {e}")
                await asyncio.sleep(60)

    async def handle_incoming_frame(self, frame_text: str):
        """解析并分发 WSS 接收到的数据帧"""
        try:
            msg = json.loads(frame_text)
        except Exception:
            return

        # 1. 响应心跳或常规 ACK
        mid = msg.get("headers", {}).get("mid")
        if mid:
            ack = {"code": 200, "headers": {"mid": mid, "sid": msg.get("headers", {}).get("sid", "")}}
            await self.send_raw(ack)

        # 检查是否为心跳响应
        if msg.get("code") == 200 and mid:
            self.last_heartbeat_response = time.time()
            return

        # 2. 检查是否为同步包 (syncPushPackage)
        body = msg.get("body", {})
        sync_pkg = body.get("syncPushPackage", {})
        data_list = sync_pkg.get("data", [])
        if not data_list:
            return

        for item in data_list:
            raw_data = item.get("data")
            if not raw_data:
                continue

            decrypted = decrypt_message(raw_data)
            if not isinstance(decrypted, dict):
                continue

            # 3. 检查订单状态消息卡片 (redReminder)
            red_remind = decrypted.get("3", {}).get("redReminder")
            if red_remind:
                logger.info(f"【订单状态卡片】买家 {decrypted.get('1')} 状态变更: {red_remind}")
                await event_bus.publish("order_event", {
                    "seller_id": self.seller_id,
                    "event_type": red_remind,
                    "raw": decrypted
                })
                continue

            # 4. 判断是否为买家/卖家会话聊天消息
            reminder_content = decrypted.get("1", {}).get("10", {}).get("reminderContent")
            if not reminder_content:
                continue

            sender_uid = decrypted["1"]["10"].get("senderUserId")
            sender_name = decrypted["1"]["10"].get("reminderTitle", "闲鱼买家")
            reminder_url = decrypted["1"]["10"].get("reminderUrl", "")
            create_time = int(decrypted["1"].get("5", time.time() * 1000))

            # 时效性过滤
            if (time.time() * 1000 - create_time) > settings.MESSAGE_EXPIRE_TIME:
                continue

            item_id = ""
            if "itemId=" in reminder_url:
                item_id = reminder_url.split("itemId=")[1].split("&")[0]

            chat_id = decrypted["1"].get("2", "").split("@")[0]

            # Case A: 卖家自己发送的消息 (检查人工接管控制符或卖家插话)
            if sender_uid == self.seller_id:
                async with AsyncSessionLocal() as session:
                    stmt = select(Conversation).where(Conversation.chat_id == chat_id)
                    res = await session.execute(stmt)
                    conv = res.scalar_one_or_none()

                    if conv:
                        # 检查切换关键词 (如 "。")
                        if reminder_content.strip() == settings.TOGGLE_KEYWORDS:
                            new_mode = "manual" if conv.copilot_mode == "auto" else "auto"
                            conv.copilot_mode = new_mode
                            conv.manual_takeover_at = datetime.utcnow() if new_mode == "manual" else None
                            await session.commit()
                            logger.info(f"会话 {chat_id} 通过关键词切换接管模式: {new_mode}")
                            await event_bus.publish("copilot_mode_changed", {
                                "chat_id": chat_id,
                                "copilot_mode": new_mode
                            })
                            return

                        # 卖家手动插话记录
                        manual_msg = Message(
                            chat_id=chat_id,
                            seller_id=self.seller_id,
                            item_id=item_id,
                            sender_id=self.seller_id,
                            role="seller_manual",
                            content=reminder_content,
                            timestamp=datetime.utcnow()
                        )
                        session.add(manual_msg)
                        conv.unread_count = 0
                        await session.commit()

                        await event_bus.publish("message_sent", {
                            "chat_id": chat_id,
                            "seller_id": self.seller_id,
                            "role": "seller_manual",
                            "content": reminder_content,
                            "timestamp": datetime.utcnow().isoformat()
                        })
                return

            # Case B: 买家发来的消息 -> 触发业务工作流
            await workflow.process_incoming_message(
                seller_id=self.seller_id,
                chat_id=chat_id,
                buyer_id=sender_uid,
                buyer_name=sender_name,
                item_id=item_id,
                user_msg=reminder_content,
                raw_msg_data=decrypted
            )

    async def run_forever(self):
        """长连接自愈循环 (支持断线指数退避)"""
        self.is_running = True
        backoff = 2

        while self.is_running:
            try:
                # 检查并刷新 Token
                if not self.current_token:
                    ok = await self.init_session()
                    if not ok:
                        logger.error(f"账号 {self.seller_id} 无法获取 Token，等待重试")
                        await asyncio.sleep(10)
                        continue

                headers = {
                    "Cookie": self.cookies_str,
                    "Host": "wss-goofish.dingtalk.com",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Origin": "https://www.goofish.com"
                }

                logger.info(f"账号 {self.seller_id} 正在建立 WSS 长连接...")
                async with websockets.connect(settings.WSS_URL, extra_headers=headers) as ws:
                    self.ws = ws
                    self.last_heartbeat_time = time.time()
                    self.last_heartbeat_response = time.time()
                    backoff = 2  # 重置退避时长

                    await self.register_device()
                    await event_bus.publish("account_status", {
                        "seller_id": self.seller_id,
                        "status": "online",
                        "message": "长连接已就绪，AI 7x24h 自动值守中"
                    })

                    self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                    self._token_task = asyncio.create_task(self._token_refresh_loop())

                    async for message in ws:
                        await self.handle_incoming_frame(message)

            except asyncio.CancelledError:
                self.is_running = False
                break
            except ConnectionClosed as e:
                logger.warning(f"账号 {self.seller_id} WSS 连接中断: {e}")
            except Exception as e:
                logger.error(f"账号 {self.seller_id} 运行异常: {e}")
            finally:
                if self._heartbeat_task:
                    self._heartbeat_task.cancel()
                if self._token_task:
                    self._token_task.cancel()

                await event_bus.publish("account_status", {
                    "seller_id": self.seller_id,
                    "status": "reconnecting",
                    "message": f"连接中断，{backoff} 秒后尝试自动恢复..."
                })
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.5, 60)


class ConnectionHub:
    """多账号长连接连接池调度中枢"""

    def __init__(self):
        self.instances: Dict[str, XianyuConnectionInstance] = {}
        self._tasks: Dict[str, asyncio.Task] = {}

    def start_account(self, seller_id: str, cookies_str: str, proxy_url: Optional[str] = None):
        """启动或重载指定账号长连接实例 (支持独立代理)"""
        if seller_id in self.instances:
            self.stop_account(seller_id)

        inst = XianyuConnectionInstance(seller_id, cookies_str, proxy_url=proxy_url)
        self.instances[seller_id] = inst
        self._tasks[seller_id] = asyncio.create_task(inst.run_forever())
        logger.info(f"已在后台启动账号 {seller_id} 的 WSS 长连接实例 (代理: {proxy_url or '全局直连'})")

    def stop_account(self, seller_id: str):
        """停止指定账号长连接"""
        if seller_id in self.instances:
            self.instances[seller_id].is_running = False
            if seller_id in self._tasks:
                self._tasks[seller_id].cancel()
                del self._tasks[seller_id]
            del self.instances[seller_id]
            logger.info(f"已注销账号 {seller_id} 实例")

    async def send_chat_message(self, seller_id: str, chat_id: str, to_user_id: str, text: str):
        """向指定账号绑定的通道发送买家回复"""
        inst = self.instances.get(seller_id)
        if not inst:
            # 若连接池暂无，尝试使用首个活动账号
            if self.instances:
                inst = next(iter(self.instances.values()))
            else:
                logger.error(f"无法发送消息：账号 {seller_id} 无活动 WSS 连接")
                return

        await inst.send_chat_message(chat_id, to_user_id, text)


connection_hub = ConnectionHub()
# 将发送方法注入到工作流中
workflow.set_sender(connection_hub.send_chat_message)
