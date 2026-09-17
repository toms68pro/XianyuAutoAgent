from typing import List, Optional, Dict, Any
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel

from app.core.database import get_db
from app.models.entities import FAQ
from app.core.rag import knowledge_base

router = APIRouter(prefix="/api/faqs", tags=["RAG知识库问答管理"])


class FAQOut(BaseModel):
    id: int
    item_id: Optional[str] = None
    question: str
    answer: str
    keywords: str
    created_at: datetime

    class Config:
        from_attributes = True


class FAQCreate(BaseModel):
    item_id: Optional[str] = None
    question: str
    answer: str
    keywords: Optional[str] = ""


class FAQSimulateRequest(BaseModel):
    query: str
    item_id: Optional[str] = None
    top_k: int = 3
    min_score: float = 0.2


@router.get("", response_model=List[FAQOut])
async def list_faqs(
    item_id: Optional[str] = Query(None, description="筛选特定商品FAQ"),
    db: AsyncSession = Depends(get_db)
):
    """获取知识库问答列表"""
    query = select(FAQ).order_by(desc(FAQ.id))
    if item_id:
        query = query.where(FAQ.item_id == item_id)
    res = await db.execute(query)
    return res.scalars().all()


@router.post("", response_model=FAQOut)
async def create_faq(body: FAQCreate, db: AsyncSession = Depends(get_db)):
    """添加新的标准问答对至知识库"""
    faq = FAQ(
        item_id=body.item_id,
        question=body.question.strip(),
        answer=body.answer.strip(),
        keywords=body.keywords.strip() if body.keywords else "",
        created_at=datetime.utcnow()
    )
    db.add(faq)
    await db.commit()
    await db.refresh(faq)
    return faq


@router.put("/{faq_id}", response_model=FAQOut)
async def update_faq(
    faq_id: int,
    body: FAQCreate,
    db: AsyncSession = Depends(get_db)
):
    """修改更新知识库条目"""
    stmt = select(FAQ).where(FAQ.id == faq_id)
    res = await db.execute(stmt)
    faq = res.scalar_one_or_none()
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ条目不存在")

    faq.question = body.question.strip()
    faq.answer = body.answer.strip()
    faq.keywords = body.keywords.strip() if body.keywords else ""
    faq.item_id = body.item_id

    await db.commit()
    await db.refresh(faq)
    return faq


@router.delete("/{faq_id}")
async def delete_faq(faq_id: int, db: AsyncSession = Depends(get_db)):
    """删除指定问答条目"""
    stmt = select(FAQ).where(FAQ.id == faq_id)
    res = await db.execute(stmt)
    faq = res.scalar_one_or_none()
    if not faq:
        raise HTTPException(status_code=404, detail="条目不存在")
    await db.delete(faq)
    await db.commit()
    return {"status": "deleted", "id": faq_id}


@router.post("/simulate")
async def simulate_rag_search(body: FAQSimulateRequest):
    """测试与模拟 RAG 混合检索命中 (供工作台调试与置信度审计)"""
    tokens = knowledge_base._tokenize(body.query)
    results = await knowledge_base.search_relevant_faq(
        query=body.query,
        item_id=body.item_id,
        top_k=body.top_k,
        min_score=body.min_score
    )
    formatted_context = await knowledge_base.format_rag_context(body.query, body.item_id)

    return {
        "query": body.query,
        "tokens": tokens,
        "results": results,
        "formatted_prompt_context": formatted_context,
        "match_count": len(results)
    }
