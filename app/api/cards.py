from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from pydantic import BaseModel

from app.core.database import get_db
from app.models.entities import CardKey

router = APIRouter(prefix="/api/cards", tags=["虚拟资产与卡密发货池"])


class CardKeyOut(BaseModel):
    id: int
    item_id: Optional[str] = None
    card_code: str
    status: str
    buyer_id: Optional[str] = None
    order_id: Optional[str] = None
    created_at: datetime
    used_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CardBatchImportRequest(BaseModel):
    item_id: Optional[str] = None
    codes: str  # 换行分割的多张卡密文本


@router.get("", response_model=List[CardKeyOut])
async def list_cards(
    status: Optional[str] = Query(None, description="状态筛选: available / used"),
    item_id: Optional[str] = Query(None, description="按关联商品ID筛选"),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db)
):
    """查询卡密资产列表"""
    query = select(CardKey).order_by(desc(CardKey.id)).limit(limit)
    if status:
        query = query.where(CardKey.status == status)
    if item_id:
        query = query.where(CardKey.item_id == item_id)

    res = await db.execute(query)
    return res.scalars().all()


@router.get("/stats")
async def get_card_stats(db: AsyncSession = Depends(get_db)):
    """获取卡密库存与发放统计"""
    total = (await db.execute(select(func.count(CardKey.id)))).scalar() or 0
    available = (await db.execute(select(func.count(CardKey.id)).where(CardKey.status == "available"))).scalar() or 0
    used = (await db.execute(select(func.count(CardKey.id)).where(CardKey.status == "used"))).scalar() or 0

    return {
        "total": total,
        "available": available,
        "used": used
    }


@router.post("/batch")
async def batch_import_cards(
    body: CardBatchImportRequest,
    db: AsyncSession = Depends(get_db)
):
    """批量导入卡密 (按行分割，自动排重清洗)"""
    lines = [line.strip() for line in body.codes.split("\n") if line.strip()]
    if not lines:
        raise HTTPException(status_code=400, detail="未检测到有效的卡密文本")

    added_count = 0
    now = datetime.utcnow()
    for code in lines:
        card = CardKey(
            item_id=body.item_id if body.item_id else None,
            card_code=code,
            status="available",
            created_at=now
        )
        db.add(card)
        added_count += 1

    await db.commit()
    return {"status": "success", "imported_count": added_count}


@router.delete("/{card_id}")
async def delete_card(card_id: int, db: AsyncSession = Depends(get_db)):
    """删除指定卡密"""
    stmt = select(CardKey).where(CardKey.id == card_id)
    res = await db.execute(stmt)
    card = res.scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="卡密不存在")

    await db.delete(card)
    await db.commit()
    return {"status": "deleted", "id": card_id}
