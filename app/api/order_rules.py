from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel

from app.core.database import get_db
from app.models.entities import OrderRule

router = APIRouter(prefix="/api/order_rules", tags=["自动化发货与履约规则"])


class OrderRuleOut(BaseModel):
    id: int
    item_id: Optional[str] = None
    trigger_event: str
    auto_reply_text: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class OrderRuleCreate(BaseModel):
    item_id: Optional[str] = None
    trigger_event: str = "等待卖家发货"  # 或 "等待买家付款"
    auto_reply_text: str
    is_active: bool = True


@router.get("", response_model=List[OrderRuleOut])
async def list_order_rules(db: AsyncSession = Depends(get_db)):
    """获取所有自动化发货履约规则"""
    stmt = select(OrderRule).order_by(desc(OrderRule.id))
    res = await db.execute(stmt)
    return res.scalars().all()


@router.post("", response_model=OrderRuleOut)
async def create_order_rule(body: OrderRuleCreate, db: AsyncSession = Depends(get_db)):
    """添加或更新自动化发货规则"""
    rule = OrderRule(
        item_id=body.item_id,
        trigger_event=body.trigger_event,
        auto_reply_text=body.auto_reply_text.strip(),
        is_active=body.is_active,
        created_at=datetime.utcnow()
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.post("/{rule_id}/toggle")
async def toggle_order_rule(rule_id: int, db: AsyncSession = Depends(get_db)):
    """启用/暂停自动发货规则"""
    stmt = select(OrderRule).where(OrderRule.id == rule_id)
    res = await db.execute(stmt)
    rule = res.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")

    rule.is_active = not rule.is_active
    await db.commit()
    return {"status": "success", "id": rule_id, "is_active": rule.is_active}


@router.delete("/{rule_id}")
async def delete_order_rule(rule_id: int, db: AsyncSession = Depends(get_db)):
    """删除发货规则"""
    stmt = select(OrderRule).where(OrderRule.id == rule_id)
    res = await db.execute(stmt)
    rule = res.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")

    await db.delete(rule)
    await db.commit()
    return {"status": "deleted", "id": rule_id}
