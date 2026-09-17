import time
import json
import asyncio
from typing import Dict, Any, Optional
import httpx
from loguru import logger
from sqlalchemy import select
from app.protocol.utils import generate_sign, trans_cookies
from app.core.event_bus import event_bus
from app.core.database import AsyncSessionLocal
from app.models.entities import Account


class XianyuAsyncClient:
    """全异步闲鱼 MTOP HTTP 客户端 (基于 httpx，零阻塞 I/O)"""

    def __init__(self, cookies_str: str, proxy_url: Optional[str] = None):
        self.cookies_str = cookies_str
        self.cookies = trans_cookies(cookies_str)
        self.seller_id = self.cookies.get("unb", "")
        self.proxy_url = proxy_url
        
        from app.config import settings
        # 创建高性能异步 HTTP 客户端 (支持账号级别独立代理池隔离)
        proxy = self.proxy_url or (settings.PROXY_URL if settings.PROXY_URL else None)
        self.client = httpx.AsyncClient(
            cookies=self.cookies,
            timeout=15.0,
            proxy=proxy,
            headers={
                'accept': 'application/json',
                'accept-language': 'zh-CN,zh;q=0.9',
                'origin': 'https://www.goofish.com',
                'referer': 'https://www.goofish.com/',
                'sec-ch-ua': '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36',
            }
        )

    def update_cookies(self, new_cookies_str: str):
        """动态更新 Cookie"""
        self.cookies_str = new_cookies_str
        self.cookies = trans_cookies(new_cookies_str)
        self.client.cookies.clear()
        self.client.cookies.update(self.cookies)
        self.seller_id = self.cookies.get("unb", "")

    async def has_login(self, retry_count: int = 0) -> bool:
        """异步检查登录态与保活"""
        if retry_count >= 2:
            return False

        url = 'https://passport.goofish.com/newlogin/hasLogin.do'
        params = {'appName': 'xianyu', 'fromSite': '77'}
        data = {
            'hid': self.client.cookies.get('unb', ''),
            'ltl': 'true',
            'appName': 'xianyu',
            'appEntrance': 'web',
            '_csrf_token': self.client.cookies.get('XSRF-TOKEN', ''),
            'umidToken': '',
            'hsiz': self.client.cookies.get('cookie2', ''),
            'bizParams': 'taobaoBizLoginFrom=web',
            'mainPage': 'false',
            'isMobile': 'false',
            'lang': 'zh_CN',
            'returnUrl': '',
            'fromSite': '77',
            'isIframe': 'true',
            'documentReferer': 'https://www.goofish.com/',
            'defaultView': 'hasLogin',
            'umidTag': 'SERVER',
            'deviceId': self.client.cookies.get('cna', '')
        }

        try:
            resp = await self.client.post(url, params=params, data=data)
            res_json = resp.json()
            if res_json.get('content', {}).get('success'):
                logger.debug("登录态验证有效 (hasLogin OK)")
                return True
            else:
                logger.warning(f"hasLogin 失败: {res_json}")
                await asyncio.sleep(0.5)
                return await self.has_login(retry_count + 1)
        except Exception as e:
            logger.error(f"hasLogin 请求异常: {e}")
            await asyncio.sleep(0.5)
            return await self.has_login(retry_count + 1)

    async def get_token(self, device_id: str, retry_count: int = 0) -> Optional[Dict[str, Any]]:
        """异步获取消息服务 Access Token"""
        if retry_count >= 3:
            logger.error("Token 获取重试次数过多，尝试校验登录态")
            is_valid = await self.has_login()
            if not is_valid:
                logger.error("Cookie 已完全失效，触发风控或失效告警")
                await event_bus.publish("account_status", {
                    "seller_id": self.seller_id,
                    "status": "cookie_expired",
                    "message": "Cookie 已失效，请在工作台更新 Cookie"
                })
                return None

        t = str(int(time.time()) * 1000)
        data_val = json.dumps({"appKey": "444e9908a51d1cb236a27862abc769c9", "deviceId": device_id})
        token_cookie = self.client.cookies.get('_m_h5_tk', '').split('_')[0]
        sign = generate_sign(t, token_cookie, data_val)

        params = {
            'jsv': '2.7.2',
            'appKey': '34839810',
            't': t,
            'sign': sign,
            'v': '1.0',
            'type': 'originaljson',
            'accountSite': 'xianyu',
            'dataType': 'json',
            'timeout': '20000',
            'api': 'mtop.taobao.idlemessage.pc.login.token',
            'sessionOption': 'AutoLoginOnly',
            'spm_cnt': 'a21ybx.im.0.0',
            "spm_pre": "a21ybx.item.want.1.14ad3da6ALVq3n",
            "log_id": "14ad3da6ALVq3n"
        }

        try:
            resp = await self.client.post(
                'https://h5api.m.goofish.com/h5/mtop.taobao.idlemessage.pc.login.token/1.0/',
                params=params,
                data={'data': data_val}
            )
            res_json = resp.json()

            if isinstance(res_json, dict):
                ret_value = res_json.get('ret', [])
                if any('SUCCESS::调用成功' in ret for ret in ret_value):
                    logger.info("异步 Token 刷新成功")
                    return res_json

                error_msg = str(ret_value)
                if 'RGV587_ERROR' in error_msg or '被挤爆啦' in error_msg:
                    verify_url = ""
                    if isinstance(res_json, dict) and "data" in res_json and isinstance(res_json["data"], dict):
                        verify_url = res_json["data"].get("url") or res_json["data"].get("verify_url") or ""
                    if not verify_url:
                        verify_url = f"https://passport.goofish.com/newlogin/hasLogin.do?hid={self.seller_id}"

                    logger.error(f"❌ 触发闲鱼滑块风控: {ret_value}，验证跳转链接: {verify_url}")

                    # 异步持久化风控状态至数据库
                    try:
                        async with AsyncSessionLocal() as session:
                            stmt = select(Account).where(Account.user_id == self.seller_id)
                            res = await session.execute(stmt)
                            acc = res.scalar_one_or_none()
                            if acc:
                                acc.risk_status = "captcha_required"
                                acc.verify_url = verify_url
                                await session.commit()
                    except Exception as db_err:
                        logger.error(f"更新账号风控状态失败: {db_err}")

                    # 发布风控告警事件，驱动前端工作台弹出滑块辅助页面
                    await event_bus.publish("account_risk", {
                        "seller_id": self.seller_id,
                        "status": "captcha_required",
                        "verify_url": verify_url,
                        "message": "检测到闲鱼 RGV587 滑块验证挑战，请点击辅助过盾"
                    })
                    await event_bus.publish("account_status", {
                        "seller_id": self.seller_id,
                        "status": "captcha_required",
                        "verify_url": verify_url,
                        "message": "检测到滑块风控，请在工作台点击辅助过盾"
                    })
                    return None

                await asyncio.sleep(0.5)
                return await self.get_token(device_id, retry_count + 1)
        except Exception as e:
            logger.error(f"获取 Token 异常: {e}")
            await asyncio.sleep(0.5)
            return await self.get_token(device_id, retry_count + 1)

        return None

    async def get_item_info(self, item_id: str, retry_count: int = 0) -> Optional[Dict[str, Any]]:
        """异步拉取商品详情与 SKU 信息"""
        if retry_count >= 3:
            return None

        t = str(int(time.time()) * 1000)
        data_val = json.dumps({"itemId": item_id})
        token_cookie = self.client.cookies.get('_m_h5_tk', '').split('_')[0]
        sign = generate_sign(t, token_cookie, data_val)

        params = {
            'jsv': '2.7.2',
            'appKey': '34839810',
            't': t,
            'sign': sign,
            'v': '1.0',
            'type': 'originaljson',
            'accountSite': 'xianyu',
            'dataType': 'json',
            'timeout': '20000',
            'api': 'mtop.taobao.idle.pc.detail',
            'sessionOption': 'AutoLoginOnly',
            'spm_cnt': 'a21ybx.im.0.0',
        }

        try:
            resp = await self.client.post(
                'https://h5api.m.goofish.com/h5/mtop.taobao.idle.pc.detail/1.0/',
                params=params,
                data={'data': data_val}
            )
            res_json = resp.json()
            if isinstance(res_json, dict) and any('SUCCESS::调用成功' in ret for ret in res_json.get('ret', [])):
                return res_json.get('data', {}).get('itemDO')
        except Exception as e:
            logger.error(f"拉取商品详情异常 ({item_id}): {e}")

        await asyncio.sleep(0.5)
        return await self.get_item_info(item_id, retry_count + 1)

    async def modify_order_price(self, order_id: str, new_price: float) -> bool:
        """异步调用闲鱼 MTOP 真实改价接口 (针对拍下未付款订单)"""
        t = str(int(time.time()) * 1000)
        data_val = json.dumps({
            "orderId": order_id,
            "modifyPrice": str(round(new_price, 2)),
            "postFee": "0"
        })
        token_cookie = self.client.cookies.get('_m_h5_tk', '').split('_')[0]
        sign = generate_sign(t, token_cookie, data_val)

        params = {
            'jsv': '2.7.2',
            'appKey': '34839810',
            't': t,
            'sign': sign,
            'v': '1.0',
            'type': 'originaljson',
            'accountSite': 'xianyu',
            'dataType': 'json',
            'timeout': '20000',
            'api': 'mtop.taobao.idle.order.price.modify',
            'sessionOption': 'AutoLoginOnly'
        }

        try:
            resp = await self.client.post(
                'https://h5api.m.goofish.com/h5/mtop.taobao.idle.order.price.modify/1.0/',
                params=params,
                data={'data': data_val}
            )
            res_json = resp.json()
            if isinstance(res_json, dict) and any('SUCCESS::调用成功' in ret for ret in res_json.get('ret', [])):
                logger.info(f"订单 {order_id} 闲鱼官方改价成功，新价格: ¥{new_price}")
                return True
            logger.warning(f"订单改价响应: {res_json}")
            return False
        except Exception as e:
            logger.error(f"订单改价请求异常: {e}")
            return False

    async def modify_item_price(self, item_id: str, new_price: float) -> bool:
        """异步调用闲鱼 MTOP 修改商品挂牌标价"""
        t = str(int(time.time()) * 1000)
        data_val = json.dumps({
            "itemId": item_id,
            "soldPrice": str(round(new_price, 2))
        })
        token_cookie = self.client.cookies.get('_m_h5_tk', '').split('_')[0]
        sign = generate_sign(t, token_cookie, data_val)

        params = {
            'jsv': '2.7.2',
            'appKey': '34839810',
            't': t,
            'sign': sign,
            'v': '1.0',
            'type': 'originaljson',
            'accountSite': 'xianyu',
            'dataType': 'json',
            'timeout': '20000',
            'api': 'mtop.taobao.idle.item.edit',
            'sessionOption': 'AutoLoginOnly'
        }

        try:
            resp = await self.client.post(
                'https://h5api.m.goofish.com/h5/mtop.taobao.idle.item.edit/1.0/',
                params=params,
                data={'data': data_val}
            )
            res_json = resp.json()
            if isinstance(res_json, dict) and any('SUCCESS::调用成功' in ret for ret in res_json.get('ret', [])):
                logger.info(f"商品 {item_id} 挂牌标价修改成功，新价格: ¥{new_price}")
                return True
            logger.warning(f"商品标价修改响应: {res_json}")
            return False
        except Exception as e:
            logger.error(f"商品标价修改请求异常: {e}")
            return False

    async def test_proxy(self) -> Dict[str, Any]:
        """测试当前账号的网络代理连通性与出网 IP"""
        start = time.time()
        try:
            resp = await self.client.get("https://httpbin.org/ip", timeout=5.0)
            latency = int((time.time() - start) * 1000)
            data = resp.json()
            return {
                "success": True,
                "ip": data.get("origin", "unknown"),
                "latency_ms": latency,
                "proxy": self.proxy_url or "系统直连"
            }
        except Exception as e:
            try:
                # 备用闲鱼保活健康探测
                ok = await self.has_login()
                latency = int((time.time() - start) * 1000)
                return {
                    "success": ok,
                    "ip": "AliGoofish-Direct",
                    "latency_ms": latency,
                    "proxy": self.proxy_url or "系统直连",
                    "note": "闲鱼直连通讯正常" if ok else str(e)
                }
            except Exception as e2:
                return {
                    "success": False,
                    "error": str(e2),
                    "proxy": self.proxy_url or "系统直连"
                }

    async def close(self):
        """关闭客户端"""
        await self.client.aclose()

