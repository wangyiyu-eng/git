"""
modules/m3_kg_evaluate.py
模块3：解题知识图谱构建与多维度推理评估
  - 把模块2的解题要素映射到 knowledge graph 节点
  - 评估：最终答案对错 + 推理链完整性 + 知识点掌握度
  - 输出多维度判题反馈：总分、扣分点、错误原因、薄弱知识点
"""
from typing import Dict, List

from knowledge.kg_builder import get_kg
from utils.logger import get_logger


_lg = get_logger("m3")


# ---------- 评分权重 ----------
PROCESS_WEIGHT = 0.7   # 过程分占比
FINAL_WEIGHT = 0.3     # 最终答案分占比


def _map_steps_to_nodes(elements: dict, kg) -> List[str]:
    """
    从模块2输出里抽取知识点：
      - 直接用 involved_knowledge_points
      - 再用每个 step 的 content 做模糊匹配补全
    返回去重后的节点 ID 列表。
    """
    candidates = list(elements.get("involved_knowledge_points", []) or [])
    for step in elements.get("steps", []) or []:
        candidates.append(step.get("content", ""))
    return kg.match_knowledge_batch(candidates)


def _compute_process_score(steps: list) -> float:
    """
    过程分：按步骤正确比例计算。
    correct=1, uncertain=0.5, incorrect=0
    """
    if not steps:
        return 0.0
    score_map = {"correct": 1.0, "uncertain": 0.5, "incorrect": 0.0}
    total = 0.0
    for s in steps:
        v = str(s.get("verdict", "uncertain")).lower()
        total += score_map.get(v, 0.5)
    return total / len(steps)


def _evaluate_reasoning_chain(steps: list, kg) -> Dict:
    """
    推理链完整性评估：
      - completeness = 1 - missing/standard_chain_size
      - 列出错误步骤 ID 与原因
    """
    chain = kg.default_chain()
    if not chain:
        return {"completeness": 1.0, "missing_steps": [], "skipped_steps": [], "note": "no default chain"}

    incorrect_ids = [s.get("step_id") for s in steps if str(s.get("verdict", "")).lower() == "incorrect"]
    skipped_ids = []  # 简化：以"步骤 verdict=uncertain 且 result 短"视作跳步
    for s in steps:
        if str(s.get("verdict", "")).lower() == "uncertain" and len(str(s.get("result", ""))) < 2:
            skipped_ids.append(s.get("step_id"))

    # 完整性：步骤通过率
    pass_ratio = sum(1 for s in steps if str(s.get("verdict", "")).lower() == "correct") / max(len(steps), 1)
    completeness = round(pass_ratio, 4)

    return {
        "completeness": completeness,
        "incorrect_step_ids": incorrect_ids,
        "skipped_step_ids": skipped_ids,
        "standard_chain": [kg.get_name(n) for n in chain],
    }


def _compute_mastery(node_id: str, steps: list, kg) -> Dict:
    """
    估算单个知识点的掌握度：
      - 该知识点相关的步骤正确比例
    """
    node_name = kg.get_name(node_id)
    related_steps = []
    for s in steps:
        text = (s.get("content", "") or "") + " " + (s.get("reason", "") or "")
        if node_name in text or node_id in text:
            related_steps.append(s)
        else:
            # 同义词
            for syn in kg.related_synonyms(node_id):
                if syn and syn in text:
                    related_steps.append(s)
                    break

    if not related_steps:
        return {"mastery": 0.5, "sample_size": 0}

    correct = sum(1 for s in related_steps if str(s.get("verdict", "")).lower() == "correct")
    mastery = correct / len(related_steps)
    return {"mastery": round(mastery, 4), "sample_size": len(related_steps)}


def _generate_advice(node_id: str, kg, mastery: float) -> str:
    name = kg.get_name(node_id)
    prereq = kg.prerequisites(node_id)
    prereq_names = [kg.get_name(p) for p in prereq]
    msg = f"知识点【{name}】掌握度约 {mastery*100:.0f}%。"
    if prereq_names:
        msg += f"建议复习先修知识点：{'、'.join(prereq_names)}。"
    else:
        msg += "建议多做相关练习巩固。"
    return msg


def evaluate(m2_result: dict, full_score: float = None) -> dict:
    """
    模块3主函数：基于知识图谱的多维度推理评估。
    支持两种输入：
      - 单题要素 dict（原逻辑）
      - 多题合并 dict（m2_result["multi_problem"]=True，逐题打分后汇总）
    """
    import config as app_cfg
    full_score = full_score if full_score is not None else app_cfg.DEFAULT_FULL_SCORE

    if m2_result.get("multi_problem") and m2_result.get("problems"):
        return _evaluate_multi(m2_result, full_score)
    return _evaluate_single(m2_result, full_score)


