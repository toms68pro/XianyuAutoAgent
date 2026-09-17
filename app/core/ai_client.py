"""
工业级大模型客户端连接管理 (AI Client Manager)
集中管理基于 AsyncOpenAI 与 httpx 的连接池生命周期、避免资源泄漏与杜绝伪造密钥
"""
from typing import Optional
import httpx
from openai import AsyncOpenAI
from loguru import logger
from app.config import settings


class AIConfigurationError(Exception):
    """大模型服务配置异常"""
    pass


class AIClientManager:
    """大模型客户端单例管理器，提供连接池复用与优雅降级控制"""

    _instance: Optional["AIClientManager"] = None
    _client: Optional[AsyncOpenAI] = None
    _http_client: Optional[httpx.AsyncClient] = None

    def __new__(cls) -> "AIClientManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def is_configured(self) -> bool:
        """检查大模型服务凭据是否已有效配置"""
        return bool(settings.API_KEY and settings.API_KEY.strip())

    def get_client(self, timeout: float = 25.0) -> Optional[AsyncOpenAI]:
        """获取或惰性初始化 AsyncOpenAI 客户端单例"""
        if not self.is_configured:
            return None

        if self._client is None:
            self._http_client = httpx.AsyncClient(
                trust_env=False,
                timeout=httpx.Timeout(timeout, connect=10.0)
            )
            self._client = AsyncOpenAI(
                api_key=settings.API_KEY.strip(),
                base_url=settings.MODEL_BASE_URL,
                http_client=self._http_client
            )
        return self._client

    async def close(self):
        """优雅释放 HTTP 连接池"""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None
            self._client = None
            logger.debug("大模型底层 HTTP 客户端连接池已优雅释放")


ai_client_manager = AIClientManager()
