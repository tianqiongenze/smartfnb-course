"""MCP Server: 餐饮业务工具集(2026标准 streamable-http 传输)。
每个工具返回结构化数据 + SQL溯源(反P5: 指标口径可复核)。"""
from __future__ import annotations

import os
import json
import datetime as dt
import urllib.request
import urllib.parse

import pymysql
from mcp.server.fastmcp import FastMCP

DB = dict(host=os.getenv("DB_HOST", "tidb.infra.svc.cluster.local"), port=4000,
          user="root", charset="utf8mb4", database="fnb")

mcp = FastMCP("fnb-tools", host="0.0.0.0", port=8000, stateless_http=True)

def _sanitize(v):
    """Decimal→float, date/datetime→str, bytes→str (JSON可序列化且数值类型正确)"""
    from decimal import Decimal
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (dt.date, dt.datetime)):
        return str(v)
    if isinstance(v, bytes):
        return v.decode("utf-8", "ignore")
    return v

def q(sql: str, args: tuple = ()) -> list[dict]:
    c = pymysql.connect(**DB)
    try:
        cur = c.cursor(pymysql.cursors.DictCursor)
        cur.execute(sql, args)
        return [{k: _sanitize(v) for k, v in r.items()} for r in cur.fetchall()]
    finally:
        c.close()

def _src(sql: str, args: tuple) -> dict:
    return {"sql": " ".join(sql.split()), "params": list(args)}

@mcp.tool()
def list_stores() -> str:
    """列出全部门店(编号/名称/城市)"""
    rows = q("SELECT store_id, name, city FROM store ORDER BY store_id")
    return json.dumps({"stores": rows, "trace": _src("SELECT store_id,name,city FROM store", ())},
                      ensure_ascii=False, default=str)

DIFF_SQL = """SELECT t.d AS date, t.store_id, t.ing_id, i.ing_code, i.name_std, i.category,
       t.theo_gram, COALESCE(a.actual_gram,0) AS actual_gram,
       ROUND((COALESCE(a.actual_gram,0)-t.theo_gram)/NULLIF(t.theo_gram,0)*100,1) AS diff_pct
FROM (
  SELECT sl.order_date d, sl.store_id, b.ing_id, ROUND(SUM(sl.qty*b.grams_per_serving)) theo_gram
  FROM sales_line sl JOIN bom b ON sl.dish_id=b.dish_id
  WHERE sl.order_date=%s AND sl.store_id=%s
  GROUP BY sl.order_date, sl.store_id, b.ing_id
) t LEFT JOIN (
  SELECT movement_date d, store_id, ing_id, SUM(qty_base_gram) actual_gram
  FROM stock_movement WHERE movement_date=%s AND store_id=%s AND movement_type='consume'
  GROUP BY movement_date, store_id, ing_id
) a ON t.d=a.d AND t.store_id=a.store_id AND t.ing_id=a.ing_id
JOIN ingredient i ON i.ing_id=t.ing_id
ORDER BY ABS(ROUND((COALESCE(a.actual_gram,0)-t.theo_gram)/NULLIF(t.theo_gram,0)*100,1)) DESC LIMIT %s"""

@mcp.tool()
def get_diff(store_id: int, date: str, limit: int = 20) -> str:
    """查询某门店某日的食材用量差异: 理论用量(销售×BOM) vs 实际领用, 按绝对差异率降序"""
    rows = q(DIFF_SQL, (date, store_id, date, store_id, limit))
    return json.dumps({"date": date, "store_id": store_id, "lines": rows,
                       "trace": _src("SELECT 理论(销售xBOM聚合) LEFT JOIN 实际(消耗聚合) WHERE date=%s AND store_id=%s", (date, store_id))},
                      ensure_ascii=False, default=str)

