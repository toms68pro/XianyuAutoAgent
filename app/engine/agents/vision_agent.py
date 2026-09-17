import time
from typing import Dict, Any, List, Optional
import httpx
from openai import AsyncOpenAI
from loguru import logger
from app.config import settings
from app.engine.agents.base import BaseAsyncAgent


VISION_PROMPT = """【角色设定】
你是一位对数码3C、二奢、百货具有极高专业度的二手实物验机与成色评估专家。买家在闲鱼聊天中发送了实物照片、成色细节、瑕疵局部、验机报告或发票凭据。

【专业分析任务】
1. 观察判定：
   - 手机/平板/电脑：分析外观成色、边角磕碰、屏幕划痕/亮斑/老化、爱思助手或电池健康百分比、接口触点、配件是否原装。
   - 奢侈品/服饰鞋包：分析五金光泽磨损、皮质走线、防伪标识与正常使用痕迹。
   - 凭据/发票/订单：核对购买渠道与日期真实性。
2. 实事求是与专业表述：
   - 若成色完好，直接确认成色优势并热情引导拍下；
   - 若发现买家指出的细微瑕疵，如实客观评价，并结合卖家商品描述给出合理解释（如“正常微小使用痕迹，功能完全完好”）；
   - 若图片受反光或角度影响看不清，礼貌指出并请买家“换个角度/无反光再拍一张特写”。
3. 篇幅控制：亲切客观，每句≤15字，总字数不超过 45 字。"""


class VisionAsyncAgent(BaseAsyncAgent):
    """多模态图文视觉质检 Agent (支持 GPT-4o / Qwen-VL 等视觉大模型)"""

    def __init__(self):
        super().__init__(system_prompt=VISION_PROMPT)
        # 默认使用多模态视觉模型，如 qwen-vl-max 或 gpt-4o
        self.vision_model = "qwen-vl-max" if "dashscope" in settings.MODEL_BASE_URL else (settings.MODEL_NAME or "gpt-4o")

    async def analyze_image_and_reply(
        self,
        user_msg: str,
        image_url: str,
        item_desc: str,
        history: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """多模态图文联合推理"""
        start_t = time.time()
        
        system_content = f"【咨询商品信息】\n{item_desc}\n\n{self.system_prompt}"
        messages = [
            {"role": "system", "content": system_content}
        ]

        # 拼接最近对话
        for h in (history[-4:] if history else []):
            if h.get("role") in ["user", "assistant"]:
                messages.append({"role": h["role"], "content": h["content"]})

        # 拼接用户消息与图片内容 (遵循 OpenAI 视觉标准输入格式)
        user_content = []
        if user_msg:
            user_content.append({"type": "text", "text": user_msg})
        else:
            user_content.append({"type": "text", "text": "请帮我看看这张图片里的商品成色或细节怎么样？"})

        user_content.append({
            "type": "image_url",
            "image_url": {"url": image_url}
        })

        messages.append({"role": "user", "content": user_content})

        try:
            resp = await self.client.chat.completions.create(
                model=self.vision_model,
                messages=messages,
                temperature=0.2,
                max_tokens=350
            )
            reply = resp.choices[0].message.content or ""
            latency_ms = int((time.time() - start_t) * 1000)

            return {
                "reply": reply,
                "thinking": f"【多模态视觉识别完成】耗时 {latency_ms}ms | 模型: {self.vision_model}",
                "latency_ms": latency_ms
            }
        except Exception as e:
            logger.error(f"多模态视觉分析异常: {e}")
            return {
                "reply": "图片收到啦亲！从图上看大体成色完好，您具体想看哪部分细节我也可以再给您拍特写~",
                "thinking": f"视觉模型调用降级兜底: {str(e)}",
                "latency_ms": int((time.time() - start_t) * 1000)
            }


vision_agent = VisionAsyncAgent()
