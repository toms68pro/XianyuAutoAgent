from typing import List, Optional, Dict, Any
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from loguru import logger

from app.core.database import get_db
from app.models.entities import Account
from app.protocol.connection import connection_hub
from app.protocol.client import XianyuAsyncClient
from app.protocol.utils import trans_cookies
from app.core.event_bus import event_bus

router = APIRouter(prefix="/api/accounts", tags=["多账号矩阵管理"])


class AccountOut(BaseModel):
    id: int
    user_id: str
    nickname: str
    is_active: bool
    connection_status: str
    proxy_url: Optional[str] = None
    risk_status: str = "normal"
    verify_url: Optional[str] = None
    last_active_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AccountCreateRequest(BaseModel):
    nickname: str = "店铺账号"
    cookie_str: str
    proxy_url: Optional[str] = None


class AccountUpdateRequest(BaseModel):
    nickname: Optional[str] = None
    cookie_str: Optional[str] = None
    proxy_url: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("", response_model=List[AccountOut])
async def list_accounts(db: AsyncSession = Depends(get_db)):
    """获取所有绑定的卖家矩阵账号"""
    stmt = select(Account).order_by(Account.id.asc())
    res = await db.execute(stmt)
    accounts = res.scalars().all()

    # 同步内存中最新的运行状态
    for acc in accounts:
        inst = connection_hub.instances.get(acc.user_id)
        if inst and inst.is_running and inst.ws and not inst.ws.closed:
            acc.connection_status = "online"
        elif inst and inst.is_running:
            acc.connection_status = "reconnecting"
        else:
            acc.connection_status = "offline"

    return accounts


@router.post("", response_model=AccountOut)
async def create_or_update_account(
    body: AccountCreateRequest,
    db: AsyncSession = Depends(get_db)
):
    """添加或更新闲鱼卖家账号 Cookie 与独立代理网络"""
    cookies_dict = trans_cookies(body.cookie_str)
    unb_uid = cookies_dict.get("unb")
    if not unb_uid:
        raise HTTPException(status_code=400, detail="Cookie 格式不合法或未包含 unb 卖家标识")

    stmt = select(Account).where(Account.user_id == unb_uid)
    res = await db.execute(stmt)
    acc = res.scalar_one_or_none()

    clean_proxy = body.proxy_url.strip() if body.proxy_url else None

    if not acc:
        acc = Account(
            user_id=unb_uid,
            nickname=body.nickname,
            cookie_str=body.cookie_str,
            proxy_url=clean_proxy,
            risk_status="normal",
            is_active=True,
            connection_status="offline",
            last_active_at=datetime.utcnow()
        )
        db.add(acc)
    else:
        acc.nickname = body.nickname
        acc.cookie_str = body.cookie_str
        acc.proxy_url = clean_proxy
        acc.is_active = True
        acc.last_active_at = datetime.utcnow()

    await db.commit()
    await db.refresh(acc)

    # 立即启动异步长连接 (注入指定代理)
    connection_hub.start_account(acc.user_id, acc.cookie_str, acc.proxy_url)
    return acc


@router.put("/{user_id}", response_model=AccountOut)
async def update_account(
    user_id: str,
    body: AccountUpdateRequest,
    db: AsyncSession = Depends(get_db)
):
    """更新账号配置 (包括代理、别名与Cookie)"""
    stmt = select(Account).where(Account.user_id == user_id)
    res = await db.execute(stmt)
    acc = res.scalar_one_or_none()
    if not acc:
        raise HTTPException(status_code=404, detail="账号不存在")

    if body.nickname is not None:
        acc.nickname = body.nickname.strip()
    if body.cookie_str is not None and body.cookie_str.strip():
        acc.cookie_str = body.cookie_str.strip()
    if body.proxy_url is not None:
        acc.proxy_url = body.proxy_url.strip() if body.proxy_url.strip() else None
    if body.is_active is not None:
        acc.is_active = body.is_active

    await db.commit()
    await db.refresh(acc)

    # 重启长连接实例以应用新代理与配置
    if acc.is_active:
        connection_hub.start_account(acc.user_id, acc.cookie_str, acc.proxy_url)
    else:
        connection_hub.stop_account(acc.user_id)

    return acc


@router.post("/{user_id}/toggle")
async def toggle_account(user_id: str, db: AsyncSession = Depends(get_db)):
    """启动或暂停账号自动值守"""
    stmt = select(Account).where(Account.user_id == user_id)
    res = await db.execute(stmt)
    acc = res.scalar_one_or_none()
    if not acc:
        raise HTTPException(status_code=404, detail="账号不存在")

    acc.is_active = not acc.is_active
    await db.commit()

    if acc.is_active:
        connection_hub.start_account(acc.user_id, acc.cookie_str, acc.proxy_url)
    else:
        connection_hub.stop_account(acc.user_id)

    return {"status": "success", "user_id": user_id, "is_active": acc.is_active}


@router.post("/{user_id}/resolve_risk")
async def resolve_account_risk(user_id: str, db: AsyncSession = Depends(get_db)):
    """人工在浏览器完成滑块后，通知系统复测登录态并自愈恢复长连接"""
    stmt = select(Account).where(Account.user_id == user_id)
    res = await db.execute(stmt)
    acc = res.scalar_one_or_none()
    if not acc:
        raise HTTPException(status_code=404, detail="账号不存在")

    # 创建独立临时客户端检测登录态
    test_client = XianyuAsyncClient(acc.cookie_str, proxy_url=acc.proxy_url)
    try:
        is_ok = await test_client.has_login()
        if is_ok:
            acc.risk_status = "normal"
            acc.verify_url = None
            await db.commit()

            # 重载长连接实例
            connection_hub.start_account(acc.user_id, acc.cookie_str, acc.proxy_url)

            await event_bus.publish("account_status", {
                "seller_id": acc.user_id,
                "status": "online",
                "message": "滑块风控验证已通过，服务已恢复！"
            })
            return {"status": "resolved", "risk_status": "normal", "message": "验证通过，服务已自愈恢复"}
        else:
            return {
                "status": "pending",
                "risk_status": acc.risk_status,
                "message": "闲鱼验证尚未通过，请确认已在浏览器滑动拼图成功后再次点击复查"
            }
    finally:
        await test_client.close()


@router.post("/{user_id}/test_proxy")
async def test_account_proxy(user_id: str, db: AsyncSession = Depends(get_db)):
    """测试账号绑定的网络与代理连通性"""
    stmt = select(Account).where(Account.user_id == user_id)
    res = await db.execute(stmt)
    acc = res.scalar_one_or_none()
    if not acc:
        raise HTTPException(status_code=404, detail="账号不存在")

    test_client = XianyuAsyncClient(acc.cookie_str, proxy_url=acc.proxy_url)
    try:
        result = await test_client.test_proxy()
        return result
    finally:
        await test_client.close()


@router.delete("/{user_id}")
async def delete_account(user_id: str, db: AsyncSession = Depends(get_db)):
    """删除注销店铺账号"""
    stmt = select(Account).where(Account.user_id == user_id)
    res = await db.execute(stmt)
    acc = res.scalar_one_or_none()
    if not acc:
        raise HTTPException(status_code=404, detail="账号不存在")

    connection_hub.stop_account(user_id)
    await db.delete(acc)
    await db.commit()
    return {"status": "deleted", "user_id": user_id}
