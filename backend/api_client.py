"""
api_client.py
DeepSeek-Vision API 请求封装：
  - 单/多模态消息组装
  - 超时重试（指数退避）
  - 异常捕获与日志
  - 原始响应存档（便于论文分析）
"""
import importlib.util
import json
import os
import time
from typing import List, Optional

import requests


def _load_config():
    cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.py")
    spec = importlib.util.spec_from_file_location("app_config", cfg_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_CONFIG = _load_config()


# 让 logger 模块懒加载避免循环
def _lg():
    from utils.logger import get_logger
    return get_logger()


class DeepSeekVisionError(Exception):
    """API 调用业务异常。"""
    pass


# HTTP 状态码 → (是否可重试, 人话说明)
# 不可重试的错误重试 3 次只会白等几分钟，必须立刻失败并给出明确原因
_HTTP_ERROR_MAP = {
    401: (False, "API Key 无效或未配置（检查 backend/config.py 的 DEEPSEEK_API_KEY）"),
    402: (False, "账户余额不足，请到 DeepSeek 平台充值"),
    403: (False, "无权访问该模型（检查账号权限或模型名是否正确）"),
    404: (False, "接口地址或模型名不存在（检查 DEEPSEEK_API_BASE / DEEPSEEK_MODEL）"),
    413: (False, "图片太大（建议压缩到 2MB 以内）"),
    422: (False, "请求体格式错误（图片 base64 可能损坏）"),
    429: (True,  "请求过于频繁（触发限流），稍后自动重试"),
    500: (True,  "服务端内部错误，稍后自动重试"),
    502: (True,  "服务端网关错误，稍后自动重试"),
    503: (True,  "服务暂不可用，稍后自动重试"),
    504: (True,  "服务端超时，稍后自动重试"),
}


def _archive_raw(payload: dict, response: dict, image_id: str, model: str):
    """把每次调用的请求体与原始响应存档到 raw_responses/。"""
    os.makedirs(_CONFIG.RAW_DIR, exist_ok=True)
    fname = f"{int(time.time()*1000)}_{image_id[:10]}_{model.replace('/', '_')}.json"
    path = os.path.join(_CONFIG.RAW_DIR, fname)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"request": payload, "response": response}, f, ensure_ascii=False, indent=2)


def call_vision(
    user_text: str,
    image_b64: str,
    system_text: str = "",
    image_id: str = "image",
    image_url_mime: str = "image/jpeg",
    extra_payload: Optional[dict] = None,
) -> dict:
    """
    调用 DeepSeek-Vision 通用对话。
    参数：
      user_text: 用户提示词
      image_b64: 图片 base64
      system_text: 系统提示词（可空）
      image_id: 用于归档命名
      image_url_mime: 图片 MIME
      extra_payload: 额外覆盖字段（按需使用）
    返回：
      API 返回的完整 dict（含 choices 等）
    """
    # 前置检查：API Key 未配置时直接给出明确提示，
    # 避免把 Key 为空的请求发到服务端、最后只拿到一个难懂的 401
    key = (_CONFIG.DEEPSEEK_API_KEY or "").strip()
    if not key or key.startswith("sk-xxx"):
        raise DeepSeekVisionError(
            "未配置 API Key：请设置环境变量 DEEPSEEK_API_KEY，"
            "或编辑 backend/config.py 填入真实 Key（参考 backend/config.example.py）。"
        )

    url = f"{_CONFIG.DEEPSEEK_API_BASE.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": _CONFIG.DEEPSEEK_MODEL,
        "temperature": _CONFIG.TEMPERATURE,
        "max_tokens": _CONFIG.MAX_TOKENS,
        "messages": [
            {"role": "system", "content": system_text or "你是答卷识别与分析专家。"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{image_url_mime};base64,{image_b64}"
                        },
                    },
                ],
            },
        ],
    }
    if extra_payload:
        payload.update(extra_payload)

    last_err = None
    for attempt in range(1, _CONFIG.MAX_RETRIES + 1):
        try:
            t0 = time.time()
            resp = requests.post(
                url, headers=headers, json=payload, timeout=_CONFIG.REQUEST_TIMEOUT
            )
            latency_ms = int((time.time() - t0) * 1000)
            if resp.status_code != 200:
                code = resp.status_code
                retryable, hint = _HTTP_ERROR_MAP.get(code, (True, ""))
                last_err = f"HTTP {code}: {resp.text[:300]}" if not hint else f"HTTP {code} {hint}"
                _lg().warning(f"[API] attempt {attempt} failed: {last_err}")
                # 不可重试错误（Key 无效/余额不足等）→ 立刻失败，不再浪费重试时间
                if not retryable:
                    raise DeepSeekVisionError(f"DeepSeek-Vision 调用失败（不可自动恢复）: {last_err}")
                time.sleep(_CONFIG.RETRY_BACKOFF ** attempt)
                continue

            data = resp.json()
            data.setdefault("_meta", {})
            data["_meta"]["latency_ms"] = latency_ms
            data["_meta"]["model"] = _CONFIG.DEEPSEEK_MODEL

            # 存档原始响应
            try:
                _archive_raw(payload, data, image_id, _CONFIG.DEEPSEEK_MODEL)
            except Exception as e:
                _lg().warning(f"[API] archive raw failed: {e}")

            return data

        except requests.exceptions.Timeout as e:
            last_err = f"timeout: {e}"
            _lg().warning(f"[API] attempt {attempt} timeout")
        except Exception as e:
            last_err = f"error: {e}"
            _lg().warning(f"[API] attempt {attempt} exception: {e}")

        time.sleep(_CONFIG.RETRY_BACKOFF ** attempt)

    raise DeepSeekVisionError(f"DeepSeek-Vision 调用失败（{_CONFIG.MAX_RETRIES} 次重试后）: {last_err}")


def extract_content(response: dict) -> str:
    """从 API 返回中抽取 assistant 文本内容。"""
    try:
        return response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return ""


def safe_json_parse(content: str) -> dict:
    """
    模型有时会在 JSON 外面包 ```json ... ```。这里尽量宽容解析。
    解析失败返回空 dict，由业务层决定重试或兜底。
    """
    if not content:
        return {}
    s = content.strip()
    # 去掉 markdown 代码块
    if s.startswith("```"):
        s = s.strip("`")
        # 去掉可能的 json 标记
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.strip()
    # 找到第一个 { 和最后一个 }
    try:
        start = s.index("{")
        end = s.rindex("}")
        s = s[start:end + 1]
        return json.loads(s)
    except (ValueError, json.JSONDecodeError):
        return {}