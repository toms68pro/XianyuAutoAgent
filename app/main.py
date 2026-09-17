import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from loguru import logger
from sqlalchemy import select

from app.config import settings
from app.core.database import init_db, AsyncSessionLocal
from app.models.entities import Account
from app.protocol.connection import connection_hub
from app.protocol.utils import trans_cookies

# 导入各模块 API 路由
from app.api.conversations import router as conv_router
from app.api.messages import router as msg_router
from app.api.items import router as item_router
from app.api.accounts import router as acc_router
from app.api.stats import router as stat_router
from app.api.sse import router as sse_router
from app.api.faqs import router as faq_router
from app.api.order_rules import router as order_rule_router
from app.api.orders import router as order_router
from app.api.cards import router as card_router
from app.api.canned_replies import router as canned_router

# 激活事件监听器 (告警通知中心与自动化履约发货引擎)
import app.core.notifier
import app.engine.fulfillment



@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：异步初始化数据库与长连接池"""
    logger.info("🚀 Xianyu AutoAgent Pro 2.0 服务启动中...")
    
    # 1. 初始化数据库表结构
    await init_db()

    # 2. 检查并启动默认账号
    async with AsyncSessionLocal() as session:
        # 优先读取数据库中的账号
        stmt = select(Account).where(Account.is_active == True)
        res = await session.execute(stmt)
        active_accounts = res.scalars().all()

        if active_accounts:
            for acc in active_accounts:
                logger.info(f"正在从数据库自动恢复账号长连接: {acc.user_id} ({acc.nickname})")
                connection_hub.start_account(acc.user_id, acc.cookie_str, acc.proxy_url)
        elif settings.COOKIES_STR:
            # 回退使用 .env 中的 COOKIES_STR
            cookies_dict = trans_cookies(settings.COOKIES_STR)
            seller_id = cookies_dict.get("unb")
            if seller_id:
                logger.info(f"正在从环境变量注册并启动默认账号: {seller_id}")
                acc = Account(
                    user_id=seller_id,
                    nickname="默认店铺",
                    cookie_str=settings.COOKIES_STR,
                    is_active=True
                )
                session.add(acc)
                await session.commit()
                connection_hub.start_account(seller_id, settings.COOKIES_STR)

    logger.info(f"✅ 后端核心网关就绪，控制台地址: http://{settings.SERVER_HOST}:{settings.SERVER_PORT}")
    yield

    # 优雅停机：释放所有长连接与 HTTP 资源池
    logger.info("正在优雅关闭所有闲鱼 WSS 通道与网络连接池...")
    for uid in list(connection_hub.instances.keys()):
        connection_hub.stop_account(uid)
    from app.core.ai_client import ai_client_manager
    await ai_client_manager.close()
    logger.info("已安全停机")


app = FastAPI(
    title="Xianyu AutoAgent Pro API",
    description="工业级闲鱼全自动客服与多账号矩阵协同系统",
    version="2.0.0",
    lifespan=lifespan
)

# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册 API 路由
app.include_router(conv_router)
app.include_router(msg_router)
app.include_router(item_router)
app.include_router(acc_router)
app.include_router(stat_router)
app.include_router(sse_router)
app.include_router(faq_router)
app.include_router(order_rule_router)
app.include_router(order_router)
app.include_router(card_router)
app.include_router(canned_router)



@app.get("/health")
async def health_check():
    """系统健康检查端点"""
    return {
        "status": "healthy",
        "version": "2.0.0",
        "active_accounts": len(connection_hub.instances)
    }


# 静态资源与前端单页应用路由
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    async def serve_index():
        """根路径返回现代化卖家 Copilot 工作台"""
        index_file = os.path.join(static_dir, "index.html")
        return FileResponse(index_file)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.SERVER_HOST,
        port=settings.SERVER_PORT,
        reload=False
    )
