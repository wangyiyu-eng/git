"""
utils/cache.py
基于"图片内容 MD5 + 提示词版本"的简单 JSON 缓存。
避免对同一张答卷重复调用 API，节省成本与时间（轻量化策略之一）。
"""
import hashlib
import importlib.util
import json
import os

from .io_helper import save_json, load_json


def _load_config():
    cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.py")
    spec = importlib.util.spec_from_file_location("app_config", cfg_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_CONFIG = _load_config()


def _cache_key(image_md5: str, prompt_version: str, extra: str = "") -> str:
    raw = f"{image_md5}|{prompt_version}|{extra}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _cache_path(key: str) -> str:
    return os.path.join(_CONFIG.CACHE_DIR, f"{key}.json")


def get(image_md5: str, prompt_version: str, extra: str = "") -> dict:
    """命中则返回字典，未命中返回 None。"""
    if not _CONFIG.CACHE_ENABLED:
        return None
    p = _cache_path(_cache_key(image_md5, prompt_version, extra))
    if os.path.exists(p):
        try:
            return load_json(p)
        except Exception:
            return None
    return None


def set(image_md5: str, prompt_version: str, data: dict, extra: str = ""):
    if not _CONFIG.CACHE_ENABLED:
        return
    p = _cache_path(_cache_key(image_md5, prompt_version, extra))
    save_json(data, p)


def clear_all():
    if os.path.isdir(_CONFIG.CACHE_DIR):
        for f in os.listdir(_CONFIG.CACHE_DIR):
            if f.endswith(".json"):
                os.remove(os.path.join(_CONFIG.CACHE_DIR, f))