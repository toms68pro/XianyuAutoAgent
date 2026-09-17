import re
from dataclasses import dataclass
from typing import Optional, Tuple, List
from loguru import logger


@dataclass
class GuardrailDecision:
    """确定性价格护栏决策结果"""
    decision: str                # 'ask_price' | 'counter_offer' | 'accept' | 'reject' | 'gift_alternative'
    target_price: float          # 本轮建议报价/对策价
    min_price_floor: float       # 硬性底价红线 (大模型绝对不可突破)
    gift_offered: bool           # 是否采用赠品/包邮策略让步
    gift_desc: str               # 赠品/服务说明
    instructions_for_llm: str    # 注入给大模型的硬性指令


class PriceGuardrail:
    """工业级确定性价格护栏引擎 (数字决策归代码，话术表达归 LLM，100% 杜绝破价)"""

    @staticmethod
    def extract_buyer_offer(text: str, current_price: float) -> Optional[float]:
        """从买家文本中提取出价数字"""
        clean_text = text.replace(',', '').replace('，', '')

        # 匹配 "1500能出吗", "1500出不出", "给1500", "出1500", "1500包邮"
        patterns = [
            r'(\d+(?:\.\d+)?)\s*(?:元|块)?\s*(?:能出|出不出|卖不卖|行不行|给|包邮|出吗)',
            r'(?:出|给|出价|只要)\s*(\d+(?:\.\d+)?)',
            r'(\d+(?:\.\d+)?)\s*(?:元|块)'
        ]

        for p in patterns:
            match = re.search(p, clean_text)
            if match:
                try:
                    val = float(match.group(1))
                    if 0 < val <= current_price * 2:  # 合理价格区间
                        return val
                except ValueError:
                    pass

        # 匹配 "能少50吗", "便宜100"
        diff_match = re.search(r'(?:少|便宜|优惠|减|降)\s*(\d+(?:\.\d+)?)', clean_text)
        if diff_match:
            try:
                diff = float(diff_match.group(1))
                if 0 < diff < current_price:
                    return current_price - diff
            except ValueError:
                pass

        return None

    def evaluate(
        self,
        listed_price: float,
        min_price: float,
        step_discount: float,
        max_rounds: int,
        current_round: int,
        buyer_msg: str,
        allow_gift: bool = True,
        gift_desc: str = "赠送原装配件/包顺丰快递"
    ) -> GuardrailDecision:
        """
        核心确定性决策函数
        """
        # 默认底线保护: 若未设底价，则默认为挂牌价的 90%
        if min_price <= 0:
            min_price = round(listed_price * 0.9, 2)
        if step_discount <= 0:
            step_discount = round((listed_price - min_price) / max(max_rounds, 1), 2)

        buyer_offer = self.extract_buyer_offer(buyer_msg, listed_price)

        # 1. 第一轮议价且买家未出明确价（如仅问"能便宜点吗"、"底价多少"）
        if buyer_offer is None and current_round <= 1:
            return GuardrailDecision(
                decision="ask_price",
                target_price=listed_price,
                min_price_floor=min_price,
                gift_offered=False,
                gift_desc=gift_desc,
                instructions_for_llm=(
                    f"【系统硬性决策-第一轮试探】：买家未给明确报价。"
                    f"请勿主动降价！礼貌反问买家心理诚意价多少，掌握谈判主动权。"
                    f"严禁出现任何低于标价 ¥{listed_price} 的让步数字！"
                )
            )

        # 计算本轮最大允许降价幅度 (根据议价轮次逐步阶梯释放)
        effective_round = min(current_round, max_rounds)
        allowed_discount = round(step_discount * effective_round, 2)
        counter_price = max(round(listed_price - allowed_discount, 2), min_price)

        # 2. 买家给出了明确出价
        if buyer_offer is not None:
            # Case A: 买家出价甚至高于或等于当前对策价 -> 爽快成交
            if buyer_offer >= counter_price:
                return GuardrailDecision(
                    decision="accept",
                    target_price=buyer_offer,
                    min_price_floor=min_price,
                    gift_offered=False,
                    gift_desc=gift_desc,
                    instructions_for_llm=(
                        f"【系统硬性决策-接受报价】：买家出价 ¥{buyer_offer} 符合预期。"
                        f"爽快同意成交，引导买家立即拍下，承诺改价或尽快发货。"
                    )
                )

            # Case B: 买家出价低于硬底价 (屠龙刀砍价) -> 坚决拒绝并守价
            if buyer_offer < min_price:
                should_gift = allow_gift and (current_round >= 2)
                return GuardrailDecision(
                    decision="reject",
                    target_price=counter_price,
                    min_price_floor=min_price,
                    gift_offered=should_gift,
                    gift_desc=gift_desc,
                    instructions_for_llm=(
                        f"【系统硬性决策-坚决守价】：买家出价 ¥{buyer_offer} 严重低于成本底线 ¥{min_price}。"
                        f"必须明确拒绝 ¥{buyer_offer}！"
                        f"给出当前最低底线 ¥{counter_price} 并强调成色品质。"
                        + (f"可提出附送【{gift_desc}】作为挽留条件。" if should_gift else "")
                        + f"【极度重要】：回复中严禁出现任何低于 ¥{counter_price} 的金额！"
                    )
                )

            # Case C: 买家出价在底价以上但低于本轮对策价 -> 给出本轮对策折中价
            return GuardrailDecision(
                decision="counter_offer",
                target_price=counter_price,
                min_price_floor=min_price,
                gift_offered=allow_gift,
                gift_desc=gift_desc,
                instructions_for_llm=(
                    f"【系统硬性决策-阶梯折中让步】：买家出价 ¥{buyer_offer}。"
                    f"表明立场并提出折中方案价 ¥{counter_price}。"
                    f"【极度重要】：回复中严禁出现任何低于 ¥{counter_price} 的金额！"
                )
            )

        # 3. 买家持续追问优惠但未给数字
        return GuardrailDecision(
            decision="counter_offer",
            target_price=counter_price,
            min_price_floor=min_price,
            gift_offered=allow_gift,
            gift_desc=gift_desc,
            instructions_for_llm=(
                f"【系统硬性决策-最终诚意报价】：当前商品标价 ¥{listed_price}，经过协商可给予诚意价 ¥{counter_price}。"
                f"引导买家以此价格拍下，严禁出现低于 ¥{counter_price} 的金额！"
            )
        )

    def post_validate(self, reply_text: str, min_price_floor: float) -> Tuple[str, bool]:
        """
        后置合规拦截器：扫描大模型最终输出中的所有金额数字，确保未破底价红线
        """
        if min_price_floor <= 0:
            return reply_text, False

        # 查找所有类似 1500元, ¥1500, 1500块
        found_prices = re.findall(r'(?:¥|￥)?\s*(\d+(?:\.\d+)?)\s*(?:元|块)?', reply_text)
        violated = False

        for p_str in found_prices:
            try:
                p_val = float(p_str)
                # 排除很小的数字（如年份2024、尺寸14寸、成色99新等）
                if (min_price_floor * 0.2) < p_val < min_price_floor:
                    logger.warning(f"🚨 价格护栏触发！大模型回复出现破底价数字: ¥{p_val} < 底线 ¥{min_price_floor}")
                    violated = True
                    break
            except ValueError:
                pass

        if violated:
            # 自动修复兜底文案
            safe_text = f"价格实在很诚意啦，最低只能到 ¥{min_price_floor} 顺丰包邮，看好可直接拍下改价~"
            return safe_text, True

        return reply_text, False


price_guardrail = PriceGuardrail()
