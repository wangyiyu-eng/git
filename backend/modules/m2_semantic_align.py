"""
modules/m2_semantic_align.py
模块2：跨模态语义对齐与解题要素抽取
  - 以识别内容（模块1输出）为输入
  - 通过精心设计的提示词让 DeepSeek-Vision 直接抽取结构化解题要素
  - 自动区分错误类型：逻辑漏洞 / 计算错误 / 概念错误
  - 支持多题页面：先拆分题目，再逐题抽取（并行），最后合并
  - 解析失败时自动重试；完全失败给出降级默认结构
"""
import hashlib
import importlib.util
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

import requests

from api_client import extract_content, safe_json_parse
from prompts.prompt_templates import (
    PROMPT_VERSION, SYSTEM_PROMPT_M2, USER_PROMPT_M2,
)
from utils.cache import get as _cache_get, set as _cache_set
from utils.logger import get_logger


_lg = get_logger("m2")

# 单张答卷最多拆分的题目数（防止异常拆分导致请求爆炸）
MAX_PROBLEMS = 10


def _load_config():
    cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.py")
    spec = importlib.util.spec_from_file_location("app_config", cfg_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_CFG = _load_config()


# ---------- 多题拆分提示词（纯文本调用，消耗小） ----------
SPLIT_SYSTEM_PROMPT = "你是试卷结构分析助手。只输出 JSON，不要输出任何其他内容。"
SPLIT_USER_PROMPT = """下面是一张答卷图片的OCR识别文本。请判断其中包含几道独立的题目，并把每道题的作答内容完整拆分出来。

要求：
1. 按题号（如 (1)(2)(3)、1. 2.、第X题）或明显的"解："分隔拆分；
2. 每道题保留原文，不要改写、不要解题、不要遗漏；
3. 如果整页只有一道题，problems 数组只放一个元素（整段文本）；
4. 只输出 JSON，格式：{{"problem_count": 题目数, "problems": ["第1题原文", "第2题原文", ...]}}

识别文本：
{raw_text}"""


def _md5_16(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:16]


def _build_user_prompt(recognized: dict, question_context: str = "") -> str:
    """组装模块2 user prompt，把识别内容插入模板。"""
    rec_lines = []
    mr = recognized.get("modality_recognition", {})
    if mr.get("handwritten_text"):
        rec_lines.append("[手写文本]")
        rec_lines.extend(f"- {x}" for x in mr["handwritten_text"])
    if mr.get("formulas"):
        rec_lines.append("[数学公式]")
        rec_lines.extend(f"- {x}" for x in mr["formulas"])
    if mr.get("charts"):
        rec_lines.append("[答题图表]")
        rec_lines.extend(f"- {x}" for x in mr["charts"])
    if mr.get("code_snippets"):
        rec_lines.append("[简易代码]")
        rec_lines.extend(f"- {x}" for x in mr["code_snippets"])
    if not rec_lines:
        rec_lines.append("（无可结构化识别项）")
    rec_lines.append("\n[完整识别文本]\n" + (recognized.get("raw_text") or ""))
    recognized_content = "\n".join(rec_lines)

    qctx = question_context.strip() if question_context else "（无额外参考信息）"
    return USER_PROMPT_M2.format(
        recognized_content=recognized_content,
        question_context=qctx,
    )


def _looks_multi_problem(raw_text: str) -> bool:
    """
    启发式判断识别文本是否可能包含多道题：
    统计强题号标记 (1) （2） 1. 第X题 等出现次数，>=2 才触发拆分调用。
    避免单题页面白白多花一次拆分请求。
    """
    if not raw_text:
        return False
    patterns = [
        r'（\s*\d+\s*）', r'\(\s*\d+\s*\)',
        r'第\s*[一二三四五六七八九十\d]+\s*题',
        r'(?:^|\n)\s*\d{1,2}\s*[\.、]',
    ]
    total = 0
    for p in patterns:
        total += len(re.findall(p, raw_text))
    return total >= 2


def _split_problems(raw_text: str, use_cache: bool = True) -> Optional[List[str]]:
    """
    调用 API 把一页多题的识别文本拆分成单题文本列表。
    纯文本调用（不带图），消耗小；结果按 raw_text 哈希缓存。
    失败返回 None（调用方回退到单题路径）。
    """
    key = _md5_16("split|" + raw_text)
    if use_cache:
        hit = _cache_get("split", PROMPT_VERSION, key)
        if hit is not None:
            return hit

    url = f"{_CFG.DEEPSEEK_API_BASE.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {_CFG.DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": _CFG.DEEPSEEK_MODEL,
        "temperature": 0,
        "max_tokens": 2048,
        "messages": [
            {"role": "system", "content": SPLIT_SYSTEM_PROMPT},
            {"role": "user", "content": SPLIT_USER_PROMPT.format(raw_text=raw_text)},
        ],
    }
    for attempt in range(1, _CFG.MAX_RETRIES + 1):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=_CFG.REQUEST_TIMEOUT)
            if resp.status_code != 200:
                _lg.warning(f"[M2-split] attempt {attempt} HTTP {resp.status_code}")
                time.sleep(_CFG.RETRY_BACKOFF ** attempt)
                continue
            parsed = safe_json_parse(extract_content(resp.json()))
            segs = parsed.get("problems") if isinstance(parsed, dict) else None
            if isinstance(segs, list) and segs and all(isinstance(s, str) and s.strip() for s in segs):
                segs = [s.strip() for s in segs][:MAX_PROBLEMS]
                if use_cache:
                    _cache_set("split", PROMPT_VERSION, segs, key)
                _lg.info(f"[M2-split] 拆分得到 {len(segs)} 道题")
                return segs
            _lg.warning(f"[M2-split] attempt {attempt} 拆分结果无效")
        except Exception as e:
            _lg.warning(f"[M2-split] attempt {attempt} exception: {e}")
            time.sleep(_CFG.RETRY_BACKOFF ** attempt)
    return None