@mcp.tool()
def top_waste_ingredients(store_id: int, days: int = 7, limit: int = 10) -> str:
    """近N天某门店浪费(废弃)最多的食材Top N"""
    start = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    rows = q("""SELECT ing_id, i.name_std, SUM(qty_base_gram)/1000.0 AS waste_kg
                FROM stock_movement m JOIN ingredient i ON i.ing_id=m.ing_id
                WHERE store_id=%s AND movement_type='waste' AND movement_date>=%s
                GROUP BY ing_id, i.name_std ORDER BY waste_kg DESC LIMIT %s""",
             (store_id, start, limit))
    return json.dumps({"store_id": store_id, "days": days, "top": rows,
                       "trace": _src("SELECT ... FROM stock_movement WHERE movement_type='waste'", (store_id, start))},
                      ensure_ascii=False, default=str)

@mcp.tool()
def get_ingredient(name_or_alias: str) -> str:
    """按名称或历史别名查食材主数据(一品一码; 支持'翅中/鸡翅膀/鸡翅（中）'等别名)"""
    rows = q("""SELECT ing_id, ing_code, name_std, category, base_unit, box_ratio, aliases, ref_price
                FROM ingredient WHERE name_std LIKE %s
                   OR JSON_SEARCH(aliases, 'one', %s) IS NOT NULL LIMIT 5""",
             (f"%{name_or_alias}%", name_or_alias))
    return json.dumps({"matches": rows,
                       "trace": _src("SELECT ... FROM ingredient WHERE name_std LIKE %s OR JSON_SEARCH(aliases...)", (name_or_alias,))},
                      ensure_ascii=False, default=str)

@mcp.tool()
def theoretical_usage(store_id: int, date: str, ing_name: str) -> str:
    """查某门店某日某食材的理论用量(由销售明细×BOM推导, 精确到克)"""
    ing = q("SELECT ing_id, name_std FROM ingredient WHERE name_std=%s LIMIT 1", (ing_name,))
    if not ing:
        return json.dumps({"error": f"未找到食材: {ing_name}", "degraded": True, "reason": "ingredient_not_found"},
                          ensure_ascii=False, default=str)
    iid = ing[0]["ing_id"]
    rows = q("""SELECT t.store_id, t.ing_id, t.theo_gram, COALESCE(a.actual_gram,0) actual_gram,
                       ROUND((COALESCE(a.actual_gram,0)-t.theo_gram)/NULLIF(t.theo_gram,0)*100,1) diff_pct
                FROM (
                  SELECT sl.store_id, b.ing_id, ROUND(SUM(sl.qty*b.grams_per_serving)) theo_gram
                  FROM sales_line sl JOIN bom b ON sl.dish_id=b.dish_id
                  WHERE sl.order_date=%s AND sl.store_id=%s AND b.ing_id=%s
                  GROUP BY sl.store_id, b.ing_id
                ) t LEFT JOIN (
                  SELECT store_id, ing_id, SUM(qty_base_gram) actual_gram
                  FROM stock_movement WHERE movement_date=%s AND store_id=%s AND ing_id=%s AND movement_type='consume'
                  GROUP BY store_id, ing_id
                ) a ON t.store_id=a.store_id AND t.ing_id=a.ing_id""",
             (date, store_id, iid, date, store_id, iid))
    return json.dumps({"ingredient": ing[0], "row": rows[0] if rows else None,
                       "degraded": False if rows else True,
                       "reason": None if rows else "该日无理论/实际数据(可能未营业或数据未生成)",
                       "fallback": "建议参考近7日均值" if not rows else None,
                       "trace": _src("SELECT 理论聚合 WHERE date,store,ing 过滤", (date, store_id, iid))},
                      ensure_ascii=False, default=str)

@mcp.tool()
def get_alerts(date: str, store_id: int = 0) -> str:
    """查某日用量差异预警(>15%), store_id=0 表示全部门店"""
    sql = ("SELECT a.id, a.diff_date, a.store_id, s.name AS store_name, a.ing_id, i.name_std, "
           "a.theo_gram, a.actual_gram, a.diff_pct, a.level, a.status "
           "FROM alert a JOIN ingredient i ON i.ing_id=a.ing_id JOIN store s ON s.store_id=a.store_id "
           "WHERE a.diff_date=%s" + (" AND a.store_id=%s" if store_id else "") + " ORDER BY ABS(a.diff_pct) DESC")
    args = (date, store_id) if store_id else (date,)
    return json.dumps({"date": date, "alerts": q(sql, args),
                       "trace": _src(sql, args)}, ensure_ascii=False, default=str)

