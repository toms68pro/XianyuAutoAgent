from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel

from app.core.database import get_db
from app.core.event_bus import event_bus
from app.models.entities import Conversation, Message
from app.models.enums import CopilotMode

router = APIRouter(prefix="/api/conversations", tags=["会话管理"])


class ConversationOut(BaseModel):
    id: int
    chat_id: str
    seller_id: str
    buyer_id: str
    buyer_name: str
    item_id: Optional[str] = None
    copilot_mode: str
    bargain_count: int
    latest_intent: str
    buyer_sentiment: str = "neutral"
    unread_count: int
    last_message_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class MessageOut(BaseModel):
    id: int
    chat_id: str
    seller_id: str
    sender_id: str
    role: str
    content: str
    intent: Optional[str] = None
    ai_thinking: Optional[str] = None
    draft_status: str
    timestamp: datetime

    class Config:
        from_attributes = True


class ModeUpdateRequest(BaseModel):
    copilot_mode: CopilotMode


@router.get("", response_model=List[ConversationOut])
async def list_conversations(
    status: Optional[str] = Query(None, description="状态筛选: auto/draft/manual/bargain"),
    search: Optional[str] = Query(None, description="搜索买家昵称或ID"),
    db: AsyncSession = Depends(get_db)
):
    """获取所有会话列表"""
    query = select(Conversation).order_by(desc(Conversation.last_message_at))

    if status == "bargain":
        query = query.where(Conversation.bargain_count > 0)
    elif status:
        query = query.where(Conversation.copilot_mode == status)

    if search:
        query = query.where(
            (Conversation.buyer_name.contains(search)) |
            (Conversation.chat_id.contains(search))
        )

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{chat_id}", response_model=ConversationOut)
async def get_conversation(chat_id: str, db: AsyncSession = Depends(get_db)):
    """获取单个会话详情"""
    stmt = select(Conversation).where(Conversation.chat_id == chat_id)
    res = await db.execute(stmt)
    conv = res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conv


@router.put("/{chat_id}/mode")
async def update_copilot_mode(
    chat_id: str,
    body: ModeUpdateRequest,
    db: AsyncSession = Depends(get_db)
):
    """切换会话的协同接管模式 (auto / draft / manual)"""
    stmt = select(Conversation).where(Conversation.chat_id == chat_id)
    res = await db.execute(stmt)
    conv = res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")

    conv.copilot_mode = body.copilot_mode.value
    conv.manual_takeover_at = datetime.utcnow() if body.copilot_mode == CopilotMode.MANUAL else None
    await db.commit()

    await event_bus.publish("copilot_mode_changed", {
        "chat_id": chat_id,
        "copilot_mode": body.copilot_mode.value
    })

    return {"status": "success", "chat_id": chat_id, "copilot_mode": conv.copilot_mode}


@router.get("/{chat_id}/messages", response_model=List[MessageOut])
async def get_chat_messages(
    chat_id: str,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db)
):
    """获取指定会话的完整历史聊天与决策记录"""
    stmt = select(Message).where(Message.chat_id == chat_id).order_by(Message.timestamp.asc()).limit(limit)
    res = await db.execute(stmt)
    messages = res.scalars().all()

    # 标记未读为 0
    conv_stmt = select(Conversation).where(Conversation.chat_id == chat_id)
    conv_res = await db.execute(conv_stmt)
    conv = conv_res.scalar_one_or_none()
    if conv and conv.unread_count > 0:
        conv.unread_count = 0
        await db.commit()

    return messages


@router.get("/{chat_id}/export")
async def export_conversation(chat_id: str, db: AsyncSession = Depends(get_db)):
    """导出会话完整对话历史流与决策审计日志"""
    stmt = select(Conversation).where(Conversation.chat_id == chat_id)
    res = await db.execute(stmt)
    conv = res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")

    msg_stmt = select(Message).where(Message.chat_id == chat_id).order_by(Message.timestamp.asc())
    msg_res = await db.execute(msg_stmt)
    messages = msg_res.scalars().all()

    lines = [
        "========================================",
        f"闲鱼客服会话审计导出记录: {conv.chat_id}",
        f"买家昵称: {conv.buyer_name} (UID: {conv.buyer_id})",
        f"关联商品ID: {conv.item_id or '未绑定'}",
        f"累计议价轮次: {conv.bargain_count} | 当前模式: {conv.copilot_mode} | 买家情绪: {conv.buyer_sentiment}",
        f"导出时间: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} (UTC)",
        "========================================\n"
    ]

    for m in messages:
        t_str = m.timestamp.strftime("%H:%M:%S")
        if m.role == "user":
            lines.append(f"[{t_str}] 👤 买家: {m.content}")
        elif m.role == "assistant":
            intent_label = f" (意图: {m.intent})" if m.intent else ""
            lines.append(f"[{t_str}] 🤖 AI助手{intent_label}: {m.content}")
            if m.ai_thinking:
                lines.append(f"       💡 决策思考: {m.ai_thinking.strip()}")
        elif m.role == "seller_manual":
            lines.append(f"[{t_str}] 👨‍💼 卖家插话: {m.content}")
        else:
            lines.append(f"[{t_str}] 🔔 系统: {m.content}")

    lines.append("\n========================================")
    full_text = "\n".join(lines)
    return {
        "chat_id": conv.chat_id,
        "buyer_name": conv.buyer_name,
        "message_count": len(messages),
        "transcript": full_text
    }
