import re
from typing import Optional, Dict, Any
from loguru import logger


class SemanticCache:
    """
    高频电商问答语义缓存引擎 (Semantic Cache)
    对高频问候、物流时效、正品成色保证等常见问询实现 <10ms 极速秒回，
    大幅削减云端大模型 API Token 消耗与网络延时。
    """

    # 预置高频意图与高质量标准话术 (覆盖二手高频问答)
    BUILTIN_PATTERNS = [
        {
            "intent": "greeting",
            "regex": r"^(你好|您好|哈喽|hello|hi|在吗|在么|在不在|在不|亲|老板)[\s,，.。!！?？~～]*(在吗|在么|在不在|在不|你好|您好|亲)?[\s!！?？~～]*$",
            "reply": "在的亲！商品成色完好、功能正常，看好可以直接拍下，今天就能为您发出~"
        },
        {
            "intent": "shipping_time",
            "regex": r"^(今天|现在|什么时候|几天)?\s*(能发吗|发货吗|发货|发什么快递|现货吗|多久能发|发货不|什么时候发|几天能到|马上能发吗)[\s!！?？~～]*$",
            "reply": "现货在手！当天下午 6 点前拍下默认当天发出，默认顺丰/圆通速递，包裹均有专业防震气泡加固~"
        },
        {
            "intent": "authenticity",
            "regex": r"^(保真吗|是正品吗|假一赔几|支持验机吗|支持验货宝吗|官方正品吗|支持验货吗|保正吗)[\s!！?？~～]*$",
            "reply": "保真保正品！支持闲鱼官方验货宝验机，收货后功能成色不符支持无理由退换，请放心下单~"
        },
        {
            "intent": "free_shipping",
            "regex": r"^(能|可以|顺丰|能不能)?\s*(包邮吗|包邮不|包个邮|免运费吗|包运费吗|运费多少)[\s!！?？~～]*$",
            "reply": "诚心要可以给您包顺丰发出！看好可以直接拍下，今天就为您打包寄出~"
        },
        {
            "intent": "condition_inquiry",
            "regex": r"^(成色怎么样|成色如何|外观有磨损吗|有划痕吗|功能正常吗|有暗病吗|电池健康多少)[\s!！?？~～]*$",
            "reply": "功能全好、无暗病！实物拍摄无滤镜遮掩，关键功能均已全面检测，收到支持24小时验机~"
        },
        {
            "intent": "accessories",
            "regex": r"^(配件齐全吗|带包装盒吗|有发票吗|箱说全吗|带充电器吗|单机还是全套)[\s!！?？~～]*$",
            "reply": "包含配件详见商品描述与实拍图，发货前均会细致加固包装，看好直接拍下即可~"
        },
        {
            "intent": "pickup",
            "regex": r"^(支持自提吗|能同城自提吗|支持面交吗|能面交吗|同城能送吗|在哪里自提)[\s!！?？~～]*$",
            "reply": "支持同城面交自提！也可以直接下单选择同城顺丰闪送，当日即可送达~"
        },
        {
            "intent": "minimal_cut",
            "regex": r"^(5块钱出吗|10块钱卖吗|白送行不行|对半出不|半价卖吗|五折出吗)[\s!！?？~～]*$",
            "reply": "抱歉哦亲，屠龙刀实在出不了呢，标价已是非常诚意的高性价比出价啦~"
        }
    ]


    def __init__(self):
        self._compiled = [
            {"intent": p["intent"], "regex": re.compile(p["regex"], re.IGNORECASE), "reply": p["reply"]}
            for p in self.BUILTIN_PATTERNS
        ]
        # 内存动态 LRU 缓存字典: normalized_query -> reply
        self._dynamic_cache: Dict[str, str] = {}
        self._redis = None

        # 若配置了 REDIS_URL，初始化 Redis 8 异步连接池
        try:
            from app.config import settings
            if getattr(settings, "REDIS_URL", None):
                import redis.asyncio as aioredis
                self._redis = aioredis.from_url(
                    settings.REDIS_URL,
                    decode_responses=True,
                    socket_timeout=2.0
                )
                logger.info("⚡ Redis 8 语义缓存引擎与连接池已就绪")
        except Exception as e:
            logger.warning(f"Redis 8 驱动加载或连接初始化跳过: {e}")

    def _normalize(self, text: str) -> str:
        """文本去标点、去空、归一化"""
        return re.sub(r'[^\w\u4e00-\u9fa5]', '', text).lower()

    def get(self, query: str) -> Optional[Dict[str, Any]]:
        """同步检索语义缓存 (本地正则与内存高速检索)"""
        norm = self._normalize(query)
        if not norm:
            return None

        # 1. 动态精确缓存命中
        if norm in self._dynamic_cache:
            logger.debug(f"⚡ 动态语义缓存直接命中: {norm}")
            return {
                "reply": self._dynamic_cache[norm],
                "intent": "cache_hit",
                "source": "dynamic_memory_cache"
            }

        # 2. 正则高频模式快速命中
        for item in self._compiled:
            if item["regex"].search(query.strip()):
                logger.info(f"⚡ 高频问候语义缓存秒级命中 [{item['intent']}]: {query}")
                return {
                    "reply": item["reply"],
                    "intent": item["intent"],
                    "source": "builtin_semantic_cache"
                }

        return None

    async def get_async(self, query: str) -> Optional[Dict[str, Any]]:
        """异步检索语义缓存 (优先内存正则 -> Redis 8 分布式缓存 -> 内存动态字典)"""
        # 1. 先走本地同步高速校验 (<0.1ms)
        sync_hit = self.get(query)
        if sync_hit:
            return sync_hit

        # 2. Redis 8 分布式缓存检索 (若启用)
        norm = self._normalize(query)
        if norm and self._redis:
            try:
                val = await self._redis.get(f"xianyu:cache:{norm}")
                if val:
                    logger.info(f"⚡ Redis 8 分布式语义缓存命中: {norm}")
                    return {
                        "reply": val,
                        "intent": "cache_hit",
                        "source": "redis_8_cache"
                    }
            except Exception as e:
                logger.debug(f"Redis 8 缓存查询异常: {e}")

        return None

    def set(self, query: str, reply: str):
        """记录动态成功回复至内存缓存"""
        norm = self._normalize(query)
        if norm and len(norm) <= 30 and len(reply) <= 120:
            if len(self._dynamic_cache) > 1000:
                self._dynamic_cache.clear()
            self._dynamic_cache[norm] = reply

    async def set_async(self, query: str, reply: str):
        """异步记录成功回复至内存与 Redis 8 (TTL 24小时)"""
        norm = self._normalize(query)
        if not norm or len(norm) > 30 or len(reply) > 120:
            return

        self.set(query, reply)

        if self._redis:
            try:
                await self._redis.setex(f"xianyu:cache:{norm}", 86400, reply)
            except Exception as e:
                logger.debug(f"Redis 8 缓存写入异常: {e}")


semantic_cache = SemanticCache()
