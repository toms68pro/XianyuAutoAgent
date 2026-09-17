from typing import Optional, List
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel
from loguru import logger

from app.core.database import get_db
from app.core.event_bus import event_bus
from app.models.entities import Conversation, Message, Item, Account
from app.protocol.connection import connection_hub
from app.protocol.client import XianyuAsyncClient

router = APIRouter(prefix="/api/orders", tags=["订单与改价交易闭环"])


class ModifyPriceRequest(BaseModel):
    chat_id: str
    target_price: float
    order_id: Optional[str] = None
    update_item_listing: bool = True  # 是否联动修改商品实际挂牌标价
    notify_buyer: bool = True
    remark: Optional[str] = "协商改价完成"


@router.post("/modify_price")
async def one_click_modify_price(
    body: ModifyPriceRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    一键按协商价改价闭环
    1. 若提供了未付款 order_id，调用闲鱼 MTOP 真实修改订单实付金额
    2. 若提供了商品 item_id，联动调用 MTOP 降低商品挂牌标价并更新商品库
    3. 自动向买家下发改价成功消息，引导完成支付
    """
    stmt = select(Conversation).where(Conversation.chat_id == body.chat_id)
    res = await db.execute(stmt)
    conv = res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="关联会话不存在")

    mtop_order_success = False
    mtop_item_success = False

    # 获取该卖家账号凭据进行真实 MTOP 操作
    acc_stmt = select(Account).where(Account.user_id == conv.seller_id)
    acc_res = await db.execute(acc_stmt)
    acc = acc_res.scalar_one_or_none()

    if acc and acc.cookie_str:
        client = XianyuAsyncClient(acc.cookie_str)
        try:
            # A. 若有订单号，修改订单金额
            if body.order_id:
                mtop_order_success = await client.modify_order_price(body.order_id, body.target_price)

            # B. 若开启了商品标价修改，直接调用 MTOP 修改商品售价
            if body.update_item_listing and conv.item_id:
                mtop_item_success = await client.modify_item_price(conv.item_id, body.target_price)
                # 同步更新本地数据库商品表
                item_stmt = select(Item).where(Item.item_id == conv.item_id)
                item_res = await db.execute(item_stmt)
                item = item_res.scalar_one_or_none()
                if item:
                    item.price = body.target_price
                    item.last_updated = datetime.utcnow()
        except Exception as e:
            logger.error(f"调用 MTOP 改价异常: {e}")
        finally:
            await client.close()

    notice_text = f"老板好，价格已帮您改好为 ¥{body.target_price:.2f} 啦！拍下付款后今天立即安排顺丰发出~"

    if body.notify_buyer:
        # 下发闲鱼消息告知买家
        await connection_hub.send_chat_message(
            seller_id=conv.seller_id,
            chat_id=conv.chat_id,
            to_user_id=conv.buyer_id,
            text=notice_text
        )

        msg_record = Message(
            chat_id=conv.chat_id,
            seller_id=conv.seller_id,
            item_id=conv.item_id,
            sender_id=conv.seller_id,
            role="assistant",
            content=notice_text,
            intent="price_modified",
            ai_thinking=f"【一键改价闭环触发】成交目标价 ¥{body.target_price} (MTOP标价同步: {mtop_item_success}, 订单改价: {mtop_order_success})",
            draft_status="direct_sent",
            timestamp=datetime.utcnow()
        )
        db.add(msg_record)
        conv.last_message_at = datetime.utcnow()
        await db.commit()

    # 广播事件至 Web 工作台
    await event_bus.publish("price_modified", {
        "chat_id": conv.chat_id,
        "target_price": body.target_price,
        "mtop_item_success": mtop_item_success,
        "mtop_order_success": mtop_order_success,
        "timestamp": datetime.utcnow().isoformat()
    })

    return {
        "status": "success",
        "chat_id": conv.chat_id,
        "target_price": body.target_price,
        "mtop_item_success": mtop_item_success,
        "mtop_order_success": mtop_order_success,
        "message": "改价处理完成，通知已下发"
    }

