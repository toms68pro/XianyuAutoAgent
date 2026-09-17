import re
from typing import Tuple


class SecurityManager:
    """系统安全防线：敏感导流词拦截、反 Prompt 注入与合规过滤"""

    # 违规导流词库 (含常见变形与谐音)
    BLOCKED_PATTERNS = [
        r"(微\s*[信|芯|心|x]|v\s*x|wechat|wx|加\s*v)",
        r"(q\s*q|扣\s*扣|企鹅号)",
        r"(支\s*付\s*宝|zhifubao|alipay)",
        r"(银\s*行\s*卡|转\s*账|私\s*下|线\s*下\s*交易|当\s*面\s*扫)",
        r"(淘\s*宝\s*店铺|拼\s*多\s*多|京\s*东)",
        r"(电\s*话|手\s*机\s*号|1[3-9]\d{9})"
    ]

    # 常见 Prompt 注入与越狱测试模式
    INJECTION_PATTERNS = [
        r"(忽略|忘掉|放弃).*(之前|上方|系统).*(指令|提示词|设定|规则)",
        r"(you are now|ignore previous instructions|system prompt|jailbreak)",
        r"(你现在不是.*而是|从现在开始你是一个)",
        r"(输出.*完整.*prompt|打印.*开发者模式)",
        r"(请如实复述|毫无保留地展示)"
    ]

    def __init__(self):
        self._blocked_regex = [re.compile(p, re.IGNORECASE) for p in self.BLOCKED_PATTERNS]
        self._injection_regex = [re.compile(p, re.IGNORECASE) for p in self.INJECTION_PATTERNS]

    def check_injection(self, text: str) -> bool:
        """检查用户输入是否包含恶意 Prompt 注入"""
        if not text:
            return False
        return any(regex.search(text) for regex in self._injection_regex)

    def filter_reply(self, text: str) -> Tuple[str, bool]:
        """
        过滤 AI 或卖家回复内容，拦截违规导流信息
        
        Returns:
            (filtered_text, was_modified)
        """
        if not text:
            return text, False

        for regex in self._blocked_regex:
            if regex.search(text):
                return "[安全合规提醒] 平台严禁脱离闲鱼交易，请通过闲鱼官方平台沟通及下单。", True

        return text, False


security_manager = SecurityManager()
