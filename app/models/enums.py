"""
闲鱼智能客服核心领域枚举定义 (Domain Enums)
遵循 DDD 规范，提供强类型状态机与业务数据字典，杜绝魔法字符串
"""
from enum import Enum


class CopilotMode(str, Enum):
    """人机协同工作模式"""
    AUTO = "auto"        # AI 全托管：自动思考决策并即时回复
    DRAFT = "draft"      # 草稿模式：AI 生成回复建议，待卖家确认后发送
    MANUAL = "manual"    # 人工接管：AI 保持静默，由人工完全操作


class BuyerSentiment(str, Enum):
    """买家情绪意向评级"""
    URGENT = "urgent"      # 紧迫/急购：催发货、急用、马上买
    POSITIVE = "positive"  # 高意向/爽快：诚心要、直接拍、改价秒付款
    NEGATIVE = "negative"  # 敏感/质疑：怀疑假货、差评、投诉、风险
    NEUTRAL = "neutral"    # 中性/日常：常规参数、规格咨询


class MessageRole(str, Enum):
    """消息发送方角色"""
    USER = "user"                    # 买家
    ASSISTANT = "assistant"          # AI 客服助手
    SELLER_MANUAL = "seller_manual"  # 卖家人工插话
    SYSTEM = "system"                # 系统自动化通知


class DraftStatus(str, Enum):
    """AI 草稿状态"""
    NONE = "none"                # 非草稿 (常规已发送消息)
    PENDING = "pending"          # 待人工审批放行
    APPROVED = "approved"        # 已人工放行并发送
    REJECTED = "rejected"        # 已人工驳回
    DIRECT_SENT = "direct_sent"  # 快捷指令/改价直接发送


class RiskStatus(str, Enum):
    """闲鱼店铺风控状态"""
    NORMAL = "normal"                        # 正常
    CAPTCHA_REQUIRED = "captcha_required"    # 触发 RGV587 滑块验证
    COOKIE_EXPIRED = "cookie_expired"        # 登录凭据过期失效


class ConnectionStatus(str, Enum):
    """WSS 长连接通道状态"""
    ONLINE = "online"                        # 在线值守
    OFFLINE = "offline"                      # 离线
    RECONNECTING = "reconnecting"            # 正在重连
    CAPTCHA_REQUIRED = "captcha_required"    # 需辅助过盾
    ERROR = "error"                          # 异常断开


class CardKeyStatus(str, Enum):
    """虚拟卡密/数字资产状态"""
    AVAILABLE = "available"  # 待发放库存
    USED = "used"            # 已核销发放
