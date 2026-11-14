"""R1 Agent Harness — 预算控制(反P2的运行时化): LLM调用数/token/连续失败熔断"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


class BudgetExceeded(Exception):
    pass


@dataclass
class Budget:
    max_llm_calls: int = 6
    max_llm_tokens: int = 9000
    max_consecutive_errors: int = 2
    max_tool_calls: int = 24                    # [OPT-C2] 工具调用上限(防失控循环)
    llm_calls: int = 0
    llm_tokens: int = 0
    tool_calls: int = 0                         # [OPT-C2]
    consecutive_errors: int = 0
    created_at: float = field(default_factory=time.time)

    def charge_call(self, tokens: int = 0) -> None:
        if self.llm_calls >= self.max_llm_calls:
            raise BudgetExceeded(f"LLM调用次数预算耗尽({self.max_llm_calls})")
        if self.llm_tokens + tokens > self.max_llm_tokens:
            raise BudgetExceeded(f"token预算耗尽({self.max_llm_tokens})")
        self.llm_calls += 1
        self.llm_tokens += tokens

    def record_error(self) -> None:
        self.consecutive_errors += 1
        if self.consecutive_errors >= self.max_consecutive_errors:
            raise BudgetExceeded(f"连续LLM失败{self.consecutive_errors}次, 熔断降级")

    def record_success(self) -> None:
        self.consecutive_errors = 0

    def charge_tool(self) -> None:
        """[OPT-C2] 工具调用计入预算: 超上限熔断(失控循环的运行时防线)"""
        if self.tool_calls >= self.max_tool_calls:
            raise BudgetExceeded(f"工具调用预算耗尽({self.max_tool_calls})")
        self.tool_calls += 1

    @property
    def snapshot(self) -> dict:
        return {"llm_calls": self.llm_calls, "llm_tokens": self.llm_tokens,
                "tool_calls": self.tool_calls,             # [OPT-C2]
                "errors": self.consecutive_errors}
