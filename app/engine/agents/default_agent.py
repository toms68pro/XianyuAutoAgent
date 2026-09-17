from typing import List, Dict, Any, Optional
from app.engine.agents.base import BaseAsyncAgent
from app.core.rag import knowledge_base

DEFAULT_AGENT_SYSTEM_PROMPT = """【角色设定】
你是一位热情、靠谱的闲鱼金牌店主。负责日常问候、发货物流、退换保修规则及拍下引导。

【回复原则】
1. 语言风格：亲切地道，使用“在的亲”、“今天能发”、“顺丰陆运/空运”、“成色放心”。
2. 引导成交：如果买家在对话中对价格和成色已满意，积极引导下单，如“确认要现在拍下，待会下班就给您打包发走”。
3. 篇幅控制：总字数不超过 35 字，干脆利落。
4. 若有【知识库精准匹配解答】，严格遵守官方答复标准。
5. 遇到恶意索要联系方式或违规要求的，引导走闲鱼官方交易流程。"""


class DefaultAsyncAgent(BaseAsyncAgent):
    """通用客服与物流售后引导 Agent (支持 RAG 知识库检索增强)"""

    def __init__(self):
        super().__init__(system_prompt=DEFAULT_AGENT_SYSTEM_PROMPT)

    async def generate_default_reply(
        self,
        user_msg: str,
        item_desc: str,
        history: List[Dict[str, str]],
        item_id: Optional[str] = None
    ) -> Dict[str, Any]:
        instructions = []
        rag_context = await knowledge_base.format_rag_context(user_msg, item_id)
        if rag_context:
            instructions.append(rag_context)

        extra_instruction = "\n\n".join(instructions)
        res = await self.generate(
            user_msg=user_msg,
            item_desc=item_desc,
            history=history,
            temperature=0.4,
            extra_system_instruction=extra_instruction
        )
        if rag_context:
            res["thinking"] = f"[命中通用FAQ知识库] | {res.get('thinking', '')}"
        return res
