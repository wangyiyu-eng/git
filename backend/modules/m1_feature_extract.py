"""
modules/m1_feature_extract.py
模块1：答卷多模态特征提取
  - 加载增强后的答卷图片
  - Base64 编码
  - 调用 DeepSeek-Vision 识别手写文本/公式/图表/代码
  - 原始结果存档 + 缓存

输入: image_path 或 (image_path, image_id)
输出: dict, 含 modality_recognition / raw_text / api_meta
"""
from typing import Optional

from api_client import call_vision, extract_content, safe_json_parse
from prompts.prompt_templates import (
    PROMPT_VERSION, SYSTEM_PROMPT_M1, USER_PROMPT_M1,
)
from utils.cache import get as _cache_get, set as _cache_set
from utils.io_helper import (
    bytes_md5, file_md5, image_to_base64, load_image, save_json,
)
from utils.logger import get_logger


_lg = get_logger("m1")


def _identify_image_id(image_path: Optional[str] = None, raw_bytes: Optional[bytes] = None) -> str:
    if raw_bytes is not None:
        return bytes_md5(raw_bytes)
    if image_path is not None:
        return file_md5(image_path)
    raise ValueError("必须提供 image_path 或 raw_bytes")


def extract_features(image_path: str = None,
                     raw_bytes: bytes = None,
                     image_id: str = None,
                     use_cache: bool = True) -> dict:
    """
    模块1主函数：识别答卷多模态特征。
    返回 dict，包含 modality_recognition / raw_text / api_meta。
    """
    # 1. 生成 image_id 与缓存键
    if image_id is None:
        image_id = _identify_image_id(image_path, raw_bytes)

    cache_key_extra = ""
    if use_cache:
        hit = _cache_get(image_id, PROMPT_VERSION, cache_key_extra)
        if hit is not None:
            _lg.info(f"[M1] cache HIT id={image_id}")
            hit["cache_hit"] = True
            return hit

    # 2. 编码图片
    if raw_bytes is not None:
        from io import BytesIO
        from PIL import Image
        img = Image.open(BytesIO(raw_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")
        b64 = image_to_base64(img)
        mime = "image/jpeg"
    else:
        img = load_image(image_path)
        b64 = image_to_base64(img)
        ext = image_path.lower().split(".")[-1]
        mime = "image/png" if ext == "png" else "image/jpeg"

    # 3. 调用 DeepSeek-Vision
    _lg.info(f"[M1] call DeepSeek-Vision id={image_id}")
    resp = call_vision(
        user_text=USER_PROMPT_M1,
        image_b64=b64,
        system_text=SYSTEM_PROMPT_M1,
        image_id=image_id,
        image_url_mime=mime,
    )
    content = extract_content(resp)
    parsed = safe_json_parse(content)

    # 4. 组装结构化结果
    result = {
        "image_id": image_id,
        "raw_text": parsed.get("raw_text") or content,
        "modality_recognition": parsed.get("modality_recognition", {
            "handwritten_text": [],
            "formulas": [],
            "charts": [],
            "code_snippets": [],
        }),
        "notes": parsed.get("notes", ""),
        "api_meta": resp.get("_meta", {}),
        "cache_hit": False,
    }

    # 5. 写缓存
    if use_cache:
        _cache_set(image_id, PROMPT_VERSION, result, cache_key_extra)

    return result


def extract_features_batch(image_paths: list, use_cache: bool = True) -> list:
    """批量调用，逐张返回结果。"""
    results = []
    for p in image_paths:
        try:
            results.append(extract_features(image_path=p, use_cache=use_cache))
        except Exception as e:
            _lg.error(f"[M1] batch fail {p}: {e}")
            results.append({"image_path": p, "error": str(e)})
    return results