PROC_BASE = os.getenv("PROC_URL", "http://svc-procurement:8080")

@mcp.tool()
def compare_prices(ing_name: str, days: int = 90) -> str:
    """按食材名比价: 近N天各供应商实际成交均价与评分(采购历史)"""
    ing = q("SELECT ing_id, name_std FROM ingredient WHERE name_std=%s LIMIT 1", (ing_name,))
    if not ing:
        return json.dumps({"error": f"未找到食材: {ing_name}", "degraded": True}, ensure_ascii=False)
    iid = ing[0]["ing_id"]
    rows = q("""SELECT po.sup_id AS supId, s.name AS supName, s.rating,
                       ROUND(AVG(pi.unit_price),2) AS avgPrice, COUNT(*) AS dealCnt
                FROM purchase_item pi
                JOIN purchase_order po ON po.po_id = pi.po_id
                JOIN supplier s ON s.sup_id = po.sup_id
                WHERE pi.ing_id=%s AND po.order_date >= %s
                GROUP BY po.sup_id, s.name, s.rating ORDER BY avgPrice ASC LIMIT 10""",
             (iid, (dt.date.today() - dt.timedelta(days=days)).isoformat()))
    return json.dumps({"ingredient": ing[0], "quotes": rows,
                       "trace": _src("SELECT AVG(unit_price) FROM purchase_item JOIN purchase_order WHERE ing_id=%s", (iid,))},
                      ensure_ascii=False, default=str)

