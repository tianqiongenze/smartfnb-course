"""R1 Agent Harness — 标准工具循环(observe→plan→act→verify→reflect)
收编此前散落在 graph/guards/direct 的执行逻辑, 所有专家节点统一走本循环。
verify: numeric_guard数字溯源; reflect: 预算耗尽/工具失败的降级重写。
"""
from __future__ import annotations

import json
from typing import Awaitable, Callable

from .budget import Budget, BudgetExceeded
from .context import SessionContext
from ..guards import numeric_guard
from ..direct import direct_diff_answer, needs_llm_analysis

ToolFn = Callable[[str, dict], Awaitable[dict | None]]


async def act_with_tools(ctx: SessionContext, budget: Budget, tool_fn: ToolFn,
                         tool_name: str, args: dict) -> dict | None:
    """ACT: 调工具, 结果进上下文溯源源(数字依据), 失败返回None"""
    data = await tool_fn(tool_name, args)
    if data is not None:
        ctx.add_retrieved(json.dumps(data, ensure_ascii=False)[:4000])
    return data


def verify(ctx: SessionContext, answer: str) -> tuple[str, str]:
    """VERIFY: 数字溯源校验, 不通过附加警示(置信度降级)"""
    verdict = numeric_guard(answer, ctx.retrieved)
    if verdict["ok"]:
        return answer, verdict["confidence"]
    flagged = ", ".join(verdict["unverified"][:8])
    return (answer + f"\n\n⚠️ 溯源校验: 以下数字未在工具数据中核实: {flagged}"), "LOW"


def reflect_on_budget(exc: BudgetExceeded, direct_answer: str | None) -> str:
    """REFLECT: 预算/熔断降级为工具直答或明示降级(反P4: 不静默)"""
    if direct_answer:
        return direct_answer + f"\n\n(LLM归因解读因预算控制跳过: {exc})"
    return f"⚠️ 本回答处于降级模式: {exc}\n建议: 请稍后重试或查看管理端报表。"
