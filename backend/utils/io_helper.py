"""
utils/io_helper.py
图片 IO 工具：图片加载、Base64 编码、JSON/CSV 读写、文件哈希。
"""
import base64
import csv
import hashlib
import json
import os
from io import BytesIO
from typing import Any, List

from PIL import Image


# ---------- 图片相关 ----------
def load_image(image_path: str) -> Image.Image:
    """
    加载答卷图片。仅支持 jpg/png，其它格式抛异常。
    返回 Pillow Image 对象（RGB 模式）。
    """
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"图片不存在: {image_path}")
    ext = os.path.splitext(image_path)[1].lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
        raise ValueError(f"不支持的图片格式: {ext}")

    img = Image.open(image_path)
    # 部分 PNG 含 alpha 通道，转 RGB
    if img.mode != "RGB":
        img = img.convert("RGB")
    return img


def image_to_base64(img: Image.Image, format: str = "JPEG", max_side: int = 1600) -> str:
    """
    图片 -> Base64 字符串。过大图片自动按比例缩放（防止超过 API 限制）。
    """
    img = img.copy()
    # 限制最大边长，节省 token / 加快上传
    w, h = img.size
    if max(w, h) > max_side:
        scale = max_side / float(max(w, h))
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format=format, quality=90)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def image_bytes_to_base64(raw_bytes: bytes, format: str = "JPEG") -> str:
    """直接对已读取的字节做 Base64（前端上传后端保存的场景）。"""
    return base64.b64encode(raw_bytes).decode("utf-8")


def file_md5(path: str) -> str:
    """计算文件 MD5，用作缓存键与文件名。"""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def bytes_md5(raw: bytes) -> str:
    return hashlib.md5(raw).hexdigest()


# ---------- JSON / CSV 读写 ----------
def save_json(data: Any, path: str, ensure_dir: bool = True):
    if ensure_dir:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_csv(rows: List[dict], path: str, fieldnames: List[str] = None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not rows:
        return
    if fieldnames is None:
        fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            # 自动把 list/dict 序列化为字符串，避免 CSV 报错
            safe = {}
            for k, v in row.items():
                if isinstance(v, (list, dict)):
                    safe[k] = json.dumps(v, ensure_ascii=False)
                else:
                    safe[k] = v
            writer.writerow(safe)


def now_iso() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")