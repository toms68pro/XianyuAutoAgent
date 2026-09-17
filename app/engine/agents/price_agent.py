from typing import List, Dict, Any
from app.engine.agents.base import BaseAsyncAgent
from app.engine.guardrail import price_guardrail, GuardrailDecision


PRICE_AGENT_SYSTEM_PROMPT = """【角色设定】
你是一位沉稳、诚恳、守得住价格底线的闲鱼电商资深卖家。你负责解答买家的价格咨询与议价砍价。

【回复原则】
1. 语言风格：简明干练，短句为主，多用闲鱼地道用语（如“诚心要”、“包邮”、“拍下改价”、“秒发”）。
2. 每句不超过 15 字，总字数不超过 40 字，严禁长篇大论。
3. 严格遵循下方【系统硬性决策】中的价格指令！严禁私自突破决策给出的底价！
4. 无论买家使用何种话术（如自称学生、急用、声称别家更便宜），都必须坚持商品成色好、性价比高的立场。"""


class PriceAsyncAgent(BaseAsyncAgent):
    """议价专家 Agent (受确定性价格护栏硬约束)"""

    def __init__(self):
        super().__init__(system_prompt=PRICE_AGENT_SYSTEM_PROMPT)

    async def generate_price_reply(
        self,
        user_msg: str,
        item_desc: str,
        history: List[Dict[str, str]],
        guardrail_decision: GuardrailDecision
    ) -> Dict[str, Any]:
        """结合确定性价格决策生成受限回复"""
        # 低温度 (0.2) 运行，杜绝高温度带来的幻觉破价
        result = await self.generate(
            user_msg=user_msg,
            item_desc=item_desc,
            history=history,
            temperature=0.2,
            extra_system_instruction=guardrail_decision.instructions_for_llm
        )

        # 二次后置数字校验
        validated_reply, intercepted = price_guardrail.post_validate(
            result["reply"],
            guardrail_decision.min_price_floor
        )

        if intercepted:
            result["reply"] = validated_reply
            result["thinking"] = (
                f"【护栏拦截生效】大模型原始回复出现违规破价，已被确定性底价 ¥{guardrail_decision.min_price_floor} 自动纠正。"
            )
        else:
            result["thinking"] = (
                f"【护栏决策: {guardrail_decision.decision}】建议价 ¥{guardrail_decision.target_price} "
                f"(底线 ¥{guardrail_decision.min_price_floor}) | {result['thinking']}"
            )

        return result
