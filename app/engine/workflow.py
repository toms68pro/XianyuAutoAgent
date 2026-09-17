import time
import random
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, Callable, Coroutine, List
from sqlalchemy import select
from loguru import logger

from app.config import settings
from app.core.database import AsyncSessionLocal
from app.core.event_bus import event_bus
from app.models.entities import Conversation, Message, Item, Account
from app.models.enums import CopilotMode, BuyerSentiment, DraftStatus, MessageRole
from app.engine.router import intent_router
from app.engine.guardrail import price_guardrail
from app.engine.agents.price_agent import PriceAsyncAgent
from app.engine.agents.tech_agent import TechAsyncAgent
from app.engine.agents.default_agent import DefaultAsyncAgent
from app.engine.agents.vision_agent import vision_agent
from app.core.cache import semantic_cache


class ConversationWorkflow:
    """闲鱼会话全生命周期协同调度引擎 (StateGraph 业务状态机)"""

    def __init__(self):
        self.price_agent = PriceAsyncAgent()
        self.tech_agent = TechAsyncAgent()
        self.default_agent = DefaultAsyncAgent()
        self.vision_agent = vision_agent
        # 发送回调句柄: 由 ConnectionManager 注入
        self._sender_func: Optional[Callable[[str, str, str, str], Coroutine[Any, Any, None]]] = None
        # 买家短消息防抖聚合缓冲池
        self._debounce_tasks: Dict[str, asyncio.Task] = {}
        self._pending_buffers: Dict[str, List[str]] = {}
        self._pending_raw_data: Dict[str, Optional[Dict[str, Any]]] = {}

    def set_sender(self, func: Callable[[str, str, str, str], Coroutine[Any, Any, None]]):
        """注入 WebSocket 发送句柄 (seller_id, chat_id, buyer_id, text)"""
        self._sender_func = func

    def format_item_description(self, item: Item) -> str:
        """构建标准化商品参数文本"""
        sku_list = item.get_sku_list()
        sku_str = "、".join([f"{s.get('spec')}(¥{s.get('price')})" for s in sku_list if s.get('spec')])
        return (
            f"商品名称: {item.title}\n"
            f"挂牌标价: ¥{item.price}\n"
            f"规格库存: {sku_str or '默认规格'}\n"
            f"商品描述: {item.desc}\n"
            f"附加说明: {item.tech_specs or '无特殊瑕疵，正常成色'}"
        )

    async def process_incoming_message(
        self,
        seller_id: str,
        chat_id: str,
        buyer_id: str,
        buyer_name: str,
        item_id: str,
        user_msg: str,
        raw_msg_data: Optional[Dict[str, Any]] = None
    ):
        """处理买家进线消息：即时落库上屏，并启动防抖聚合定时器"""
        async with AsyncSessionLocal() as session:
            # 1. 查询或建立会话状态
            stmt = select(Conversation).where(Conversation.chat_id == chat_id)
            res = await session.execute(stmt)
            conv = res.scalar_one_or_none()

            now = datetime.utcnow()
            if not conv:
                conv = Conversation(
                    chat_id=chat_id,
                    seller_id=seller_id,
                    buyer_id=buyer_id,
                    buyer_name=buyer_name or "闲鱼买家",
                    item_id=item_id,
                    copilot_mode=settings.DEFAULT_COPILOT_MODE,
                    unread_count=1,
                    last_message_at=now
                )
                session.add(conv)
            else:
                conv.last_message_at = now
                conv.unread_count += 1
                if item_id:
                    conv.item_id = item_id

            # 检查人工接管是否超时自动退回
            if conv.copilot_mode == CopilotMode.MANUAL.value and conv.manual_takeover_at:
                elapsed = (now - conv.manual_takeover_at).total_seconds()
                if elapsed > settings.MANUAL_MODE_TIMEOUT:
                    logger.info(f"会话 {chat_id} 人工接管超时 ({elapsed:.0f}s)，自动恢复 AI 托管")
                    conv.copilot_mode = CopilotMode.AUTO.value
                    conv.manual_takeover_at = None

            # 2. 提取多模态图片链接与评估买家情绪画像
            img_url = None
            if raw_msg_data:
                img_url = raw_msg_data.get("1", {}).get("10", {}).get("imageUrl") or raw_msg_data.get("1", {}).get("10", {}).get("picUrl")
            effective_msg = img_url if (img_url and user_msg.strip() == "[图片]") else user_msg

            sentiment = intent_router.detect_sentiment(user_msg)
            conv.buyer_sentiment = sentiment

            # 写入买家消息至审计流水 (0ms 即刻落库)
            buyer_msg_record = Message(
                chat_id=chat_id,
                seller_id=seller_id,
                item_id=item_id,
                sender_id=buyer_id,
                role=MessageRole.USER.value,
                content=effective_msg,
                timestamp=now
            )
            session.add(buyer_msg_record)
            await session.commit()
            await session.refresh(conv)

            # 3. 广播买家消息到达事件 (0ms 即刻更新前端 UI 与雷达指标)
            await event_bus.publish("message_received", {
                "chat_id": chat_id,
                "seller_id": seller_id,
                "buyer_id": buyer_id,
                "buyer_name": buyer_name,
                "item_id": item_id,
                "content": effective_msg,
                "copilot_mode": conv.copilot_mode,
                "buyer_sentiment": sentiment,
                "timestamp": now.isoformat()
            })

            # 4. 若处于完全人工接管模式，直接静默退出
            if conv.copilot_mode == CopilotMode.MANUAL.value:
                logger.info(f"会话 {chat_id} 处于人工接管中，跳过 AI 自动回复")
                return

        # 5. 消息防抖聚合机制 (Debounce Buffer)
        if chat_id not in self._pending_buffers:
            self._pending_buffers[chat_id] = []
        self._pending_buffers[chat_id].append(user_msg)

        if raw_msg_data:
            self._pending_raw_data[chat_id] = raw_msg_data

        # 取消已有的未到期防抖任务，重新计时
        if chat_id in self._debounce_tasks and not self._debounce_tasks[chat_id].done():
            self._debounce_tasks[chat_id].cancel()

        if settings.MESSAGE_DEBOUNCE_SECONDS > 0:
            self._debounce_tasks[chat_id] = asyncio.create_task(
                self._debounce_dispatch(seller_id, chat_id, buyer_id, buyer_name, item_id)
            )
        else:
            await self._run_ai_pipeline(seller_id, chat_id, buyer_id, buyer_name, item_id, user_msg, raw_msg_data)

    async def _debounce_dispatch(
        self,
        seller_id: str,
        chat_id: str,
        buyer_id: str,
        buyer_name: str,
        item_id: str
    ):
        """防抖计时器：等待买家连续输入停顿后合并触发 AI 推理"""
        try:
            await asyncio.sleep(settings.MESSAGE_DEBOUNCE_SECONDS)
            buffered = self._pending_buffers.pop(chat_id, [])
            raw_data = self._pending_raw_data.pop(chat_id, None)
            if not buffered:
                return

            combined_msg = "，".join(buffered) if len(buffered) > 1 else buffered[0]
            if len(buffered) > 1:
                logger.info(f"⚡ [防抖聚合触发] 会话 {chat_id} 合并 {len(buffered)} 条连续消息: '{combined_msg}'")

            await self._run_ai_pipeline(seller_id, chat_id, buyer_id, buyer_name, item_id, combined_msg, raw_data)
        except asyncio.CancelledError:
            pass
        finally:
            self._debounce_tasks.pop(chat_id, None)

    async def _run_ai_pipeline(
        self,
        seller_id: str,
        chat_id: str,
        buyer_id: str,
        buyer_name: str,
        item_id: str,
        user_msg: str,
        raw_msg_data: Optional[Dict[str, Any]] = None
    ):
        """执行 AI 决策与回复生成核心流水线"""
        async with AsyncSessionLocal() as session:
            stmt = select(Conversation).where(Conversation.chat_id == chat_id)
            res = await session.execute(stmt)
            conv = res.scalar_one_or_none()
            if not conv or conv.copilot_mode == "manual":
                logger.info(f"会话 {chat_id} 状态已变更为人工接管，放弃 AI 响应")
                return


            # 5. 读取商品信息与保护底价
            item = None
            if item_id:
                item_stmt = select(Item).where(Item.item_id == item_id)
                item_res = await session.execute(item_stmt)
                item = item_res.scalar_one_or_none()

            if not item:
                # 构造临时保底商品对象
                item = Item(
                    item_id=item_id or "unknown",
                    title="咨询商品",
                    price=999.0,
                    min_price=899.0,
                    step_discount=50.0,
                    desc="卖家暂未同步完整描述"
                )

            item_desc_text = self.format_item_description(item)

            # 6. 获取最近历史对话
            hist_stmt = select(Message).where(Message.chat_id == chat_id).order_by(Message.timestamp.desc()).limit(12)
            hist_res = await session.execute(hist_stmt)
            history_rows = list(reversed(hist_res.scalars().all()))
            history = [{"role": m.role, "content": m.content} for m in history_rows]

            # 6.5 语义缓存优先检索 (超低延时 <10ms 极速响应，支持 Redis 8 分布式缓存)
            cached_res = await semantic_cache.get_async(user_msg)
            ai_output: Dict[str, Any] = {}

            # 检查买家是否发送了图片
            image_url = None
            if raw_msg_data:
                image_url = raw_msg_data.get("1", {}).get("10", {}).get("imageUrl") or raw_msg_data.get("1", {}).get("10", {}).get("picUrl")
            if not image_url and ("http" in user_msg and any(ext in user_msg.lower() for ext in [".jpg", ".png", ".jpeg", ".webp"])):
                image_url = user_msg.strip()

            if image_url:
                logger.info(f"📸 捕获买家图片消息，进入多模态视觉分析: {image_url}")
                detected_intent = "vision"
                conv.latest_intent = "vision"
                ai_output = await self.vision_agent.analyze_image_and_reply(
                    user_msg=user_msg if user_msg != image_url else "帮我看看这个成色细节如何？",
                    image_url=image_url,
                    item_desc=item_desc_text,
                    history=history
                )

            elif cached_res:
                detected_intent = cached_res.get("intent", "cache_hit")
                conv.latest_intent = detected_intent
                ai_output = {
                    "reply": cached_res["reply"],
                    "thinking": f"⚡ 语义缓存极速命中 [{cached_res.get('source', 'cache')}]，耗时 <10ms，省去大模型 API 调用",
                    "latency_ms": 8
                }
                logger.info(f"⚡ 会话 {chat_id} 语义缓存命中直接秒回")

            else:
                # 7. 意图分类与决策分支
                detected_intent = await intent_router.detect(user_msg, item.title)
                conv.latest_intent = detected_intent
                logger.info(f"买家消息: '{user_msg}' | 命中意图: {detected_intent}")

                if detected_intent == "no_reply":
                    logger.info(f"会话 {chat_id} 触发无需回复策略 (no_reply)")
                    await session.commit()
                    return

                # 分支 A: 价格与议价处理
                if detected_intent == "price":
                    conv.bargain_count += 1
                    guardrail_decision = price_guardrail.evaluate(
                        listed_price=item.price,
                        min_price=item.min_price,
                        step_discount=item.step_discount,
                        max_rounds=item.max_bargain_rounds,
                        current_round=conv.bargain_count,
                        buyer_msg=user_msg,
                        allow_gift=item.allow_gift,
                        gift_desc=item.gift_description
                    )
                    ai_output = await self.price_agent.generate_price_reply(
                        user_msg=user_msg,
                        item_desc=item_desc_text,
                        history=history,
                        guardrail_decision=guardrail_decision
                    )

                # 分支 B: 技术规格咨询 (支持 RAG 知识库检索增强)
                elif detected_intent == "tech":
                    ai_output = await self.tech_agent.generate_tech_reply(
                        user_msg=user_msg,
                        item_desc=item_desc_text,
                        history=history,
                        item_id=item.item_id,
                        tech_specs=item.tech_specs
                    )

                # 分支 C: 物流与通用咨询
                else:
                    ai_output = await self.default_agent.generate_default_reply(
                        user_msg=user_msg,
                        item_desc=item_desc_text,
                        history=history,
                        item_id=item.item_id
                    )

            reply_text = ai_output.get("reply", "").strip()
            thinking = ai_output.get("thinking", "")

            # 8. 处理人机协同模式 (Auto / Draft)
            if conv.copilot_mode == CopilotMode.DRAFT.value:
                # 草稿模式：仅生成待审核建议，推送到工作台，不直接发出
                draft_msg = Message(
                    chat_id=chat_id,
                    seller_id=seller_id,
                    item_id=item_id,
                    sender_id=seller_id,
                    role=MessageRole.ASSISTANT.value,
                    content=reply_text,
                    intent=detected_intent,
                    ai_thinking=thinking,
                    draft_status=DraftStatus.PENDING.value,
                    timestamp=datetime.utcnow()
                )
                session.add(draft_msg)
                await session.commit()
                await session.refresh(draft_msg)

                await event_bus.publish("draft_ready", {
                    "draft_id": draft_msg.id,
                    "chat_id": chat_id,
                    "content": reply_text,
                    "intent": detected_intent,
                    "thinking": thinking,
                    "timestamp": draft_msg.timestamp.isoformat()
                })
                logger.info(f"会话 {chat_id} 生成 AI 草稿待人工确认: {reply_text}")

            else:
                # 全自动模式：模拟拟人输入延时后直接发送
                if settings.SIMULATE_HUMAN_TYPING:
                    delay = min(random.uniform(0.8, 1.5) + len(reply_text) * 0.08, 6.0)
                    logger.debug(f"模拟拟人打字，延迟发送 {delay:.2f} 秒...")
                    await asyncio.sleep(delay)

                if self._sender_func:
                    await self._sender_func(seller_id, chat_id, buyer_id, reply_text)

                assistant_msg = Message(
                    chat_id=chat_id,
                    seller_id=seller_id,
                    item_id=item_id,
                    sender_id=seller_id,
                    role=MessageRole.ASSISTANT.value,
                    content=reply_text,
                    intent=detected_intent,
                    ai_thinking=thinking,
                    draft_status=DraftStatus.DIRECT_SENT.value,
                    timestamp=datetime.utcnow()
                )
                session.add(assistant_msg)
                await session.commit()

                # 动态学习高频问答至语义缓存 (支持 Redis 8)
                if not cached_res and reply_text:
                    await semantic_cache.set_async(user_msg, reply_text)

                await event_bus.publish("message_sent", {
                    "chat_id": chat_id,
                    "seller_id": seller_id,
                    "role": MessageRole.ASSISTANT.value,
                    "content": reply_text,
                    "intent": detected_intent,
                    "thinking": thinking,
                    "timestamp": assistant_msg.timestamp.isoformat()
                })
                logger.info(f"会话 {chat_id} AI 自动发送: {reply_text}")


workflow = ConversationWorkflow()