def _evaluate_single(m2_result: dict, full_score: float) -> dict:
    """单题评估（原 evaluate 核心逻辑）。"""
    kg = get_kg()
    steps = m2_result.get("steps", []) or []

    # 1. 过程分与最终答案分
    process_ratio = _compute_process_score(steps)
    final_verdict = str(m2_result.get("final_answer", {}).get("verdict", "uncertain")).lower()
    final_ratio = 1.0 if final_verdict == "correct" else (0.0 if final_verdict == "incorrect" else 0.5)

    total_score = round(full_score * (process_ratio * PROCESS_WEIGHT + final_ratio * FINAL_WEIGHT), 2)

    # 2. 扣分明细
    breakdown = []
    breakdown.append({
        "item": "解题过程", "full": round(full_score * PROCESS_WEIGHT, 2),
        "got": round(full_score * process_ratio * PROCESS_WEIGHT, 2),
        "reason": f"共 {len(steps)} 步，正确比例 {process_ratio*100:.1f}%",
    })
    breakdown.append({
        "item": "最终答案", "full": round(full_score * FINAL_WEIGHT, 2),
        "got": round(full_score * final_ratio * FINAL_WEIGHT, 2),
        "reason": "答案正确" if final_verdict == "correct" else
                  "答案错误" if final_verdict == "incorrect" else "无法判定",
    })

    # 3. 推理链完整性
    chain_eval = _evaluate_reasoning_chain(steps, kg)

    # 4. 知识点映射 + 薄弱知识点
    involved_nodes = _map_steps_to_nodes(m2_result, kg)
    weak_nodes = []
    for nid in involved_nodes:
        m_info = _compute_mastery(nid, steps, kg)
        mastery = m_info["mastery"]
        if mastery < 0.7:  # 阈值：掌握度不足 = 薄弱
            weak_nodes.append({
                "node_id": nid,
                "node_name": kg.get_name(nid),
                "mastery": mastery,
                "sample_size": m_info["sample_size"],
                "advice": _generate_advice(nid, kg, mastery),
            })

    # 5. 错误原因汇总
    err_summary = m2_result.get("error_summary") or {}
    error_reasons = []
    if err_summary.get("logic_gap", 0) > 0:
        error_reasons.append(f"存在 {err_summary['logic_gap']} 处逻辑漏洞/跳步")
    if err_summary.get("calculation_error", 0) > 0:
        error_reasons.append(f"存在 {err_summary['calculation_error']} 处计算错误")
    if err_summary.get("concept_error", 0) > 0:
        error_reasons.append(f"存在 {err_summary['concept_error']} 处概念/原理错误")

    # 6. 学生反馈（自然语言）
    feedback_lines = []
    if total_score >= full_score * 0.85:
        feedback_lines.append("表现优秀，解题思路清晰。")
    elif total_score >= full_score * 0.6:
        feedback_lines.append("总体掌握尚可，但仍有改进空间。")
    else:
        feedback_lines.append("本次表现较弱，建议系统复习相关内容。")

    if error_reasons:
        feedback_lines.append("主要问题：" + "；".join(error_reasons) + "。")
    if weak_nodes:
        weak_str = "、".join(w["node_name"] for w in weak_nodes[:3])
        feedback_lines.append(f"薄弱知识点：{weak_str}。")
        advice_str = " ".join(w["advice"] for w in weak_nodes[:2])
        feedback_lines.append(advice_str)
    feedback_lines.append("继续加油！")

    return {
        "image_id": m2_result.get("image_id"),
        "total_score": total_score,
        "full_score": full_score,
        "score_breakdown": breakdown,
        "reasoning_chain": chain_eval,
        "involved_knowledge_points": [
            {"node_id": nid, "node_name": kg.get_name(nid)} for nid in involved_nodes
        ],
        "weak_knowledge_points": weak_nodes,
        "error_reasons": error_reasons,
        "error_summary": err_summary,
        "feedback": "".join(feedback_lines),
    }


