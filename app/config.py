import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """全局系统配置，支持从 .env 自动加载与强类型校验"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # 模型配置 (兼容 OpenAI / DashScope / DeepSeek / 本地 Ollama)
    API_KEY: str = Field(default="", description="大模型 API Key")
    MODEL_BASE_URL: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        description="模型服务基地址"
    )
    MODEL_NAME: str = Field(default="qwen-max", description="主模型名称")
    CLASSIFY_MODEL_NAME: Optional[str] = Field(default=None, description="意图分类轻量模型(可选,留空则使用主模型)")

    # 闲鱼账号凭据
    COOKIES_STR: str = Field(default="", description="闲鱼网页端提取的完整Cookie字符串")

    # 数据库与中间件
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///data/xianyu_v2.db",
        description="异步数据库连接串 (支持 SQLite / PostgreSQL 18: postgresql+asyncpg://user:pass@host:5432/dbname)"
    )
    REDIS_URL: Optional[str] = Field(
        default=None,
        description="Redis 8 连接串 (如 redis://localhost:6379/0，可选，用于高并发分布式会话/语义缓存/锁)"
    )

    # 协议与心跳
    WSS_URL: str = Field(
        default="wss://wss-goofish.dingtalk.com/",
        description="闲鱼 WSS 消息网关地址"
    )
    HEARTBEAT_INTERVAL: int = Field(default=15, description="心跳上报间隔(秒)")
    HEARTBEAT_TIMEOUT: int = Field(default=8, description="心跳超时判定阈值(秒)")
    TOKEN_REFRESH_INTERVAL: int = Field(default=3600, description="Token无感刷新周期(秒)")
    TOKEN_RETRY_INTERVAL: int = Field(default=180, description="Token刷新失败重试间隔(秒)")
    MESSAGE_EXPIRE_TIME: int = Field(default=300000, description="历史消息时效过滤(毫秒,默认5分钟)")

    # 人机协同与接管
    MANUAL_MODE_TIMEOUT: int = Field(default=3600, description="人工接管自动超时退回时长(秒)")
    TOGGLE_KEYWORDS: str = Field(default="。", description="人工接管快捷触发关键词")
    SIMULATE_HUMAN_TYPING: bool = Field(default=False, description="是否启用拟人化随机打字延时")
    DEFAULT_COPILOT_MODE: str = Field(default="auto", description="默认协同模式: auto(全托管) / draft(草稿待确认) / manual(全人工)")
    MESSAGE_DEBOUNCE_SECONDS: float = Field(default=2.5, description="买家连续短消息防抖聚合窗口时长(秒)")
    PROXY_URL: Optional[str] = Field(default=None, description="全局网络代理 (如 http://127.0.0.1:7890 或 socks5://...)")

    # 多渠道消息与告警通知 (钉钉/飞书/企业微信/Bark)
    DINGTALK_WEBHOOK: Optional[str] = Field(default=None, description="钉钉机器人 Webhook 地址")
    FEISHU_WEBHOOK: Optional[str] = Field(default=None, description="飞书机器人 Webhook 地址")
    WECOM_WEBHOOK: Optional[str] = Field(default=None, description="企业微信机器人 Webhook 地址")
    BARK_URL: Optional[str] = Field(default=None, description="Bark iOS 推送地址")
    NOTIFY_ON_ORDER: bool = Field(default=True, description="订单支付或成交时通知")
    NOTIFY_ON_CAPTCHA: bool = Field(default=True, description="遭遇滑块风控时通知")
    NOTIFY_ON_TAKEOVER: bool = Field(default=True, description="触发人工接管时通知")

    # 服务网关
    SERVER_HOST: str = Field(default="0.0.0.0", description="Web 控制台监听地址")
    SERVER_PORT: int = Field(default=8000, description="Web 控制台监听端口")
    LOG_LEVEL: str = Field(default="INFO", description="日志级别")


settings = Settings()
