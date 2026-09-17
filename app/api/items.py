from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel

from app.core.database import get_db
from app.models.entities import Item
from app.protocol.client import XianyuAsyncClient
from app.config import settings

router = APIRouter(prefix="/api/items", tags=["商品库与价格策略配置"])


class ItemOut(BaseModel):
    item_id: str
    title: str
    desc: str
    price: float
    min_price: float
    step_discount: float
    max_bargain_rounds: int
    allow_gift: bool
    gift_description: str
    tech_specs: str
    stock: int
    last_updated: datetime

    class Config:
        from_attributes = True


class ItemUpdateRequest(BaseModel):
    min_price: Optional[float] = None
    step_discount: Optional[float] = None
    max_bargain_rounds: Optional[int] = None
    allow_gift: Optional[bool] = None
    gift_description: Optional[str] = None
    tech_specs: Optional[str] = None


@router.get("", response_model=List[ItemOut])
async def list_items(
    search: Optional[str] = Query(None, description="搜索标题或ID"),
    db: AsyncSession = Depends(get_db)
):
    """获取所有已同步的商品列表与守价规则"""
    query = select(Item).order_by(desc(Item.last_updated))
    if search:
        query = query.where(Item.title.contains(search) | Item.item_id.contains(search))
    res = await db.execute(query)
    return res.scalars().all()


@router.get("/{item_id}", response_model=ItemOut)
async def get_item(item_id: str, db: AsyncSession = Depends(get_db)):
    """获取单个商品策略详情"""
    stmt = select(Item).where(Item.item_id == item_id)
    res = await db.execute(stmt)
    item = res.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="商品不存在")
    return item


@router.put("/{item_id}", response_model=ItemOut)
async def update_item_guardrail(
    item_id: str,
    body: ItemUpdateRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    修改确定性价格护栏参数 (硬底价、阶梯降价上限、赠品挽留策略、技术参数知识库)
    """
    stmt = select(Item).where(Item.item_id == item_id)
    res = await db.execute(stmt)
    item = res.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="商品不存在")

    if body.min_price is not None:
        if body.min_price > item.price:
            raise HTTPException(status_code=400, detail="底价不能高于挂牌标价")
        item.min_price = body.min_price

    if body.step_discount is not None:
        item.step_discount = body.step_discount

    if body.max_bargain_rounds is not None:
        item.max_bargain_rounds = body.max_bargain_rounds

    if body.allow_gift is not None:
        item.allow_gift = body.allow_gift

    if body.gift_description is not None:
        item.gift_description = body.gift_description

    if body.tech_specs is not None:
        item.tech_specs = body.tech_specs

    item.last_updated = datetime.utcnow()
    await db.commit()
    await db.refresh(item)
    return item


@router.post("/sync/{item_id}", response_model=ItemOut)
async def sync_item_from_xianyu(
    item_id: str,
    db: AsyncSession = Depends(get_db)
):
    """从闲鱼官方 API 同步最新商品标题、价格、描述与 SKU"""
    client = XianyuAsyncClient(settings.COOKIES_STR)
    try:
        remote_data = await client.get_item_info(item_id)
        if not remote_data:
            raise HTTPException(status_code=400, detail="从闲鱼拉取商品详情失败，请检查商品ID或Cookie")

        stmt = select(Item).where(Item.item_id == item_id)
        res = await db.execute(stmt)
        item = res.scalar_one_or_none()

        sold_price = float(remote_data.get('soldPrice', 0))
        title = remote_data.get('title', '闲鱼商品')
        desc = remote_data.get('desc', '')
        stock = int(remote_data.get('quantity', 1))

        if not item:
            item = Item(
                item_id=item_id,
                title=title,
                desc=desc,
                price=sold_price,
                min_price=round(sold_price * 0.9, 2),  # 默认 9 折保护
                step_discount=round(sold_price * 0.05, 2), # 默认每轮降 5%
                max_bargain_rounds=3,
                stock=stock,
                last_updated=datetime.utcnow()
            )
            db.add(item)
        else:
            item.title = title
            item.desc = desc
            item.price = sold_price
            item.stock = stock
            item.last_updated = datetime.utcnow()

        await db.commit()
        await db.refresh(item)
        return item
    finally:
        await client.close()
