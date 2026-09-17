import os
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from loguru import logger
from app.config import settings

# 确保 SQLite 目标目录存在
if settings.DATABASE_URL.startswith("sqlite"):
    db_path = settings.DATABASE_URL.replace("sqlite+aiosqlite:///", "")
    os.makedirs(os.path.dirname(db_path or "data/xianyu_v2.db"), exist_ok=True)

# 构造全异步数据库引擎配置 (PostgreSQL 18 生产连接池 vs SQLite 轻量模式)
engine_kwargs = {
    "echo": False,
    "future": True,
    "pool_pre_ping": True,
}

if settings.DATABASE_URL.startswith("postgresql"):
    engine_kwargs.update({
        "pool_size": 20,
        "max_overflow": 10,
        "pool_recycle": 3600,
        "pool_timeout": 30,
    })

engine = create_async_engine(
    settings.DATABASE_URL,
    **engine_kwargs
)

# 异步会话工厂
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

Base = declarative_base()


async def init_db():
    """初始化数据库架构 (自动建表与自愈增量迁移)"""
    # 显式导入所有 ORM 实体，确保 Base.metadata 注册所有数据表
    import app.models.entities  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # SQLite 自适应增量字段补齐 (向后兼容平滑迁移)
        if settings.DATABASE_URL.startswith("sqlite"):
            from sqlalchemy import text
            table_check = await conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='accounts'")
            )
            if table_check.scalar():
                res = await conn.execute(text("PRAGMA table_info(accounts)"))
                columns = [row[1] for row in res.fetchall()]
                if "proxy_url" not in columns:
                    await conn.execute(text("ALTER TABLE accounts ADD COLUMN proxy_url VARCHAR(256)"))
                if "risk_status" not in columns:
                    await conn.execute(text("ALTER TABLE accounts ADD COLUMN risk_status VARCHAR(32) DEFAULT 'normal'"))
                if "verify_url" not in columns:
                    await conn.execute(text("ALTER TABLE accounts ADD COLUMN verify_url TEXT"))

    # 初始化默认常用快捷话术种子数据
    try:
        from app.models.entities import CannedReply
        from sqlalchemy import select
        async with AsyncSessionLocal() as session:
            check_res = await session.execute(select(CannedReply).limit(1))
            if not check_res.scalars().first():
                default_canned = [
                    CannedReply(title="💎 99新无瑕疵", content="成色 99 新，屏幕无划痕亮斑，按键阻尼完好，支持闲鱼验货宝！", category="成色品质"),
                    CannedReply(title="🚚 顺丰当天发出", content="现货在手！当天下午 6 点前拍下默认顺丰发出，附带防震包装~", category="物流时效"),
                    CannedReply(title="🤝 送配件包顺丰挽留", content="标价已是非常诚意的高性价比出价啦，爽快再送您小配件并包顺丰！", category="议价挽留"),
                    CannedReply(title="📦 加厚防震包装", content="商品均采用定制五层加厚纸箱 + 加厚气泡膜缠绕发货，抗摔防震~", category="物流时效"),
                    CannedReply(title="⚡ 拍下立即改价", content="诚心要可直接拍下，我后台马上为您改价~", category="议价挽留"),
                    CannedReply(title="🛡️ 验机退换保证", content="支持收货后24小时内验机，功能成色不符包退，请放心~", category="售后保证")
                ]
                session.add_all(default_canned)
                await session.commit()
    except Exception as e:
        logger.warning(f"种子话术初始化跳过: {e}")

    logger.info("异步数据库引擎初始化完毕，数据表结构就绪")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖注入：获取数据库会话"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
