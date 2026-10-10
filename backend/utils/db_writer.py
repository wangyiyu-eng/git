"""
utils/db_writer.py —— 把判题结果落库（界面2的数据源）
不依赖 ORM，直接用 sqlite3（毕设轻量化原则）。
"""
import json
from typing import Optional

from db.database import from_json, get_conn, to_json


def _score_rate(total: float, full: float) -> float:
    if not full or full <= 0:
        return 0.0
    return round(max(0.0, min(1.0, total / full)), 4)


def save_record(result: dict, full_score_default: float = 10.0) -> int:
    """
    把一次判题结果保存到 SQLite：
      - judge_records   一条
      - problem_details 每题一条（兼容单题 / 多题）
      - knowledge_stats 按节点聚合（题目涉及的每个知识点）
    返回 judge_records.id；失败返回 -1。
    """
    m3 = result.get("M3_judgment") or {}
    m2 = result.get("M2_elements") or {}

    total = float(m3.get("total_score") or 0)
    full = float(m3.get("full_score") or full_score_default)
    rate = _score_rate(total, full)

    err = m3.get("error_summary") or {}
    weak = m3.get("weak_knowledge_points") or []

    # 多题 → problem_count 来自 M3.per_problem；否则取 problems 长度 / 1
    problems = m2.get("problems") or []
    if m3.get("problem_count"):
        pcount = int(m3["problem_count"])
    elif problems:
        pcount = len(problems)
    elif m2.get("final_answer") is not None:
        pcount = 1
    else:
        pcount = 0

    is_multi = 1 if m2.get("multi_problem") else (1 if pcount > 1 else 0)
    is_pass = 1 if rate >= 0.6 else 0
    feedback = m3.get("feedback") or ""
    duration = int(result.get("total_latency_ms") or 0)

    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO judge_records (
                image_name, image_path, image_md5,
                full_score, total_score, score_rate,
                problem_count, is_multi_problem,
                error_logic, error_calculation, error_concept,
                weak_points, detail_json, feedback,
                is_pass, duration_ms, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            result.get("image_name") or "uploaded.jpg",
            result.get("image_path") or "",
            result.get("image_id") or "",
            full, total, rate,
            pcount, is_multi,
            int(err.get("logic_gap") or 0),
            int(err.get("calculation_error") or 0),
            int(err.get("concept_error") or 0),
            to_json([w.get("node_id") for w in weak]),
            to_json(result),
            feedback,
            is_pass, duration,
            result.get("created_at") or "",
        ))
        record_id = cur.lastrowid

        # ---- 每题明细 ----
        # 多题：来自 m3.per_problem 与 m2.problems
        per = m3.get("per_problem") or []
        if per:
            for i, p in enumerate(per, 1):
                _save_problem(cur, record_id, p, i)
        else:
            # 单题：直接包成一条
            _save_problem(cur, record_id, {
                "problem_index": 1,
                "total_score": total,
                "full_score": full,
                "final_answer": m2.get("final_answer"),
                "error_reasons": m3.get("error_reasons") or [],
                "error_summary": err,
                "involved_knowledge_points": m2.get("involved_knowledge_points") or [],
                "steps": m2.get("steps") or [],
            }, 1)

        # ---- 知识点聚合 ----
        _agg_knowledge(cur, m2, m3)

        conn.commit()
        return record_id
    except Exception as e:
        conn.rollback()
        # 不让数据库写入失败拖垮判题主流程
        try:
            from utils.logger import get_logger
            get_logger("db").error(f"save_record failed: {e}")
        except Exception:
            pass
        return -1
    finally:
        conn.close()