def _call_extraction(user_prompt: str,
                     image_b64: Optional[str],
                     image_mime: str,
                     cache_id: str,
                     extra_str: str,
                     use_cache: bool) -> dict:
    """
    核心：单次"解题要素抽取"API 调用（含重试与缓存）。
    单题与多题逐题抽取共用此函数。
    """
    if use_cache:
        hit = _cache_get(cache_id, PROMPT_VERSION, extra_str)
        if hit is not None:
            _lg.info(f"[M2] cache HIT id={cache_id}")
            hit["cache_hit"] = True
            return hit

    url = f"{_CFG.DEEPSEEK_API_BASE.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {_CFG.DEEPSEEK_API_KEY}", "Content-Type": "application/json"}

    content_parts = [{"type": "text", "text": user_prompt}]
    if image_b64:
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:{image_mime};base64,{image_b64}"},
        })

    payload = {
        "model": _CFG.DEEPSEEK_MODEL,
        "temperature": _CFG.TEMPERATURE,
        "max_tokens": _CFG.MAX_TOKENS,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT_M2},
            {"role": "user", "content": content_parts},
        ],
    }

    last_err = None
    for attempt in range(1, _CFG.MAX_RETRIES + 1):
        try:
            t0 = time.time()
            resp = requests.post(url, headers=headers, json=payload, timeout=_CFG.REQUEST_TIMEOUT)
            latency_ms = int((time.time() - t0) * 1000)
            if resp.status_code != 200:
                last_err = f"HTTP {resp.status_code}: {resp.text[:300]}"
                _lg.warning(f"[M2] attempt {attempt} HTTP fail: {last_err}")
                time.sleep(_CFG.RETRY_BACKOFF ** attempt)
                continue
            data = resp.json()
            content = extract_content(data)
            parsed = safe_json_parse(content)
            if not parsed:
                last_err = "JSON 解析失败"
                _lg.warning(f"[M2] attempt {attempt} parse fail: {content[:200]}")
                time.sleep(_CFG.RETRY_BACKOFF ** attempt)
                continue

            # 兜底：保证必要字段
            parsed.setdefault("known_conditions", [])
            parsed.setdefault("steps", [])
            parsed.setdefault("final_answer", {"value": "", "verdict": "uncertain"})
            parsed.setdefault("error_summary",
                              {"logic_gap": 0, "calculation_error": 0, "concept_error": 0})
            parsed.setdefault("involved_knowledge_points", [])
            parsed.setdefault("standard_reasoning_chain", "")

            parsed["cache_hit"] = False
            parsed["api_meta"] = {"latency_ms": latency_ms, "model": _CFG.DEEPSEEK_MODEL}

            # 写缓存（保护：空结果不缓存，避免坏结果被长期复用）
            is_empty = (not parsed["steps"]) and parsed["final_answer"].get("verdict") == "uncertain"
            if use_cache and not is_empty:
                _cache_set(cache_id, PROMPT_VERSION, parsed, extra_str)
            elif is_empty:
                _lg.warning(f"[M2] 结果为空，不写缓存 id={cache_id}")

            return parsed

        except requests.exceptions.Timeout as e:
            last_err = f"timeout: {e}"
            _lg.warning(f"[M2] attempt {attempt} timeout")
        except Exception as e:
            last_err = f"error: {e}"
            _lg.warning(f"[M2] attempt {attempt} exception: {e}")
        time.sleep(_CFG.RETRY_BACKOFF ** attempt)

    _lg.error(f"[M2] all retries failed id={cache_id}: {last_err}")
    return {
        "known_conditions": [],
        "steps": [],
        "final_answer": {"value": "", "verdict": "uncertain"},
        "error_summary": {"logic_gap": 0, "calculation_error": 0, "concept_error": 0},
        "involved_knowledge_points": [],
        "standard_reasoning_chain": "",
        "cache_hit": False,
        "_error": str(last_err),
    }


