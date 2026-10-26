"""意图路由与数字溯源守卫(纯函数, 可测) —— 反P2/P5/P6的关键防线"""
from __future__ import annotations

import re

# 规则路由(先规则后LLM, 简单意图不进大模型, 省CPU吞吐)
DIFF_KEYS = ("差异", "浪费", "用量", "预警", "领料", "损耗", "实际用了", "多用了", "少记")
MENU_KEYS = ("点餐", "推荐", "菜单", "菜品", "想吃什么", "招牌")
STATE_KEYS = ("你好", "谢谢", "再见", "在吗")
PROC_KEYS = ("采购", "补货", "订货", "进货", "比价", "建议单", "供应商")
FAQ_KEYS = ("怎么降", "如何降", "怎么减", "如何减", "怎样降", "什么是", "怎么换算", "如何换算")
FORECAST_KEYS = ("预测", "未来", "下周", "明天备", "备货多少")

def route_intent(question: str) -> str:
    q = (question or "").lower()
    if any(k in q for k in FORECAST_KEYS):
        return "forecast_agent"
    if any(k in q for k in FAQ_KEYS):
        return "fallback"                      # FAQ类优先走语义缓存(反P2: 不为常识问题耗LLM)
    if any(k in q for k in PROC_KEYS):
        return "procurement_agent"
    if any(k in q for k in DIFF_KEYS):
        return "diff_agent"
    if any(k in q for k in MENU_KEYS):
        return "menu_agent"
    if any(k in q for k in STATE_KEYS):
        return "smalltalk"
    return "knowledge_agent"

_QTY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|公斤|千克)")
_STOP = ("帮", "给", "号店", "门店", "采购", "补货", "订货", "进货", "公斤", "千克", "kg",
         "一下", "请", "要", "需要", "我想", "预测", "下周", "未来", "的需求", "需求",
         "看看", "查一下", "的", "最近", "几天", "是多少", "多少")

def parse_proc_request(question: str) -> dict:
    """解析采购请求: 数量+单位+疑似食材词(规则抽取, 失败返回qty=None由上游追问)"""
    m = _QTY_RE.search(question)
    qty = float(m.group(1)) if m else None
    word = question
    if m:
        word = question[:m.start()] + question[m.end():]
    for s in _STOP:
        word = word.replace(s, " ")
    word = re.sub(r"\d+(?:\.\d+)?", " ", word)     # 清掉门店编号等残留数字
    word = word.strip(" ,。!?，。！？ ")
    return {"qty": qty, "unit": "kg", "ing_hint": word or None}

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")

def _norm(n: float) -> list[str]:
    """同一数值的等价表达: 原值/克↔公斤/取整"""
    out = {repr(n), str(int(n)) if n == int(n) else str(round(n, 1))}
    out |= {str(round(n * 1000, 1)), str(int(n * 1000)) if (n * 1000) == int(n * 1000) else str(round(n * 1000, 1))}
    out |= {str(round(n / 1000, 1))} if n >= 1000 else set()
    return {o for o in out if o and o != "0"}

def numeric_guard(answer: str, tool_outputs: list[str], tolerance_pct: float = 2.0) -> dict:
    """校验答案中的数字必须能在工具输出中溯源(反幻觉: '8公斤牛肉'事件的技术绝杀)。
    返回 {ok, unverified: [...], confidence}"""
    if not tool_outputs:
        return {"ok": False, "unverified": [], "confidence": "LOW",
                "reason": "无工具输出可溯源(数据依赖不满足)"}
    haystack = "\n".join(tool_outputs)
    candidates = [float(m) for m in _NUM_RE.findall(haystack)]
    unverified = []
    for tok in _NUM_RE.findall(answer):
        n = float(tok)
        if n in (0, 1, 2, 3, 4, 5, 7, 10, 15, 20, 30, 50, 100):      # 常见非业务数字(阈值/序号)放行
            continue
        if tok in haystack:
            continue
        ok = False
        # 同一数值的等价表达: 原值/克↔公斤(字符串精确形态, 避免单字符误匹配)
        for v in (n, n * 1000, n / 1000):
            for form in (str(round(v, 1)), str(int(v)) if v >= 10 else None,
                         repr(int(v)) if v >= 10 and v == int(v) else None):
                if form and form in haystack:
                    ok = True; break
            if ok: break
            if not ok:                            # ±tolerance% 容差(四舍五入/换算差异)
                for v in (n, n * 1000, n / 1000):
                    for m in candidates:
                        if m and abs(v - m) / max(abs(m), 1e-9) * 100 <= tolerance_pct:
                            ok = True; break
                    if ok: break
        if not ok:
            unverified.append(tok)
    return {"ok": not unverified, "unverified": unverified,
            "confidence": "HIGH" if not unverified else "LOW"}

DEGRADED_NOTICE = ("⚠️ 本回答处于降级模式: {reason}\n"
                   "建议参考: {fallback}")
