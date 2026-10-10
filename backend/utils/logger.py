"""
utils/logger.py
统一日志模块：每次判题都记录时间、图片名、总分、错误类型，便于毕设实验分析。
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

# 读取 config（注意：config 模块名会与 stdlib 冲突，使用 importlib）
def _load_config():
    import importlib.util
    cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.py")
    spec = importlib.util.spec_from_file_location("app_config", cfg_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_CONFIG = _load_config()


def get_logger(name: str = "answer_mark") -> logging.Logger:
    """
    获取项目统一 logger。控制台 + 文件，按 5MB 滚动，保留 3 个备份。
    """
    logger = logging.getLogger(name)
    if logger.handlers:  # 避免重复初始化
        return logger

    logger.setLevel(getattr(logging, _CONFIG.LOG_LEVEL, logging.INFO))

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    # 文件
    os.makedirs(_CONFIG.LOG_DIR, exist_ok=True)
    fh = RotatingFileHandler(
        _CONFIG.LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger


def log_judge(image_name: str, total_score: float, full_score: float,
              error_summary: dict, latency_ms: int):
    """专门记录一次判题的核心信息，方便 grep 分析。"""
    lg = get_logger()
    lg.info(
        f"JUDGE | image={image_name} | total={total_score}/{full_score} | "
        f"errors={error_summary} | latency={latency_ms}ms"
    )