def _flatten_problems(problems: List[dict], image_id: str) -> dict:
    """
    把逐题抽取结果合并为兼容单题结构的 dict：
      - steps 加上【第k题】前缀扁平合并（前端/M3 无需大改即可展示）
      - final_answer / error_summary / 知识点 做汇总
      - 同时保留 problems 列表供模块3逐题打分
    """
    flat = {
        "image_id": image_id,
        "multi_problem": True,
        "problem_count": len(problems),
        "problems": problems,
        "known_conditions": [],
        "steps": [],
        "final_answer": {"value": "", "verdict": "correct"},
        "error_summary": {"logic_gap": 0, "calculation_error": 0, "concept_error": 0},
        "involved_knowledge_points": [],
        "standard_reasoning_chain": "",
        "cache_hit": False,
    }
    verdicts = []
    for p in problems:
        idx = p.get("problem_index", 0)
        flat["known_conditions"] += p.get("known_conditions", []) or []
        for s in p.get("steps", []) or []:
            s2 = dict(s)
            s2["content"] = f"【第{idx}题】{s.get('content', '')}"
            flat["steps"].append(s2)
        fa = p.get("final_answer", {}) or {}
        verdicts.append(str(fa.get("verdict", "uncertain")).lower())
        val = str(fa.get("value", "")).strip()
        if val:
            flat["final_answer"]["value"] += f"第{idx}题: {val}；"
        for k in flat["error_summary"]:
            flat["error_summary"][k] += (p.get("error_summary") or {}).get(k, 0) or 0
        for kp in p.get("involved_knowledge_points", []) or []:
            if kp not in flat["involved_knowledge_points"]:
                flat["involved_knowledge_points"].append(kp)
        if p.get("standard_reasoning_chain"):
            flat["standard_reasoning_chain"] += f"第{idx}题：{p['standard_reasoning_chain']} "
    # 整页最终答案判定：全部对才算对，任一错即错
    if any(v == "incorrect" for v in verdicts):
        flat["final_answer"]["verdict"] = "incorrect"
    elif all(v == "correct" for v in verdicts):
        flat["final_answer"]["verdict"] = "correct"
    else:
        flat["final_answer"]["verdict"] = "uncertain"
    return flat


def align_and_extract(m1_result: dict,
                      question_context: str = "",
                      image_b64: Optional[str] = None,
                      image_mime: str = "image/jpeg",
                      use_cache: bool = True) -> dict:
    """
    模块2主函数。
    流程：
      1. 整体结果缓存命中 → 直接返回
      2. 启发式判断是否多题页面 → 是则拆分后逐题抽取（并行）并合并
      3. 否则走单题抽取
    """
    image_id = m1_result.get("image_id", "unknown")
    raw_text = m1_result.get("raw_text", "") or ""
    # 缓存键需包含：题目上下文 + 识别文本的哈希（识别结果变了 M2 要重跑）
    extra_str = _md5_16(f"{question_context}|{raw_text}")

    if use_cache:
        hit = _cache_get(image_id, PROMPT_VERSION, extra_str)
        if hit is not None:
            _lg.info(f"[M2] cache HIT id={image_id}")
            hit["cache_hit"] = True
            return hit

    # ---- 多题路径 ----
    if _looks_multi_problem(raw_text):
        segs = _split_problems(raw_text, use_cache)
        if segs and len(segs) >= 2:
            _lg.info(f"[M2] 多题页面：拆分为 {len(segs)} 道题，逐题抽取")

            def _work(i_seg):
                i, seg = i_seg
                pseudo = {"raw_text": seg, "modality_recognition": {}}
                up = _build_user_prompt(pseudo, question_context)
                el = _call_extraction(up, None, image_mime,
                                      f"{image_id[:8]}_p{i+1}", _md5_16(seg), use_cache)
                el["image_id"] = f"{image_id[:8]}_p{i+1}"
                el["problem_index"] = i + 1
                el["problem_text"] = seg[:100]
                return el

            with ThreadPoolExecutor(max_workers=min(4, len(segs))) as ex:
                problems = list(ex.map(_work, enumerate(segs)))
            problems.sort(key=lambda p: p["problem_index"])
            return _flatten_problems(problems, image_id)

    # ---- 单题路径 ----
    user_prompt = _build_user_prompt(m1_result, question_context)
    parsed = _call_extraction(user_prompt, image_b64, image_mime, image_id, extra_str, use_cache)
    parsed["image_id"] = image_id
    return parsed
