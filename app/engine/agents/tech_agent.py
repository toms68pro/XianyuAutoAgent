from typing import List, Dict, Any, Optional
from app.engine.agents.base import BaseAsyncAgent
from app.core.rag import knowledge_base

TECH_AGENT_SYSTEM_PROMPT = """【角色设定】
你是一位对数码、二奢、潮流、百货有极深经验的产品技术专家。负责向买家解答商品参数、规格、型号、使用场景、配件完整度与兼容性问题。

【回复原则】
1. 语言风格：通俗易懂，将晦涩的专业参数转化为日常大白话，不堆砌生僻术语。
2. 实事求是：以【商品基本信息】及卖家提供的说明为准，不夸大、不瞎编。若有【知识库精准匹配解答】，优先按标准答复回答。
3. 篇幅控制：每句≤12字，总字数≤45字，直接切中买家要害。
4. 引导意向：解答完参数后，顺带引导买家确认成色或提议拍下。"""


class TechAsyncAgent(BaseAsyncAgent):
    """技术咨询与参数解答 Agent (支持 RAG 知识库检索增强)"""

    def __init__(self):
        super().__init__(system_prompt=TECH_AGENT_SYSTEM_PROMPT)

    async def generate_tech_reply(
        self,
        user_msg: str,
        item_desc: str,
        history: List[Dict[str, str]],
        item_id: Optional[str] = None,
        tech_specs: str = ""
    ) -> Dict[str, Any]:
        instructions = []
        if tech_specs:
            instructions.append(f"【实物参数与成色说明】：\n{tech_specs}")

        # RAG 知识库检索
        rag_context = await knowledge_base.format_rag_context(user_msg, item_id)
        if rag_context:
            instructions.append(rag_context)

        extra_instruction = "\n\n".join(instructions)

        res = await self.generate(
            user_msg=user_msg,
            item_desc=item_desc,
            history=history,
            temperature=0.3,
            extra_system_instruction=extra_instruction
        )
        if rag_context:
            res["thinking"] = f"[命中RAG知识库] | {res.get('thinking', '')}"
        return res
