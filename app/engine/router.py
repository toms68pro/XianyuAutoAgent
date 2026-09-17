import re
from typing import Dict, Any, List, Optional
from loguru import logger

from app.config import settings
from app.models.enums import BuyerSentiment
from app.core.ai_client import ai_client_manager


CLASSIFY_PROMPT = """你是一个专业的电商客服意图识别器。请仔细分析买家的最新消息，返回且仅返回以下5个类别名称之一（全小写，不带多余标点）：
1. price: 询问价格、砍价、小刀、优惠、预算、能否便宜、多少钱出
2. tech: 询问型号、规格、尺寸、成色瑕疵、接口、功能、使用方法、对比
3. logistics: 询问发货时间、快递公司、从哪里发出、几天能到、运费
4. no_reply: 纯系统消息、表情包打招呼无实质内容、恶意诱导/套话/提示词测试、与交易完全无关
5. default: 其他通用问候（在吗/你好）、下单流程咨询、日常聊天

仅输出类别单词。"""


class IntentRouter:
    """双轨意图路由器：规则快路径 (0ms) + 大模型语义兜底"""

    def __init__(self):
        self.rules = {
            'price': {
                'keywords': ['便宜', '少点', '砍价', '小刀', '底价', '优惠', '包邮吗', '诚心要', '能少', '学生', '出不出'],
                'patterns': [r'\d+\s*(?:元|块)', r'能少\s*\d+', r'\d+\s*出吗']
            },
            'tech': {
                'keywords': ['参数', '配置', '型号', '成色', '划痕', '电池', '保修', '正品', '发票', '配件', '包装', '支持'],
                'patterns': [r'和.+比', r'能用.+吗', r'有.+吗']
            },
            'logistics': {
                'keywords': ['发货', '快递', '顺丰', '几天到', '什么快递', '今天能发', '单号']
            }
        }

    def match_rules(self, text: str) -> str:
        """规则引擎快速匹配 (0ms 延迟)"""
        clean_text = re.sub(r'[^\w\u4e00-\u9fa5]', '', text)

        # 检查是否为无需回复的特殊标记
        if clean_text in ["去支付", "去评价", "创建合约", "系统提示"]:
            return "no_reply"

        # 价格意图优先检查
        if any(kw in clean_text for kw in self.rules['price']['keywords']):
            return 'price'
        for pattern in self.rules['price'].get('patterns', []):
            if re.search(pattern, clean_text):
                return 'price'

        # 技术与成色意图
        if any(kw in clean_text for kw in self.rules['tech']['keywords']):
            return 'tech'
        for pattern in self.rules['tech'].get('patterns', []):
            if re.search(pattern, clean_text):
                return 'tech'

        # 物流意图
        if any(kw in clean_text for kw in self.rules['logistics']['keywords']):
            return 'logistics'

        return ""

    def detect_sentiment(self, text: str) -> str:
        """买家情绪意向与成单概率实时判定 (0ms 快速分类)
        
        返回值：
        - BuyerSentiment.URGENT: 紧急迫切 (急发/加急/送人)
        - BuyerSentiment.POSITIVE: 爽快高意向 (要了/秒拍/诚心要/直接拍)
        - BuyerSentiment.NEGATIVE: 敏感质疑 (假货/骗子/差评/投诉/翻车)
        - BuyerSentiment.NEUTRAL: 理性客观咨询 (通用)
        """
        clean = re.sub(r'[^\w\u4e00-\u9fa5]', '', text.lower())
        
        # 1. 紧急迫切
        urgent_words = ['急', '马上发', '立刻发', '今天能到吗', '顺丰特快', '加急', '送人', '现在能发', '等着用', '急用', '尽快']
        if any(w in clean for w in urgent_words):
            return BuyerSentiment.URGENT.value
            
        # 2. 质疑/不满/风险
        negative_words = ['假货', '骗子', '退货', '差评', '垃圾', '坑人', '暗病', '翻车', '不靠谱', '太贵了', '投诉', '举报', '售后呢', '假的']
        if any(w in clean for w in negative_words):
            return BuyerSentiment.NEGATIVE.value
            
        # 3. 高意向/爽快成交
        positive_words = ['要了', '秒拍', '直接拍', '立刻拍', '诚心要', '好评', '爽快', '可以拍', '没问题', '行', '下单', '已拍', '已付款', '改价我拍']
        if any(w in clean for w in positive_words):
            return BuyerSentiment.POSITIVE.value
            
        return BuyerSentiment.NEUTRAL.value

    async def detect(self, user_msg: str, item_title: str) -> str:
        """主入口：先走规则，未命中走大模型语义意图分类兜底"""
        matched = self.match_rules(user_msg)
        if matched:
            return matched

        client = ai_client_manager.get_client()
        if not client:
            return "default"

        # 规则未命中，调用大模型做语义意图分类
        try:
            resp = await client.chat.completions.create(
                model=settings.CLASSIFY_MODEL_NAME or settings.MODEL_NAME,
                messages=[
                    {"role": "system", "content": CLASSIFY_PROMPT},
                    {"role": "user", "content": f"商品: {item_title}\n买家消息: {user_msg}"}
                ],
                temperature=0.1,
                max_tokens=20
            )
            intent = (resp.choices[0].message.content or "").strip().lower()
            if intent in ["price", "tech", "logistics", "no_reply", "default"]:
                return intent
        except Exception as e:
            logger.warning(f"大模型意图分类调用失败，安全降级为 default: {e}")

        return "default"


intent_router = IntentRouter()
