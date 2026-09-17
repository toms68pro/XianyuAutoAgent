import json
import asyncio
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from loguru import logger
from app.core.event_bus import event_bus

router = APIRouter(prefix="/api/sse", tags=["实时事件推流"])


@router.get("")
async def sse_event_stream(request: Request):
    """
    全双工 SSE 实时推流接口
    推送新进消息、AI 思考轨迹、草稿待审、协同模式切换及风控告警
    """
    queue = event_bus.subscribe("*")

    async def event_generator():
        try:
            # 初始连接握手包
            yield f"event: connected\ndata: {json.dumps({'status': 'ok', 'message': 'SSE 实时长连接就绪'})}\n\n"

            while True:
                # 检查客户端是否断开
                if await request.is_disconnected():
                    break

                try:
                    # 等待事件，带 15 秒心跳保活
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    topic = event.get("topic", "message")
                    data = event.get("data", {})
                    yield f"event: {topic}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    # 发送轻量保活 ping
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            event_bus.unsubscribe("*", queue)
            logger.debug("SSE 客户端断开连接")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
