"""
api_analytics.py —— 学情统计与知识图谱分析接口（界面2）
  GET /api/analytics/overview       整体概览（KPI）
  GET /api/analytics/trend          得分率趋势（按天）
  GET /api/analytics/distribution   得分率分布（直方图分桶）
  GET /api/analytics/knowledge      知识点掌握度（柱状图）
  GET /api/analytics/recent         最近 N 条判题记录（表格）
  GET /api/analytics/graph_stats    知识图谱（节点标色：错误率高的节点标红）
"""
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import mean, median
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from db.database import get_conn, from_json
from knowledge.kg_builder import get_kg
from utils.logger import get_logger


router = APIRouter(prefix="/api/analytics", tags=["analytics"])
_lg = get_logger("analytics")


def _ok(data):
    return JSONResponse(content={"success": True, "data": data})


def _err(msg, code=500):
    return JSONResponse(status_code=code, content={"success": False, "error": msg})


# ---------- 1. 总览 KPI ----------
@router.get("/overview")
def overview(days: int = Query(30, ge=1, le=365)):
    """返回指定天数范围内的核心 KPI。"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        cur.execute("""
            SELECT
                COUNT(*)                            AS paper_cnt,
                COALESCE(SUM(problem_count), 0)     AS problem_cnt,
                COALESCE(AVG(score_rate), 0)        AS avg_rate,
                COALESCE(AVG(total_score), 0)       AS avg_score,
                COALESCE(SUM(is_multi_problem), 0)  AS multi_cnt,
                COALESCE(SUM(CASE WHEN is_pass=1 THEN 1 ELSE 0 END), 0) AS pass_cnt,
                COALESCE(SUM(error_logic), 0)       AS logic_err,
                COALESCE(SUM(error_calculation), 0) AS calc_err,
                COALESCE(SUM(error_concept), 0)     AS concept_err
            FROM judge_records WHERE created_at >= ?
        """, (since,))
        row = cur.fetchone()
        conn.close()

        paper_cnt = row["paper_cnt"] or 0
        pass_cnt = row["pass_cnt"] or 0
        multi_cnt = row["multi_cnt"] or 0
        return _ok({
            "days": days,
            "since": since,
            "paper_count": paper_cnt,
            "problem_count": row["problem_cnt"] or 0,
            "avg_score_rate": round((row["avg_rate"] or 0), 4),
            "avg_score": round((row["avg_score"] or 0), 2),
            "pass_count": pass_cnt,
            "pass_rate": round(pass_cnt / paper_cnt, 4) if paper_cnt else 0.0,
            "multi_problem_count": multi_cnt,
            "single_problem_count": max(0, paper_cnt - multi_cnt),
            "error_totals": {
                "logic_gap": row["logic_err"] or 0,
                "calculation_error": row["calc_err"] or 0,
                "concept_error": row["concept_err"] or 0,
            },
        })
    except Exception as e:
        _lg.error(f"overview: {e}")
        return _err(str(e))


# ---------- 2. 趋势（按天） ----------
@router.get("/trend")
def trend(days: int = Query(30, ge=1, le=180)):
    """按天聚合：每天的平均得分率、答卷数、错误数。"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        since_date = (datetime.now() - timedelta(days=days)).date().isoformat()
        cur.execute("""
            SELECT
                substr(created_at, 1, 10)        AS day,
                COUNT(*)                         AS paper_cnt,
                COALESCE(AVG(score_rate), 0)     AS avg_rate,
                COALESCE(SUM(error_logic), 0) +
                COALESCE(SUM(error_calculation), 0) +
                COALESCE(SUM(error_concept), 0)   AS err_total
            FROM judge_records
            WHERE substr(created_at, 1, 10) >= ?
            GROUP BY day
            ORDER BY day ASC
        """, (since_date,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        # 补全缺失日期（保持连续）
        start = datetime.now().date() - timedelta(days=days - 1)
        map_day = {r["day"]: r for r in rows}
        full = []
        for i in range(days):
            d = (start + timedelta(days=i)).isoformat()
            full.append(map_day.get(d, {
                "day": d, "paper_cnt": 0, "avg_rate": 0, "err_total": 0,
            }))
        # 数值四舍五入
        for r in full:
            r["avg_rate"] = round(r["avg_rate"], 4)
        return _ok({"days": days, "series": full})
    except Exception as e:
        _lg.error(f"trend: {e}")
        return _err(str(e))


# ---------- 3. 得分率分布（10 桶直方图）----------
@router.get("/distribution")
def distribution(days: int = Query(30, ge=1, le=365)):
    """把 score_rate 分到 10 个桶：[0,10%), [10,20%) ... [90,100%]。"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        cur.execute("""
            SELECT score_rate FROM judge_records WHERE created_at >= ?
        """, (since,))
        rates = [r["score_rate"] for r in cur.fetchall()]
        conn.close()

        buckets = [
            {"label": "0-10%",   "min": 0.0,  "max": 0.1},
            {"label": "10-20%",  "min": 0.1,  "max": 0.2},
            {"label": "20-30%",  "min": 0.2,  "max": 0.3},
            {"label": "30-40%",  "min": 0.3,  "max": 0.4},
            {"label": "40-50%",  "min": 0.4,  "max": 0.5},
            {"label": "50-60%",  "min": 0.5,  "max": 0.6},
            {"label": "60-70%",  "min": 0.6,  "max": 0.7},
            {"label": "70-80%",  "min": 0.7,  "max": 0.8},
            {"label": "80-90%",  "min": 0.8,  "max": 0.9},
            {"label": "90-100%", "min": 0.9,  "max": 1.001},
        ]
        # 100% 归入最后一桶（max=1.001）
        for b in buckets:
            b["count"] = 0
        for r in rates:
            for b in buckets:
                if b["min"] <= r < b["max"]:
                    b["count"] += 1
                    break
        return _ok({"days": days, "total": len(rates), "buckets": buckets})
    except Exception as e:
        _lg.error(f"distribution: {e}")
        return _err(str(e))


# ---------- 4. 知识点掌握度 ----------
@router.get("/knowledge")
def knowledge(days: int = Query(30, ge=1, le=365)):
    """返回知识图谱节点 + 错误率，供前端柱状图与图谱标色。"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        # 1) 当前周期统计
        cur.execute("""
            SELECT node_id, node_name,
                   SUM(total_count)  AS total_count,
                   SUM(error_count)  AS error_count
            FROM knowledge_stats
            WHERE updated_at >= ?
            GROUP BY node_id, node_name
            ORDER BY total_count DESC
        """, (since,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        # 合并：保留图谱全节点，未出现过的 total=0
        kg = get_kg()
        stat_map = {r["node_id"]: r for r in rows}
        items = []
        for nid in kg.get_node_ids():
            s = stat_map.get(nid, {})
            total = int(s.get("total_count") or 0)
            err = int(s.get("error_count") or 0)
            items.append({
                "node_id": nid,
                "node_name": kg.get_name(nid) if not s.get("node_name") else s["node_name"],
                "total_count": total,
                "error_count": err,
                "error_rate": round(err / total, 4) if total else 0.0,
                "mastery": round(1 - (err / total), 4) if total else None,
            })
        # 按掌握度升序（薄弱在上）
        items.sort(key=lambda x: (x["mastery"] is None, x["mastery"] or 0))
        return _ok({"days": days, "items": items})
    except Exception as e:
        _lg.error(f"knowledge: {e}")
        return _err(str(e))


# ---------- 5. 最近判题 ----------
@router.get("/recent")
def recent(limit: int = Query(20, ge=1, le=100)):
    """最近 N 条判题记录（按时间倒序）。"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, image_name, total_score, full_score, score_rate,
                   problem_count, is_multi_problem,
                   error_logic, error_calculation, error_concept,
                   weak_points, is_pass, duration_ms, created_at
            FROM judge_records
            ORDER BY created_at DESC, id DESC
            LIMIT ?
        """, (limit,))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        for r in rows:
            r["score_rate"] = round(r["score_rate"] or 0, 4)
            r["weak_points"] = from_json(r["weak_points"], [])
        return _ok({"items": rows})
    except Exception as e:
        _lg.error(f"recent: {e}")
        return _err(str(e))


# ---------- 6. 知识图谱（节点标色） ----------
@router.get("/graph_stats")
def graph_stats(days: int = Query(30, ge=1, le=365)):
    """返回知识图谱全部节点 + 边，按错误率标色。"""
    try:
        kg = get_kg()
        graph = kg.to_dict_for_frontend()

        # 取每个节点的错误率
        conn = get_conn()
        cur = conn.cursor()
        since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        cur.execute("""
            SELECT node_id, SUM(total_count) AS total_count, SUM(error_count) AS error_count
            FROM knowledge_stats
            WHERE updated_at >= ?
            GROUP BY node_id
        """, (since,))
        stats = {r["node_id"]: dict(r) for r in cur.fetchall()}
        conn.close()

        # 节点加上 error_rate / mastery 字段
        for n in graph["nodes"]:
            s = stats.get(n["id"], {})
            total = int(s.get("total_count") or 0)
            err = int(s.get("error_count") or 0)
            n["total_count"] = total
            n["error_count"] = err
            n["error_rate"] = round(err / total, 4) if total else 0.0
            n["mastery"] = round(1 - (err / total), 4) if total else None
            n["tested"] = total > 0
        return _ok({"days": days, "graph": graph})
    except Exception as e:
        _lg.error(f"graph_stats: {e}")
        return _err(str(e))