import asyncio
from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy import select, func
from loguru import logger

from app.core.database import AsyncSessionLocal
from app.core.event_bus import event_bus
from app.models.entities import OrderRule, Message, Conversation, CardKey
from app.protocol.connection import connection_hub


class OrderFulfillmentEngine:
    """闲鱼订单全自动履约引擎 (支持拍下催付、付款后自动发货卡密/网盘链接)"""

    def __init__(self):
        event_bus.register_handler("order_event", self.on_order_event)

    async def on_order_event(self, data: Dict[str, Any]):
        """监听订单状态变更事件并触发自动化执行"""
        event_type = data.get("event_type")  # e.g. "等待卖家发货" / "等待买家付款"
        seller_id = data.get("seller_id")
        raw = data.get("raw", {})
        
        # 提取买家 ID
        buyer_uid = raw.get("1", "").split("@")[0]
        if not buyer_uid or not seller_id:
            return

        # 查询关联该买家的活跃会话
        async with AsyncSessionLocal() as session:
            conv_stmt = select(Conversation).where(
                (Conversation.seller_id == seller_id) & (Conversation.buyer_id == buyer_uid)
            ).order_by(Conversation.last_message_at.desc())
            conv_res = await session.execute(conv_stmt)
            conv = conv_res.scalars().first()

            item_id = conv.item_id if conv else None
            chat_id = conv.chat_id if conv else None

            # 匹配启用的履约规则
            rule_stmt = select(OrderRule).where(
                (OrderRule.trigger_event == event_type) &
                (OrderRule.is_active == True) &
                ((OrderRule.item_id == item_id) | (OrderRule.item_id == None))
            ).order_by(OrderRule.item_id.desc())  # 优先匹配特定商品规则
            rule_res = await session.execute(rule_stmt)
            matched_rule = rule_res.scalars().first()

            # 检查是否有可用的一卡一密资产
            card_item = None
            if event_type == "等待卖家发货":
                card_stmt = select(CardKey).where(
                    (CardKey.status == "available") &
                    ((CardKey.item_id == item_id) | (CardKey.item_id == None))
                ).order_by(CardKey.item_id.desc(), CardKey.id.asc()).limit(1)
                card_res = await session.execute(card_stmt)
                card_item = card_res.scalar_one_or_none()

            if not matched_rule and not card_item:
                logger.info(f"订单事件 [{event_type}] 无匹配发货规则且无可用卡密，跳过")
                return

            if not chat_id:
                logger.warning(f"无法自动发货：未找到买家 {buyer_uid} 的有效会话")
                return

            delivery_content = matched_rule.auto_reply_text.strip() if matched_rule else "感谢老板支持！商品已自动为您发货~"

            # 若有一卡一密资产，原子核销并注入发货文案中
            if card_item:
                delivery_content += f"\n\n🔑【您的专属卡密/资产】：\n{card_item.card_code}\n（系统已自动核销出库，请妥善保管）"
                card_item.status = "used"
                card_item.buyer_id = buyer_uid
                card_item.used_at = datetime.utcnow()

                # 检查剩余库存并在低库存时告警
                rem_stmt = select(func.count(CardKey.id)).where(
                    (CardKey.status == "available") &
                    ((CardKey.item_id == item_id) | (CardKey.item_id == None))
                )
                rem_count = (await session.execute(rem_stmt)).scalar() or 0
                if rem_count <= 2:
                    logger.warning(f"⚠️ 卡密库存告急！仅剩 {rem_count} 张可用")
                    try:
                        from app.core.notifier import notifier
                        asyncio.create_task(notifier.send_alert(
                            "⚠️ 虚拟卡密库存告急预警",
                            f"**关联商品**: {item_id or '全局通用'}\n\n"
                            f"**剩余可用卡密**: {rem_count} 张\n\n"
                            f"请尽快前往管理工作台补充卡密库存，避免影响自动发货！"
                        ))
                    except Exception as e:
                        logger.error(f"发送库存告警失败: {e}")

            logger.info(f"🚀 触发自动发货/履约规则 [{event_type}]，发送内容: {delivery_content}")

            # 1. 发送消息给买家
            await connection_hub.send_chat_message(
                seller_id=seller_id,
                chat_id=chat_id,
                to_user_id=buyer_uid,
                text=delivery_content
            )

            # 2. 写入数据库
            msg_record = Message(
                chat_id=chat_id,
                seller_id=seller_id,
                item_id=item_id,
                sender_id=seller_id,
                role="assistant",
                content=delivery_content,
                intent="fulfillment",
                ai_thinking=f"【自动履约规则触发】事件: {event_type}",
                draft_status="direct_sent",
                timestamp=datetime.utcnow()
            )
            session.add(msg_record)
            if conv:
                conv.last_message_at = datetime.utcnow()
            await session.commit()

            # 3. 广播给前端工作台
            await event_bus.publish("message_sent", {
                "chat_id": chat_id,
                "seller_id": seller_id,
                "role": "assistant",
                "content": delivery_content,
                "intent": "fulfillment",
                "thinking": f"自动履约触发: {event_type}",
                "timestamp": datetime.utcnow().isoformat()
            })


fulfillment_engine = OrderFulfillmentEngine()
