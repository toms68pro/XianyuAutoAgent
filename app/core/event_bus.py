import asyncio
from typing import Dict, Set, Any, Callable, Coroutine
from loguru import logger


class EventBus:
    """全异步应用事件总线，负责驱动长连接、Agent 工作流与前端 Web 实时流 (SSE) 协同"""

    def __init__(self):
        self._subscribers: Dict[str, Set[asyncio.Queue]] = {}
        self._handlers: Dict[str, Set[Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]]] = {}

    def subscribe(self, topic: str) -> asyncio.Queue:
        """为 SSE 实时客户端订阅特定主题队列"""
        if topic not in self._subscribers:
            self._subscribers[topic] = set()
        queue = asyncio.Queue(maxsize=100)
        self._subscribers[topic].add(queue)
        return queue

    def unsubscribe(self, topic: str, queue: asyncio.Queue):
        """取消订阅"""
        if topic in self._subscribers and queue in self._subscribers[topic]:
            self._subscribers[topic].remove(queue)
            if not self._subscribers[topic]:
                del self._subscribers[topic]

    def register_handler(self, topic: str, handler: Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]):
        """注册内部协程监听处理器"""
        if topic not in self._handlers:
            self._handlers[topic] = set()
        self._handlers[topic].add(handler)

    async def publish(self, topic: str, data: Dict[str, Any]):
        """异步广播事件消息"""
        payload = {"topic": topic, "data": data}

        # 1. 广播给 SSE 队列
        if topic in self._subscribers:
            for q in list(self._subscribers[topic]):
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    logger.warning(f"事件总线队列满，丢弃旧事件: {topic}")

        # 广播给全局通用通配主题 '*'
        if "*" in self._subscribers:
            for q in list(self._subscribers["*"]):
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    pass

        # 2. 调用已注册的异步处理器
        if topic in self._handlers:
            tasks = [asyncio.create_task(h(data)) for h in self._handlers[topic]]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)


event_bus = EventBus()
