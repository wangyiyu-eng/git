"""
modules/pipeline.py
流水线整合：image -> M1 -> M2 -> M3 -> 判题结果
"""
import os
import time
from typing import Optional

from modules.m1_feature_extract import extract_features
from modules.m2_semantic_align import align_and_extract
from modules.m3_kg_evaluate import evaluate
from utils.io_helper import (
    image_to_base64, load_image, now_iso, save_json,
)
from utils.logger import get_logger, log_judge


_lg = get_logger("pipeline")


def run_judge(image_path: str = None,
              raw_bytes: bytes = None,
              question_context: str = "",
              full_score: float = None,
              image_name: str = None,
              save_to: Optional[str] = None) -> dict:
    """
    全流程判题入口。
    输入：图片路径或字节（前端上传场景）
    输出：完整判题结果 dict
    """
    import config as app_cfg

    full_score = full_score if full_score is not None else app_cfg.DEFAULT_FULL_SCORE
    t_start = time.time()

    image_id = image_path or "uploaded"
    image_name = image_name or (os.path.basename(image_path) if image_path else "uploaded.jpg")

    # ---- M1 ----
    m1 = extract_features(image_path=image_path, raw_bytes=raw_bytes)

    # ---- M2：可选带图重抽 ----
    image_b64 = None
    image_mime = "image/jpeg"
    if raw_bytes is not None:
        from io import BytesIO
        from PIL import Image
        img = Image.open(BytesIO(raw_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")
        image_b64 = image_to_base64(img)
        image_mime = "image/jpeg"
    elif image_path:
        try:
            img = load_image(image_path)
            image_b64 = image_to_base64(img)
            ext = image_path.lower().split(".")[-1]
            image_mime = "image/png" if ext == "png" else "image/jpeg"
        except Exception as e:
            _lg.warning(f"二次带图失败，继续不带图: {e}")

    m2 = align_and_extract(
        m1_result=m1,
        question_context=question_context,
        image_b64=image_b64,
        image_mime=image_mime,
    )

    # ---- M3 ----
    m3 = evaluate(m2, full_score=full_score)

    # ---- 汇总 ----
    total_ms = int((time.time() - t_start) * 1000)
    err_summary = m2.get("error_summary", {}) or {}
    result = {
        "image_id": m1.get("image_id"),
        "image_name": image_name,
        "created_at": now_iso(),
        "total_latency_ms": total_ms,
        "M1_feature": {
            "raw_text": m1.get("raw_text"),
            "modality_recognition": m1.get("modality_recognition"),
            "cache_hit": m1.get("cache_hit", False),
            "api_latency_ms": m1.get("api_meta", {}).get("latency_ms"),
        },
        "M2_elements": m2,
        "M3_judgment": m3,
    }

    # 日志
    log_judge(image_name, m3["total_score"], m3["full_score"], err_summary, total_ms)

    # 存档（JSON）
    if save_to:
        try:
            save_json(result, save_to)
        except Exception as e:
            _lg.warning(f"保存判题结果失败: {e}")

    # 存档（SQLite，供学情分析页查询）
    try:
        from utils.db_writer import save_record
        rid = save_record(result, full_score_default=full_score)
        if rid > 0:
            result["db_record_id"] = rid
    except Exception as e:
        _lg.warning(f"DB 写入失败（不影响本次判题）: {e}")

    return result


def run_judge_batch(image_paths: list, question_context: str = "",
                    full_score: float = None) -> list:
    """批量判题：逐张走流水线。"""
    results = []
    for p in image_paths:
        try:
            results.append(run_judge(
                image_path=p,
                question_context=question_context,
                full_score=full_score,
                image_name=os.path.basename(p),
            ))
        except Exception as e:
            _lg.error(f"batch judge failed {p}: {e}")
            results.append({"image_name": os.path.basename(p), "error": str(e)})
    return results