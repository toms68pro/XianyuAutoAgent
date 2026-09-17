from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.core.database import get_db
from app.core.event_bus import event_bus
from app.models.entities import Conversation, Message
from app.protocol.connection import connection_hub

router = APIRouter(prefix="/api/messages", tags=["消息交互与人机协同"])


class SendMessageRequest(BaseModel):
    chat_id: str
    content: str
    # 发送时是否顺便改变协同模式: 'keep' | 'manual' | 'auto'
    mode_action: str = "manual"


class DraftActionRequest(BaseModel):
    draft_id: int
    edited_content: Optional[str] = None


@router.post("/send")
async def send_manual_message(
    body: SendMessageRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    卖家在工作台手动发送消息（卖家插话）
    自动下发至闲鱼 WSS 通道，并可一键将该会话置为人工接管模式
    """
    stmt = select(Conversation).where(Conversation.chat_id == body.chat_id)
    res = await db.execute(stmt)
    conv = res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")

    now = datetime.utcnow()
    # 调整接管模式
    if body.mode_action == "manual":
        conv.copilot_mode = "manual"
        conv.manual_takeover_at = now
    elif body.mode_action == "auto":
        conv.copilot_mode = "auto"
        conv.manual_takeover_at = None

    conv.last_message_at = now
    conv.unread_count = 0

    # 记录卖家消息
    msg_record = Message(
        chat_id=body.chat_id,
        seller_id=conv.seller_id,
        item_id=conv.item_id,
        sender_id=conv.seller_id,
        role="seller_manual",
        content=body.content,
        timestamp=now
    )
    db.add(msg_record)
    await db.commit()

    # 通过连接中枢下发至闲鱼
    await connection_hub.send_chat_message(
        seller_id=conv.seller_id,
        chat_id=conv.chat_id,
        to_user_id=conv.buyer_id,
        text=body.content
    )

    # 广播事件至 Web 端
    await event_bus.publish("message_sent", {
        "chat_id": body.chat_id,
        "seller_id": conv.seller_id,
        "role": "seller_manual",
        "content": body.content,
        "timestamp": now.isoformat()
    })

    return {"status": "sent", "chat_id": body.chat_id, "copilot_mode": conv.copilot_mode}


@router.post("/approve_draft")
async def approve_draft(
    body: DraftActionRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    卖家审批放行 AI 草稿（可附带微调内容）
    审批通过后立即由闲鱼网关发出
    """
    stmt = select(Message).where(Message.id == body.draft_id)
    res = await db.execute(stmt)
    draft = res.scalar_one_or_none()
    if not draft or draft.draft_status != "pending":
        raise HTTPException(status_code=404, detail="待审批草稿不存在或已被处理")

    conv_stmt = select(Conversation).where(Conversation.chat_id == draft.chat_id)
    conv_res = await db.execute(conv_stmt)
    conv = conv_res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="关联会话不存在")

    final_text = body.edited_content.strip() if body.edited_content else draft.content
    draft.content = final_text
    draft.draft_status = "edited" if body.edited_content else "approved"
    draft.timestamp = datetime.utcnow()

    conv.last_message_at = draft.timestamp
    conv.unread_count = 0
    await db.commit()

    # 发送
    await connection_hub.send_chat_message(
        seller_id=conv.seller_id,
        chat_id=conv.chat_id,
        to_user_id=conv.buyer_id,
        text=final_text
    )

    await event_bus.publish("message_sent", {
        "chat_id": conv.chat_id,
        "seller_id": conv.seller_id,
        "role": "assistant",
        "content": final_text,
        "intent": draft.intent,
        "thinking": draft.ai_thinking,
        "timestamp": draft.timestamp.isoformat()
    })

    return {"status": "approved_and_sent", "content": final_text}


@router.post("/reject_draft")
async def reject_draft(
    body: DraftActionRequest,
    db: AsyncSession = Depends(get_db)
):
    """卖家驳回/丢弃 AI 建议草稿"""
    stmt = select(Message).where(Message.id == body.draft_id)
    res = await db.execute(stmt)
    draft = res.scalar_one_or_none()
    if not draft:
        raise HTTPException(status_code=404, detail="草稿不存在")

    draft.draft_status = "rejected"
    await db.commit()

    await event_bus.publish("draft_rejected", {
        "draft_id": draft.id,
        "chat_id": draft.chat_id
    })

    return {"status": "rejected", "draft_id": draft.id}
