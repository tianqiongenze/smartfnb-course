"""R1 Agent Harness — 上下文工程: 会话状态+token感知的提示组装+历史裁剪"""
from __future__ import annotations

from dataclasses import dataclass, field

def est_tokens(text: str) -> int:
    """粗估token(中文≈1.6字/token): 用于预算, 宁可保守"""
    return max(len(text) * 2 // 3, 1)

@dataclass
class SessionContext:
    question: str
    store_id: int
    date: str
    history: list[tuple[str, str]] = field(default_factory=list)   # (role, text)
    retrieved: list[str] = field(default_factory=list)             # 工具返回(溯源源)
    max_context_tokens: int = 4000

    def add_history(self, role: str, text: str) -> None:
        self.history.append((role, text))
        self._trim()

    def add_retrieved(self, tool_output: str) -> None:
        self.retrieved.append(tool_output)
        self._trim()

    def _trim(self) -> None:
        """从最旧的历史开始裁剪, 保留最新对话与全部溯源数据(数字依据不可丢)"""
        while est_tokens(self.assembled()) > self.max_context_tokens and len(self.history) > 2:
            self.history.pop(0)

    def assembled(self) -> str:
        parts = [f"门店={self.store_id} 日期={self.date} 问题: {self.question}"]
        if self.retrieved:
            parts.append("工具数据(回答数字只能来自此处): " + "\n".join(self.retrieved[-3:]))
        parts.extend(f"{r}: {t[:200]}" for r, t in self.history[-6:])
        return "\n".join(parts)

    @property
    def token_estimate(self) -> int:
        return est_tokens(self.assembled())
