from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.models.entities import Conversation, Message, Item, Account

router = APIRouter(prefix="/api/stats", tags=["统计数据看板"])


@router.get("", include_in_schema=False)
@router.get("/", include_in_schema=False)
@router.get("/dashboard")
async def get_dashboard_stats(db: AsyncSession = Depends(get_db)):
    """获取仪表盘核心指标"""
    # 账号统计
    acc_count = (await db.execute(select(func.count(Account.id)))).scalar() or 0
    
    # 会话统计
    total_convs = (await db.execute(select(func.count(Conversation.id)))).scalar() or 0
    auto_convs = (await db.execute(select(func.count(Conversation.id)).where(Conversation.copilot_mode == "auto"))).scalar() or 0
    manual_convs = (await db.execute(select(func.count(Conversation.id)).where(Conversation.copilot_mode == "manual"))).scalar() or 0
    draft_convs = (await db.execute(select(func.count(Conversation.id)).where(Conversation.copilot_mode == "draft"))).scalar() or 0
    bargain_convs = (await db.execute(select(func.count(Conversation.id)).where(Conversation.bargain_count > 0))).scalar() or 0

    # 消息统计
    total_msgs = (await db.execute(select(func.count(Message.id)))).scalar() or 0
    ai_msgs = (await db.execute(select(func.count(Message.id)).where(Message.role == "assistant"))).scalar() or 0
    manual_msgs = (await db.execute(select(func.count(Message.id)).where(Message.role == "seller_manual"))).scalar() or 0

    # 商品库统计
    total_items = (await db.execute(select(func.count(Item.item_id)))).scalar() or 0

    return {
        "accounts_count": acc_count,
        "total_conversations": total_convs,
        "auto_conversations": auto_convs,
        "manual_conversations": manual_convs,
        "draft_conversations": draft_convs,
        "bargain_conversations": bargain_convs,
        "total_messages": total_msgs,
        "ai_messages": ai_msgs,
        "manual_messages": manual_msgs,
        "total_items": total_items,
        "ai_handling_rate": round(ai_msgs / max(total_msgs, 1) * 100, 1)
    }