def _save_problem(cur, record_id: int, p: dict, idx: int):
    """写一条 problem_details。"""
    score = float(p.get("total_score") or 0)
    full = float(p.get("full_score") or 0)
    rate = _score_rate(score, full)

    # 判定：final_answer.verdict 优先；否则按得分率
    fa = p.get("final_answer") or {}
    verdict = (fa.get("verdict") if isinstance(fa, dict) else None) or (
        "correct" if rate >= 0.99 else ("incorrect" if rate < 0.6 else "uncertain")
    )

    errs = p.get("error_reasons") or []
    kps = p.get("involved_knowledge_points") or []
    # 统一转为字符串列表（兼容 dict / str）
    kp_ids = []
    for k in kps:
        if isinstance(k, dict):
            kp_ids.append(k.get("node_id") or k.get("id") or k.get("name") or "")
        else:
            kp_ids.append(str(k))
    kp_ids = [x for x in kp_ids if x]

    cur.execute("""
        INSERT INTO problem_details (
            record_id, problem_index, problem_text,
            score, full_score, verdict,
            error_reasons, knowledge_points, steps_json
        ) VALUES (?,?,?,?,?,?,?,?,?)
    """, (
        record_id, idx,
        (p.get("problem_text") or (fa.get("content") if isinstance(fa, dict) else "")) or "",
        score, full, verdict,
        to_json(errs),
        to_json(kp_ids),
        to_json(p.get("steps") or []),
    ))


def _agg_knowledge(cur, m2: dict, m3: dict):
    """按涉及到的知识点累加 knowledge_stats。"""
    # 收集所有涉及的知识点（合并 M3.involved / 各 per_problem.involved / 各题 standard_chain 命中）
    involved = []
    for it in (m3.get("involved_knowledge_points") or []):
        if isinstance(it, dict):
            involved.append(it.get("node_id") or it.get("name"))
        else:
            involved.append(str(it))
    for p in m3.get("per_problem") or []:
        for it in (p.get("involved_knowledge_points") or []):
            if isinstance(it, dict):
                involved.append(it.get("node_id") or it.get("name"))
            else:
                involved.append(str(it))
    if not involved and m2.get("problems"):
        for prob in m2["problems"]:
            for it in (prob.get("involved_knowledge_points") or []):
                if isinstance(it, dict):
                    involved.append(it.get("node_id") or it.get("name"))
                else:
                    involved.append(str(it))
    if not involved:
        return

    # 错误知识点（薄弱点 + 各题错误知识点）
    error_kps = set()
    for w in (m3.get("weak_knowledge_points") or []):
        if isinstance(w, dict):
            nid = w.get("node_id")
            if nid:
                error_kps.add(nid)
    # 各题 final_answer.verdict=incorrect → 该题所有知识点算"出错"
    for p in m3.get("per_problem") or []:
        fa = p.get("final_answer") or {}
        verdict = fa.get("verdict") if isinstance(fa, dict) else None
        score = p.get("total_score") or 0
        full = p.get("full_score") or 1
        if verdict == "incorrect" or (verdict is None and score < full * 0.99):
            for k in (p.get("involved_knowledge_points") or []):
                if isinstance(k, dict):
                    nid = k.get("node_id")
                    if nid:
                        error_kps.add(nid)
                else:
                    error_kps.add(str(k))

    from utils.io_helper import now_iso
    now = now_iso()
    seen = set()
    for nid in involved:
        if not nid or nid in seen:
            continue
        seen.add(nid)
        # 取名字
        name = nid
        for w in (m3.get("weak_knowledge_points") or []):
            if isinstance(w, dict) and w.get("node_id") == nid:
                name = w.get("node_name") or nid
                break
        if name == nid:
            for it in (m3.get("involved_knowledge_points") or []):
                if isinstance(it, dict) and it.get("node_id") == nid:
                    name = it.get("node_name") or nid
                    break

        cur.execute("""
            INSERT INTO knowledge_stats (node_id, node_name, total_count, error_count, error_rate, updated_at)
            VALUES (?, ?, 1, ?, ?, ?)
            ON CONFLICT(node_id) DO UPDATE SET
                total_count = total_count + 1,
                error_count = error_count + excluded.error_count,
                error_rate  = (error_count + excluded.error_count) * 1.0 / (total_count + 1),
                updated_at  = excluded.updated_at
        """, (
            nid, name,
            1 if nid in error_kps else 0,
            1.0 if nid in error_kps else 0.0,
            now,
        ))