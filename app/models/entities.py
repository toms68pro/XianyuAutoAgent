import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy import (
    Column, Integer, String, Text, Float, Boolean, DateTime, Index
)
from app.core.database import Base


class Account(Base):
    """闲鱼店铺/卖家账号模型 (支持多账号矩阵)"""
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), unique=True, nullable=False, index=True, comment="闲鱼卖家用户ID (unb)")
    nickname = Column(String(128), default="闲鱼卖家", comment="店铺/账号展示昵称")
    cookie_str = Column(Text, nullable=False, comment="当前绑定的Cookie凭据")
    device_id = Column(String(128), nullable=True, comment="模拟设备唯一标识码")
    access_token = Column(String(256), nullable=True, comment="当前活跃的消息通道 Token")
    proxy_url = Column(String(256), nullable=True, comment="独立绑定的网络代理(http/socks5)")
    risk_status = Column(String(32), default="normal", comment="风控状态: normal/captcha_required/cookie_expired")
    verify_url = Column(Text, nullable=True, comment="滑块挑战或风控验证跳转链接")
    is_active = Column(Boolean, default=True, comment="是否开启自动值守")
    connection_status = Column(String(32), default="offline", comment="连接状态: online/offline/error/reconnecting")
    last_active_at = Column(DateTime, default=datetime.utcnow, comment="最后活跃时间")
    created_at = Column(DateTime, default=datetime.utcnow)


class Conversation(Base):
    """买家会话模型与协同状态"""
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(String(128), unique=True, nullable=False, index=True, comment="闲鱼会话唯一标识")
    seller_id = Column(String(64), nullable=False, index=True, comment="所属卖家ID")
    buyer_id = Column(String(64), nullable=False, index=True, comment="买家ID")
    buyer_name = Column(String(128), default="闲鱼买家", comment="买家昵称")
    item_id = Column(String(64), nullable=True, index=True, comment="当前咨询的商品ID")

    # 协同模式: 'auto' (AI全托管自动回复) | 'draft' (AI草稿待审核) | 'manual' (人工完全接管)
    copilot_mode = Column(String(32), default="auto", nullable=False)
    manual_takeover_at = Column(DateTime, nullable=True, comment="进入人工接管的时间")
    
    # 业务与画像指标
    bargain_count = Column(Integer, default=0, comment="当前会话发生的累计议价轮次")
    latest_intent = Column(String(64), default="default", comment="最近识别出的买家意图")
    buyer_sentiment = Column(String(32), default="neutral", comment="买家情绪: positive/neutral/negative/urgent")
    unread_count = Column(Integer, default=0, comment="未读消息数")
    
    last_message_at = Column(DateTime, default=datetime.utcnow, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Message(Base):
    """聊天消息记录与 AI 决策审计流"""
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(String(128), nullable=False, index=True)
    seller_id = Column(String(64), nullable=False)
    item_id = Column(String(64), nullable=True)
    sender_id = Column(String(64), nullable=False)
    
    # 角色: 'user'(买家) | 'assistant'(AI助手) | 'seller_manual'(卖家插话) | 'system'(系统通知)
    role = Column(String(32), nullable=False)
    content = Column(Text, nullable=False)
    
    # AI 决策详情 (用于工作台透明展示)
    intent = Column(String(64), nullable=True, comment="命中的意图类别")
    ai_thinking = Column(Text, nullable=True, comment="大模型思考过程与守卫逻辑说明")
    
    # 人机协同草稿状态: 'none' | 'pending' | 'approved' | 'rejected' | 'edited'
    draft_status = Column(String(32), default="none")
    
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_chat_time", "chat_id", "timestamp"),
    )


class Item(Base):
    """商品库与确定性价格守卫策略配置"""
    __tablename__ = "items"

    item_id = Column(String(64), primary_key=True, comment="闲鱼商品唯一ID")
    title = Column(String(256), default="", comment="商品标题")
    desc = Column(Text, default="", comment="商品详情介绍")
    price = Column(Float, default=0.0, comment="当前挂牌标价 (元)")
    
    # 确定性价格护栏 (Guardrail Rules) - 100% 规则约束
    min_price = Column(Float, default=0.0, comment="绝对守价底线 (不可突破的最低成交价)")
    step_discount = Column(Float, default=0.0, comment="单轮议价最大让步额度 (元)")
    max_bargain_rounds = Column(Integer, default=3, comment="最大允许议价轮次")
    allow_gift = Column(Boolean, default=True, comment="是否允许以赠品代替降价")
    gift_description = Column(String(256), default="赠送配套配件 / 包顺丰快递", comment="赠品或服务让步话术")
    
    sku_details = Column(Text, default="[]", comment="SKU 规格列表 (JSON 字符串)")
    tech_specs = Column(Text, default="", comment="商品技术参数/成色说明 (用于专业问答 RAG)")
    stock = Column(Integer, default=1, comment="库存数量")
    last_updated = Column(DateTime, default=datetime.utcnow)

    def get_sku_list(self) -> List[Dict[str, Any]]:
        try:
            return json.loads(self.sku_details or "[]")
        except Exception:
            return []

    def set_sku_list(self, skus: List[Dict[str, Any]]):
        self.sku_details = json.dumps(skus, ensure_ascii=False)


class FAQ(Base):
    """商品与店铺常见问题知识库 (用于 RAG 检索增强)"""
    __tablename__ = "faqs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(String(64), nullable=True, index=True, comment="特定关联商品ID(为空则为全店通用)")
    question = Column(String(256), nullable=False, comment="常见买家问题")
    answer = Column(Text, nullable=False, comment="官方标准答复")
    keywords = Column(String(256), default="", comment="关联标签/关键词，逗号分隔")
    created_at = Column(DateTime, default=datetime.utcnow)


class OrderRule(Base):
    """订单履约与虚拟商品自动发货规则模型"""
    __tablename__ = "order_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(String(64), nullable=True, index=True, comment="关联商品ID(为空则对所有商品生效)")
    trigger_event = Column(String(64), default="等待卖家发货", comment="触发状态: 等待卖家发货 / 等待买家付款")
    auto_reply_text = Column(Text, nullable=False, comment="自动回复内容(含卡密/网盘提取码/发货感谢词)")
    is_active = Column(Boolean, default=True, comment="是否启用该自动化发货规则")
    created_at = Column(DateTime, default=datetime.utcnow)


class CardKey(Base):
    """虚拟商品卡密/资产库存模型 (一卡一密自动核销出库)"""
    __tablename__ = "card_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(String(64), nullable=True, index=True, comment="关联商品ID(为空则为通用卡密)")
    card_code = Column(Text, nullable=False, comment="卡密信息/网盘链接/激活码")
    status = Column(String(32), default="available", index=True, comment="状态: available(待发放) / used(已核销)")
    buyer_id = Column(String(64), nullable=True, comment="发放的买家ID")
    order_id = Column(String(128), nullable=True, comment="关联订单号")
    created_at = Column(DateTime, default=datetime.utcnow)
    used_at = Column(DateTime, nullable=True, comment="核销发放时间")


class CannedReply(Base):
    """常用快捷话术库模型 (支持卖家个性化维护)"""
    __tablename__ = "canned_replies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(64), nullable=False, comment="话术快捷简称")
    content = Column(Text, nullable=False, comment="话术正文")
    category = Column(String(32), default="通用", comment="分类: 议价挽留/成色品质/物流时效/售后保证")
    created_at = Column(DateTime, default=datetime.utcnow)