def _evaluate_multi(m2_result: dict, full_score: float) -> dict:
    """
    多题页面评估：full_score 是"每题满分"（由前端语义决定），
    每道题独立评估，各自拥有 过程分 + 答案分。
      - 总分 = 各题得分之和（满分 = 每题满分 × 题数）
      - 判分明细：每题两行（解题过程 / 最终答案）
      - 薄弱知识点：跨题去重合并（保留最低掌握度）
    """
    problems = m2_result.get("problems", []) or []
    n = len(problems)

    singles = []
    for p in problems:
        r = _evaluate_single(p, full_score)  # 每题都按"每题满分"评
        r["problem_index"] = p.get("problem_index", len(singles) + 1)
        singles.append(r)

    total_score = round(sum(r["total_score"] for r in singles), 2)
    total_full = round(full_score * n, 2)

    # 判分明细：每题两行（过程分 + 答案分），互不混合
    breakdown = []
    for r in singles:
        by_item = {b["item"]: b for b in r["score_breakdown"]}
        proc = by_item.get("解题过程", {})
        final = by_item.get("最终答案", {})
        breakdown.append({
            "item": f"第{r['problem_index']}题·解题过程",
            "full": proc.get("full", round(full_score * PROCESS_WEIGHT, 2)),
            "got": proc.get("got", 0),
            "reason": proc.get("reason", ""),
        })
        breakdown.append({
            "item": f"第{r['problem_index']}题·最终答案",
            "full": final.get("full", round(full_score * FINAL_WEIGHT, 2)),
            "got": final.get("got", 0),
            "reason": final.get("reason", ""),
        })

    # 推理链完整度：各题平均
    completeness = round(sum(r["reasoning_chain"]["completeness"] for r in singles) / n, 4)
    chain_eval = {
        "completeness": completeness,
        "incorrect_step_ids": [i for r in singles for i in r["reasoning_chain"].get("incorrect_step_ids", [])],
        "skipped_step_ids": [i for r in singles for i in r["reasoning_chain"].get("skipped_step_ids", [])],
        "note": f"共 {n} 道题，完整度为各题平均值",
    }

    # 知识点跨题合并
    involved_map = {}
    for r in singles:
        for it in r["involved_knowledge_points"]:
            involved_map[it["node_id"]] = it["node_name"]
    # 薄弱知识点：同节点保留最低掌握度
    weak_map = {}
    for r in singles:
        for w in r["weak_knowledge_points"]:
            old = weak_map.get(w["node_id"])
            if old is None or w["mastery"] < old["mastery"]:
                weak_map[w["node_id"]] = w

    # 错误汇总
    err_summary = {"logic_gap": 0, "calculation_error": 0, "concept_error": 0}
    for r in singles:
        for k in err_summary:
            err_summary[k] += (r.get("error_summary") or {}).get(k, 0) or 0
    error_reasons = []
    if err_summary.get("logic_gap", 0) > 0:
        error_reasons.append(f"存在 {err_summary['logic_gap']} 处逻辑漏洞/跳步")
    if err_summary.get("calculation_error", 0) > 0:
        error_reasons.append(f"存在 {err_summary['calculation_error']} 处计算错误")
    if err_summary.get("concept_error", 0) > 0:
        error_reasons.append(f"存在 {err_summary['concept_error']} 处概念/原理错误")

    # 反馈
    full_score_count = sum(1 for r in singles if r["total_score"] >= full_score * 0.99)
    feedback_lines = [f"本页共 {n} 道题（每题满分 {full_score:g} 分），其中 {full_score_count} 道得满分。"]
    if error_reasons:
        feedback_lines.append("主要问题：" + "；".join(error_reasons) + "。")
    if weak_map:
        weak_str = "、".join(w["node_name"] for w in list(weak_map.values())[:3])
        feedback_lines.append(f"薄弱知识点：{weak_str}。")
        advice_str = " ".join(w["advice"] for w in list(weak_map.values())[:2])
        feedback_lines.append(advice_str)
    if total_score >= total_full * 0.85:
        feedback_lines.append("整体表现优秀，继续加油！")
    elif total_score >= total_full * 0.6:
        feedback_lines.append("整体掌握尚可，注意错题订正。继续加油！")
    else:
        feedback_lines.append("整体较弱，建议逐题复习错因。继续加油！")

    return {
        "image_id": m2_result.get("image_id"),
        "multi_problem": True,
        "problem_count": n,
        "per_problem": singles,
        "total_score": total_score,
        "full_score": total_full,
        "score_breakdown": breakdown,
        "reasoning_chain": chain_eval,
        "involved_knowledge_points": [
            {"node_id": k, "node_name": v} for k, v in involved_map.items()
        ],
        "weak_knowledge_points": list(weak_map.values()),
        "error_reasons": error_reasons,
        "error_summary": err_summary,
        "feedback": "".join(feedback_lines),
    }