@mcp.tool()
def suggest_po(store_id: int, ing_name: str, qty_kg: float, unit_code: str = "kg") -> str:
    """生成采购建议单(DRAFT, 人在环): 选取历史均价最低且评分≥3.5的供应商, 写入建议单等待采购主管审批。
    注意: 本工具不会直接下单, AI不越过审批。"""
    ing = q("SELECT ing_id, name_std FROM ingredient WHERE name_std=%s LIMIT 1", (ing_name,))
    if not ing:
        return json.dumps({"error": f"未找到食材: {ing_name}", "degraded": True}, ensure_ascii=False)
    iid = ing[0]["ing_id"]
    quotes = q("""SELECT po.sup_id, s.name AS supName, s.rating, AVG(pi.unit_price) avgPrice
                  FROM purchase_item pi JOIN purchase_order po ON po.po_id=pi.po_id
                  JOIN supplier s ON s.sup_id=po.sup_id
                  WHERE pi.ing_id=%s AND po.order_date >= %s
                  GROUP BY po.sup_id, s.name, s.rating ORDER BY avgPrice ASC LIMIT 5""",
               (iid, (dt.date.today() - dt.timedelta(days=90)).isoformat()))
    pick = next((x for x in quotes if float(x["rating"]) >= 3.5), None)
    body = {"storeId": store_id, "ingId": iid, "qty": qty_kg, "unitCode": unit_code}
    if pick:
        body["supId"] = int(pick["sup_id"]); body["estPrice"] = round(float(pick["avgPrice"]), 2)
        body["reason"] = f"近90天均价最低且评分≥3.5(评分{pick['rating']}, 均价{pick['avgPrice']})"
    else:
        body["reason"] = "无合格历史比价(评分<3.5), 建议单为空供应商待人工指派"
    import urllib.request
    req = urllib.request.Request(PROC_BASE + "/api/suggestions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    resp = json.loads(urllib.request.urlopen(req, timeout=30).read())
    return json.dumps({"ingredient": ing[0], "qty": qty_kg, "unit": unit_code,
                       "supplier": pick["supName"] if pick else None,
                       "estPrice": body.get("estPrice"),
                       "suggestion": resp, "human_in_loop": "DRAFT等待采购主管审批",
                       "trace": _src("POST /api/suggestions (svc-procurement)", (store_id, iid))},
                      ensure_ascii=False, default=str)

@mcp.tool()
def get_suggestions(store_id: int = 0, status: str = "DRAFT") -> str:
    """查询采购建议单(默认DRAFT待审批)"""
    sql = ("SELECT g.id, g.store_id, s2.name AS store_name, g.ing_id, i.name_std, g.sug_date, "
           "g.suggest_qty, g.unit_code, s.name AS sup_name, g.est_price, g.reason, g.status, g.decided_by "
           "FROM po_suggestion g JOIN ingredient i ON i.ing_id=g.ing_id "
           "JOIN store s2 ON s2.store_id=g.store_id LEFT JOIN supplier s ON s.sup_id=g.sup_id "
           "WHERE g.status=%s" + (" AND g.store_id=%s" if store_id else "") + " ORDER BY g.created_at DESC LIMIT 30")
    args = (status, store_id) if store_id else (status,)
    return json.dumps({"status": status, "suggestions": q(sql, args),
                       "trace": _src(sql, args)}, ensure_ascii=False, default=str)

FORECAST_BASE = os.getenv("FORECAST_URL", "http://svc-forecast:8000")

@mcp.tool()
def get_forecast(store_id: int, ing_name: str, days: int = 7) -> str:
    """未来N天需求预测(理论需求克): 加权移动平均×周内因子×趋势; 含回测MAPE置信度与数据依赖声明。
    数据滞后>3天时自动降级(反P6), 不会静默输出低置信预测。"""
    import urllib.request
    url = f"{FORECAST_BASE}/api/forecast?storeId={store_id}&ingName={urllib.parse.quote(ing_name)}&days={days}"
    resp = json.loads(urllib.request.urlopen(url, timeout=60).read())
    return json.dumps(resp, ensure_ascii=False, default=str)

WM_BASE = os.getenv("WM_URL", "http://svc-worldmodel:8000")

@mcp.tool()
def worldmodel_simulate(store_id: int, ing_name: str, days: int = 7) -> str:
    """World Model采购量推演(R4): 基于历史需求分布(店×食材×星期)的蒙特卡洛仿真,
    扫描0.6x~1.4x均值共9档采购量, 输出各档缺货/浪费期望成本与最优推荐档。"""
    import urllib.request
    body = json.dumps({"storeId": store_id, "ingName": ing_name, "days": days}).encode()
    req = urllib.request.Request(WM_BASE + "/simulate", body,
                                 {"Content-Type": "application/json"})
    resp = json.loads(urllib.request.urlopen(req, timeout=120).read())
    best = resp.get("recommended") or {}
    plans = resp.get("plans") or []
    lines = [f"【World Model仿真】{ing_name} 门店{store_id} {days}天 "
             f"(日均需求{resp.get('avgDemandKgPerDay')}kg, 方法: 蒙特卡洛×正态拟合)"]
    for p in plans:
        mark = " ←推荐" if p is best or p.get("qtyPerDayKg") == best.get("qtyPerDayKg") else ""
        lines.append(f"· 采购{p.get('qtyPerDayKg')}kg/日: 期望缺货{p.get('expectedShortageKgPerDay')}kg/日 "
                     f"浪费{p.get('expectedWasteKgPerDay')}kg/日 成本{p.get('expectedCostPerDay')}元/日{mark}")
    return json.dumps({"answer": chr(10).join(lines), "raw": resp,
                       "trace": "POST /simulate (svc-worldmodel)"}, ensure_ascii=False, default=str)

@mcp.tool()
def forecast_with_ci(store_id: int, ing_name: str, days: int = 7) -> str:
    """带置信区间的预测(R4): p10/p50/p90三档(Kg), 比点预测更利于备货决策。"""
    import urllib.request
    url = f"{WM_BASE}/forecast-ci?storeId={store_id}&ingName={urllib.parse.quote(ing_name)}&days={days}"
    resp = json.loads(urllib.request.urlopen(url, timeout=60).read())
    lines = [f"【{ing_name} 需求预测(含置信区间)】门店{store_id}"]
    for d in resp.get("days", []):
        lines.append(f"· {d['date']}: p10={d['p10Kg']}kg / 中位={d['p50Kg']}kg / p90={d['p90Kg']}kg")
    return json.dumps({"answer": chr(10).join(lines), "raw": resp,
                       "trace": "GET /forecast-ci (svc-worldmodel)"}, ensure_ascii=False, default=str)

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
