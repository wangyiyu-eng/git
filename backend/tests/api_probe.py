"""
tests/api_probe.py
自动探测当前 API 服务商支持的"多模态图片传参格式"。
逐个尝试 [模型 x 格式] 组合，找出能让模型真正看到图片的组合。

用法（在项目根目录）:
  python backend\\tests\\api_probe.py --image backend\\data\\sample_images\\test1.jpg
"""
import argparse
import base64
import json
import os
import sys
import time

# Windows 控制台 GBK 兼容
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(THIS_DIR))

import importlib.util

cfg_path = os.path.join(THIS_DIR, "..", "config.py")
spec = importlib.util.spec_from_file_location("app_config", os.path.abspath(cfg_path))
cfg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cfg)

import requests


def b64_of(path: str) -> str:
    ext = path.lower().split(".")[-1]
    mime = "image/png" if ext == "png" else "image/jpeg"
    with open(path, "rb") as f:
        raw = f.read()
    # 压到较小，避免探测时超时
    from PIL import Image
    from io import BytesIO
    img = Image.open(BytesIO(raw))
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > 800:
        s = 800 / max(w, h)
        img = img.resize((int(w * s), int(h * s)), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode(), "image/jpeg"


# ---- 各种图片传参格式 ----
def content_openai_object(b64, mime):
    """OpenAI 标准: image_url 为对象"""
    return [
        {"type": "text", "text": "图片里写了什么数学式子？只回答式子本身。"},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
    ]


def content_openai_string(b64, mime):
    """变体1: image_url 为字符串"""
    return [
        {"type": "text", "text": "图片里写了什么数学式子？只回答式子本身。"},
        {"type": "image_url", "image_url": f"data:{mime};base64,{b64}"},
    ]


def content_qwen_image(b64, mime):
    """变体2: qwen/dashscope 风格 image 字段"""
    return [
        {"type": "text", "text": "图片里写了什么数学式子？只回答式子本身。"},
        {"image": f"data:{mime};base64,{b64}"},
    ]


def content_raw_url_field(b64, mime):
    """变体3: 顶层 image_url 字符串消息"""
    return [
        {"type": "text", "text": "图片里写了什么数学式子？只回答式子本身。"},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "low"}},
    ]


FORMATS = [
    ("openai-object", content_openai_object),
    ("openai-string", content_openai_string),
    ("qwen-image", content_qwen_image),
    ("openai-detail-low", content_raw_url_field),
]

MODELS = ["deepseek-v4-pro", "deepseek-flash"]

# 判断模型是否"真的看到图片"：回答里应包含数字或数学符号
def looks_like_saw_image(text: str) -> bool:
    if not text:
        return False
    bad = ["未能加载", "无法识别", "不支持", "无法加载", "没有图片", "看不到"]
    if any(b in text for b in bad):
        return False
    return any(c.isdigit() for c in text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True, help="测试图片路径")
    args = ap.parse_args()

    b64, mime = b64_of(args.image)
    url = f"{cfg.DEEPSEEK_API_BASE.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {cfg.DEEPSEEK_API_KEY}", "Content-Type": "application/json"}

    print(f"API Base : {cfg.DEEPSEEK_API_BASE}")
    print(f"测试图片 : {args.image} ({len(b64)//1024} KB base64)")
    print("=" * 60)

    results = []
    for model in MODELS:
        for fname, fn in FORMATS:
            payload = {
                "model": model,
                "temperature": 0.1,
                "max_tokens": 300,
                "messages": [
                    {"role": "user", "content": fn(b64, mime)},
                ],
            }
            tag = f"{model} + {fname}"
            try:
                t0 = time.time()
                r = requests.post(url, headers=headers, json=payload, timeout=45)
                dt = int((time.time() - t0) * 1000)
                if r.status_code != 200:
                    print(f"✗ {tag:40s} HTTP {r.status_code}: {r.text[:120]}")
                    results.append((tag, False, f"HTTP {r.status_code}"))
                    continue
                data = r.json()
                text = data["choices"][0]["message"]["content"]
                ok = looks_like_saw_image(text)
                mark = "✓ 看到图片" if ok else "✗ 没看到图片"
                print(f"{mark} | {tag:35s} ({dt}ms)")
                print(f"    回复: {text[:150]}")
                results.append((tag, ok, text[:80]))
            except Exception as e:
                print(f"✗ {tag:40s} 异常: {e}")
                results.append((tag, False, str(e)))

    print("=" * 60)
    winners = [t for t, ok, _ in results if ok]
    if winners:
        print("\n✅ 可用组合：")
        for w in winners:
            print(f"   {w}")
        print("\n请把 backend/config.py 的 DEEPSEEK_MODEL 改为上面组合中的模型名，")
        print("并告诉我格式名称，我来更新代码。")
    else:
        print("\n❌ 所有组合都失败。可能该 API 服务商不支持图片输入，")
        print("   请把服务商的接口文档发给我，或确认账户是否开通了视觉模型权限。")


if __name__ == "__main__":
    main()