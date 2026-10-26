"""R1 Agent Harness — 评测回路(Eval Harness): 评审集回归, 输出意图准确率/守卫通过率/降级正确率。
评审集 app/evalset.jsonl (≥100条): {question, expect_intent, expect_confidence_in, must_not_contain}
仅评测确定性路径(路由/工具直答/守卫), 不消耗LLM — 可进CI与CronJob。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

from ..guards import route_intent, numeric_guard, parse_proc_request
from ..direct import direct_diff_answer

@dataclass
class EvalResult:
    total: int
    intent_acc: float
    guard_pass: float
    parse_pass: float
    failures: list

def _load_evalset() -> list[dict]:
    path = os.path.join(os.path.dirname(__file__), "..", "evalset.jsonl")
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(json.loads(line))
    return out

def run_eval() -> EvalResult:
    cases = _load_evalset()
    intent_ok = guard_ok = parse_ok = 0
    failures = []
    for c in cases:
        q = c["question"]
        got = route_intent(q)
        if got == c["expect_intent"]:
            intent_ok += 1
        else:
            failures.append({"q": q[:40], "kind": "intent", "want": c["expect_intent"], "got": got})
        if c.get("parse"):
            p = parse_proc_request(q)
            want = c["parse"]
            if (p["qty"] == want.get("qty")) and (want.get("ing") in (p["ing_hint"] or "")):
                parse_ok += 1
            else:
                failures.append({"q": q[:40], "kind": "parse", "got": p})
        if c.get("adversarial_answer") is not None:
            v = numeric_guard(c["adversarial_answer"], c.get("tool_outputs", []))
            if v["ok"] == c["expect_guard_pass"]:
                guard_ok += 1
            else:
                failures.append({"q": q[:40], "kind": "guard", "expect": c["expect_guard_pass"], "got": v["ok"]})
        elif c.get("tool_lines") is not None:
            ans = direct_diff_answer({"lines": c["tool_lines"]}, 7, "2026-10-23")
            tool_json = json.dumps({"date": "2026-10-23", "store_id": 7,
                                    "lines": c["tool_lines"]}, ensure_ascii=False)
            v = numeric_guard(ans["answer"], [tool_json])
            if v["ok"]:
                guard_ok += 1
            else:
                failures.append({"q": q[:40], "kind": "direct_guard", "detail": v["unverified"][:4]})
    n = len(cases)
    n_guard = sum(1 for c in cases if c.get("adversarial_answer") is not None or c.get("tool_lines"))
    n_parse = sum(1 for c in cases if c.get("parse"))
    return EvalResult(
        total=n,
        intent_acc=round(intent_ok / n * 100, 1),
        guard_pass=round(guard_ok / n_guard * 100, 1) if n_guard else 100.0,
        parse_pass=round(parse_ok / n_parse * 100, 1) if n_parse else 100.0,
        failures=failures[:20],
    )
