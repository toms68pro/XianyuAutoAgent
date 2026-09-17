from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel

from app.core.database import get_db
from app.models.entities import CannedReply

router = APIRouter(prefix="/api/canned_replies", tags=["常用快捷话术库"])


class CannedReplyOut(BaseModel):
    id: int
    title: str
    content: str
    category: str
    created_at: datetime

    class Config:
        from_attributes = True


class CannedReplyCreate(BaseModel):
    title: str
    content: str
    category: Optional[str] = "通用"


@router.get("", response_model=List[CannedReplyOut])
async def list_canned_replies(db: AsyncSession = Depends(get_db)):
    """获取所有快捷话术列表"""
    stmt = select(CannedReply).order_by(CannedReply.id.asc())
    res = await db.execute(stmt)
    return res.scalars().all()


@router.post("", response_model=CannedReplyOut)
async def create_canned_reply(body: CannedReplyCreate, db: AsyncSession = Depends(get_db)):
    """新增常用话术条目"""
    if not body.title.strip() or not body.content.strip():
        raise HTTPException(status_code=400, detail="标题与话术内容不能为空")

    reply = CannedReply(
        title=body.title.strip(),
        content=body.content.strip(),
        category=body.category.strip() if body.category else "通用",
        created_at=datetime.utcnow()
    )
    db.add(reply)
    await db.commit()
    await db.refresh(reply)
    return reply


@router.delete("/{reply_id}")
async def delete_canned_reply(reply_id: int, db: AsyncSession = Depends(get_db)):
    """删除指定快捷话术"""
    stmt = select(CannedReply).where(CannedReply.id == reply_id)
    res = await db.execute(stmt)
    reply = res.scalar_one_or_none()
    if not reply:
        raise HTTPException(status_code=404, detail="话术条目不存在")

    await db.delete(reply)
    await db.commit()
    return {"status": "deleted", "id": reply_id}
