"""
main.py —— FastAPI 后端服务入口（毕设版·无登录）
提供 REST API 给前端（frontend/）调用：
  GET  /                   简易首页
  GET  /api/health         健康检查
  POST /api/judge          单张答卷判题（multipart/form-data）
  POST /api/judge/batch    批量答卷判题（多文件）
  GET  /api/knowledge      获取知识图谱（用于前端可视化）
  GET  /api/results        获取历史判题结果列表

毕设版本已移除登录/鉴权相关路由与依赖，便于单机本地演示与论文说明。
"""
import os
import sys
import time
from typing import List

# 把 backend/ 加入 sys.path（便于绝对导入）
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config as app_cfg
from knowledge.kg_builder import get_kg
from modules.pipeline import run_judge
from utils.io_helper import (
    bytes_md5, file_md5, load_json, now_iso, save_json,
)
from utils.logger import get_logger


_lg = get_logger("api")


# ---------- 启动时初始化数据库（界面2的数据源） ----------
try:
    from db.database import init_db
    db_path = init_db(verbose=False)
    _lg.info(f"数据库就绪: {db_path}")
except Exception as e:
    _lg.warning(f"数据库初始化失败（学情分析将不可用）: {e}")


app = FastAPI(
    title="DeepSeek-Vision 答卷智能判题系统 API",
    description="基于 DeepSeek-Vision v1.5 多模态大模型的答卷判题系统后端服务",
    version="1.2.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=app_cfg.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- 数据模型 ----------
class JudgeResultSummary(BaseModel):
    image_id: str
    image_name: str
    total_score: float
    full_score: float
    weak_points: List[str]
    created_at: str


# ---------- 工具 ----------
def _save_upload(upload: UploadFile) -> tuple:
    """保存上传文件到 UPLOAD_DIR，返回 (abs_path, raw_bytes, image_id)。"""
    os.makedirs(app_cfg.UPLOAD_DIR, exist_ok=True)
    raw = upload.file.read()
    ts = int(time.time() * 1000)
    safe_name = f"{ts}_{(upload.filename or 'image').replace('/', '_')}"
    abs_path = os.path.join(app_cfg.UPLOAD_DIR, safe_name)
    with open(abs_path, "wb") as f:
        f.write(raw)
    return abs_path, raw, bytes_md5(raw)


def _result_to_summary(result: dict) -> dict:
    j = result.get("M3_judgment", {})
    return {
        "image_id": result.get("image_id"),
        "image_name": result.get("image_name"),
        "total_score": j.get("total_score"),
        "full_score": j.get("full_score"),
        "weak_points": [w["node_name"] for w in j.get("weak_knowledge_points", [])],
        "created_at": result.get("created_at"),
    }


def _list_results(limit: int = 50) -> list:
    """从 results 目录读取历史判题结果，按 mtime 倒序。"""
    results_dir = app_cfg.RESULT_DIR
    if not os.path.isdir(results_dir):
        return []
    files = sorted(
        [f for f in os.listdir(results_dir) if f.endswith(".json")],
        key=lambda x: os.path.getmtime(os.path.join(results_dir, x)),
        reverse=True,
    )
    out = []
    for fn in files[:limit]:
        try:
            d = load_json(os.path.join(results_dir, fn))
            out.append(_result_to_summary(d))
        except Exception as e:
            _lg.warning(f"读取历史结果失败 {fn}: {e}")
    return out


# ---------- 路由 ----------
@app.get("/")
def index():
    # 直接跳转到前端首页
    return RedirectResponse(url="/web/")


# ---------- 静态前端 ----------
# 把 frontend/ 挂载到 /web/
FRONTEND_DIR = os.path.normpath(os.path.join(THIS_DIR, "..", "frontend"))
if os.path.isdir(FRONTEND_DIR):
    app.mount("/web", StaticFiles(directory=FRONTEND_DIR, html=True), name="web")
else:
    _lg.warning(f"前端目录不存在: {FRONTEND_DIR}")


@app.get("/api/health")
def health():
    """健康检查（毕设无需登录）。"""
    return {
        "status": "ok",
        "time": now_iso(),
        "model": app_cfg.DEEPSEEK_MODEL,
        "api_base": app_cfg.DEEPSEEK_API_BASE,
    }


# ---------- 判题 ----------
@app.post("/api/judge")
async def api_judge(
    file: UploadFile = File(...),
    question_context: str = Form(""),
    full_score: float = Form(10.0),
):
    """单张答卷判题。"""
    try:
        abs_path, raw, image_id = _save_upload(file)

        # 同时保存到 results 目录，文件名含 image_id 前缀便于查询
        os.makedirs(app_cfg.RESULT_DIR, exist_ok=True)
        ts = int(time.time() * 1000)
        save_path = os.path.join(app_cfg.RESULT_DIR, f"{ts}_{image_id[:10]}.json")

        result = run_judge(
            raw_bytes=raw,
            question_context=question_context,
            full_score=full_score,
            image_name=file.filename or "uploaded.jpg",
            save_to=save_path,
        )
        return JSONResponse(content={"success": True, "data": result})
    except Exception as e:
        _lg.error(f"/api/judge failed: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.post("/api/judge/batch")
async def api_judge_batch(
    files: List[UploadFile] = File(...),
    question_context: str = Form(""),
    full_score: float = Form(10.0),
):
    """
    批量答卷判题：逐张走完整流水线，返回与单题接口相同的完整结果
    （M1/M2/M3 + per_problem 明细），前端可直接渲染富详情卡片。
    """
    results = []
    for f in files:
        try:
            abs_path, raw, image_id = _save_upload(f)
            ts = int(time.time() * 1000)
            save_path = os.path.join(app_cfg.RESULT_DIR, f"{ts}_{image_id[:10]}.json")
            r = run_judge(
                raw_bytes=raw,
                question_context=question_context,
                full_score=full_score,
                image_name=f.filename or "uploaded.jpg",
                save_to=save_path,
            )
            results.append(r)  # 完整结果（前端逐题渲染需要）
        except Exception as e:
            _lg.error(f"batch judge {f.filename}: {e}")
            results.append({"image_name": f.filename, "error": str(e)})
    return JSONResponse(content={"success": True, "data": results})


@app.get("/api/knowledge")
def api_knowledge():
    """返回知识图谱全部节点和边，供前端可视化。"""
    kg = get_kg()
    return JSONResponse(content={"success": True, "data": kg.to_dict_for_frontend()})


@app.get("/api/results")
def api_results(limit: int = 50):
    """获取历史判题结果列表（最近 N 条）。"""
    return JSONResponse(content={"success": True, "data": _list_results(limit)})


# ---------- 学情分析路由 ----------
from api_analytics import router as analytics_router  # noqa: E402
app.include_router(analytics_router)


# 启动（直接 `python backend/main.py` 或 uvicorn 调用）
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=app_cfg.HOST, port=app_cfg.PORT, reload=False)