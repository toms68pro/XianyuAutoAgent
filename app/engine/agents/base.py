import time
from typing import List, Dict, Any, Optional
from loguru import logger

from app.config import settings
from app.core.security import security_manager
from app.core.ai_client import ai_client_manager


class BaseAsyncAgent:
    """全异步 Agent 基类 (支持任何兼容 OpenAI 协议的模型平台)"""

    def __init__(self, system_prompt: str, model_name: Optional[str] = None):
        self.system_prompt = system_prompt
        self.model_name = model_name or settings.MODEL_NAME

    def _build_messages(
        self,
        user_msg: str,
        item_desc: str,
        history: List[Dict[str, str]],
        extra_system_instruction: str = ""
    ) -> List[Dict[str, str]]:
        """构建结构化上下文对话链"""
        system_content = (
            f"【商品基本信息】\n{item_desc}\n\n"
            f"【角色设定与总则】\n{self.system_prompt}\n"
        )
        if extra_system_instruction:
            system_content += f"\n{extra_system_instruction}\n"

        messages = [{"role": "system", "content": system_content}]

        # 仅截取最近 10 轮对话以控制 Context 长度与 Token 消耗
        recent_history = history[-10:] if history else []
        for h in recent_history:
            if h.get("role") in ["user", "assistant"]:
                messages.append({"role": h["role"], "content": h["content"]})

        messages.append({"role": "user", "content": user_msg})
        return messages

    async def generate(
        self,
        user_msg: str,
        item_desc: str,
        history: List[Dict[str, str]],
        temperature: float = 0.3,
        extra_system_instruction: str = ""
    ) -> Dict[str, Any]:
        """异步生成智能回复主流程 (含前置安全防护与离线降级兜底)"""
        start_t = time.time()
        messages = self._build_messages(user_msg, item_desc, history, extra_system_instruction)

        # 1. 检查买家输入是否包含 Prompt 注入攻击
        if security_manager.check_injection(user_msg):
            logger.warning(f"检测到潜在的 Prompt 注入攻击: {user_msg}")
            return {
                "reply": "您好，我只解答与该商品相关的交易与售卖问题哦~",
                "thinking": "触发反注入安全防御，拒绝执行外部指令",
                "latency_ms": int((time.time() - start_t) * 1000)
            }

        # 2. 检查大模型 API 客户端配置
        client = ai_client_manager.get_client()
        if not client:
            logger.info("未配置大模型 API Key，启用离线确定性兜底回复")
            return {
                "reply": "您好！商品信息请参考详情页介绍，现货正品，直接拍下即可按时发出~",
                "thinking": "未配置大模型 API Key，执行离线安全兜底话术",
                "latency_ms": int((time.time() - start_t) * 1000)
            }

        # 3. 请求模型生成回复
        try:
            resp = await client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=temperature,
                max_tokens=400,
                top_p=0.8
            )
            raw_reply = resp.choices[0].message.content or ""
            latency_ms = int((time.time() - start_t) * 1000)

            # 4. 后置合规敏感词脱敏拦截
            filtered_reply, was_modified = security_manager.filter_reply(raw_reply)

            return {
                "reply": filtered_reply,
                "thinking": f"生成耗时 {latency_ms}ms, 输出规范" if not was_modified else "触发合规导流敏感词替换过滤",
                "latency_ms": latency_ms,
                "usage": resp.usage.model_dump() if resp.usage else {}
            }
        except Exception as e:
            logger.error(f"大模型异步调用异常: {e}")
            return {
                "reply": "您好，当前咨询人数较多，请看详情描述，确认要可直接拍下，随时为您发出~",
                "thinking": f"模型调用网络异常，自动触发降级: {str(e)}",
                "latency_ms": int((time.time() - start_t) * 1000)
            }
