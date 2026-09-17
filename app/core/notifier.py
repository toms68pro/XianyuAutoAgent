import json
import asyncio
from typing import Optional, Dict, Any
import httpx
from loguru import logger
from app.config import settings
from app.core.event_bus import event_bus


class MultiChannelNotifier:
    """多渠道移动端即时告警与事件通知中枢 (支持 钉钉 / 飞书 / 企业微信 / Bark)"""

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=10.0, trust_env=False)
        self._register_event_subscribers()

    def _register_event_subscribers(self):
        """订阅事件总线中的核心业务事件并自动派发告警"""
        event_bus.register_handler("order_event", self._handle_order_event)
        event_bus.register_handler("account_status", self._handle_account_status_event)
        event_bus.register_handler("copilot_mode_changed", self._handle_mode_event)

    async def _handle_order_event(self, data: Dict[str, Any]):
        """处理订单状态变更通知"""
        if not settings.NOTIFY_ON_ORDER:
            return
        event_type = data.get("event_type", "订单状态变更")
        seller_id = data.get("seller_id", "未知店铺")
        title = f"🎉 闲鱼订单动态: {event_type}"
        content = (
            f"**店铺账号**: {seller_id}\n\n"
            f"**事件类型**: {event_type}\n\n"
            f"**提醒详情**: 买家已操作，请及时前往闲鱼查看处理！"
        )
        await self.send_alert(title, content)

    async def _handle_account_status_event(self, data: Dict[str, Any]):
        """处理风控滑块与 Cookie 失效告警"""
        status = data.get("status")
        seller_id = data.get("seller_id", "未知账号")
        msg = data.get("message", "")

        if status == "captcha_required" and settings.NOTIFY_ON_CAPTCHA:
            title = "⚠️ 闲鱼风控预警：需要完成滑块验证"
            content = (
                f"**受影响账号**: {seller_id}\n\n"
                f"**预警等级**: 高危风控 (RGV587)\n\n"
                f"**说明**: {msg}\n\n"
                f"**建议操作**: 请在电脑或手机浏览器打开闲鱼网页版，完成拼图滑块，或登录工作台更新凭据！"
            )
            await self.send_alert(title, content)

        elif status == "cookie_expired":
            title = "🚨 凭据失效告警：Cookie 已过期"
            content = (
                f"**受影响账号**: {seller_id}\n\n"
                f"**说明**: 闲鱼登录态已失效，自动值守已暂停。\n\n"
                f"**操作建议**: 请立即在管理工作台重新粘贴最新 Cookie 以恢复服务。"
            )
            await self.send_alert(title, content)

    async def _handle_mode_event(self, data: Dict[str, Any]):
        """处理人工接管通知"""
        if not settings.NOTIFY_ON_TAKEOVER:
            return
        mode = data.get("copilot_mode")
        chat_id = data.get("chat_id")
        if mode == "manual":
            title = "👤 会话已进入人工接管状态"
            content = (
                f"**会话ID**: {chat_id}\n\n"
                f"**状态**: AI 自动回复已暂停，等待卖家手动介入沟通。"
            )
            await self.send_alert(title, content)

    async def send_alert(self, title: str, markdown_content: str):
        """向所有已配置的渠道异步广播告警"""
        tasks = []
        if settings.DINGTALK_WEBHOOK:
            tasks.append(self._send_dingtalk(title, markdown_content))
        if settings.FEISHU_WEBHOOK:
            tasks.append(self._send_feishu(title, markdown_content))
        if settings.WECOM_WEBHOOK:
            tasks.append(self._send_wecom(title, markdown_content))
        if settings.BARK_URL:
            tasks.append(self._send_bark(title, markdown_content))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for res in results:
                if isinstance(res, Exception):
                    logger.warning(f"告警通知发送异常: {res}")

    async def _send_dingtalk(self, title: str, text: str):
        """发送钉钉机器人消息"""
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": f"### {title}\n\n{text}"
            }
        }
        resp = await self.client.post(settings.DINGTALK_WEBHOOK, json=payload)
        if resp.status_code != 200:
            logger.warning(f"钉钉告警响应非200: {resp.text}")

    async def _send_feishu(self, title: str, text: str):
        """发送飞书机器人消息"""
        payload = {
            "msg_type": "interactive",
            "card": {
                "header": {"title": {"tag": "plain_text", "content": title}},
                "elements": [{"tag": "markdown", "content": text}]
            }
        }
        resp = await self.client.post(settings.FEISHU_WEBHOOK, json=payload)
        if resp.status_code != 200:
            logger.warning(f"飞书告警响应非200: {resp.text}")

    async def _send_wecom(self, title: str, text: str):
        """发送企业微信机器人消息"""
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": f"### {title}\n\n{text}"
            }
        }
        resp = await self.client.post(settings.WECOM_WEBHOOK, json=payload)
        if resp.status_code != 200:
            logger.warning(f"企业微信告警响应非200: {resp.text}")

    async def _send_bark(self, title: str, text: str):
        """发送 Bark iOS 手机推送"""
        clean_text = text.replace('**', '').replace('\n\n', ' ')
        url = f"{settings.BARK_URL.rstrip('/')}/{title}/{clean_text}"
        await self.client.get(url)

    async def close(self):
        await self.client.aclose()


notifier = MultiChannelNotifier()
