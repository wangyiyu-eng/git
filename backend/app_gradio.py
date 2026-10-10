"""
app_gradio.py —— Gradio 简易网页可视化（兼容启动方式）
若不想用前后端分离的 FastAPI，可直接 python backend/app_gradio.py 启动。
"""
import os
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)

import gradio as gr

from modules.pipeline import run_judge


def judge_one(image, question_context, full_score):
    """Gradio 调用入口。image: PIL.Image / filepath."""
    if image is None:
        return "请先上传答卷图片", "", "", "", "", ""

    # Gradio 4.x: image 输入为 numpy / PIL / filepath 三种都可能，这里统一存临时文件
    import tempfile, uuid
    from PIL import Image

    if isinstance(image, str):
        img_path = image
        raw = None
    elif isinstance(image, Image.Image):
        tmpf = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4().hex}.jpg")
        image.convert("RGB").save(tmpf, "JPEG")
        img_path = tmpf
        raw = None
    else:
        # numpy
        img = Image.fromarray(image).convert("RGB")
        tmpf = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4().hex}.jpg")
        img.save(tmpf, "JPEG")
        img_path = tmpf
        raw = None

    full_score = float(full_score or 10)

    result = run_judge(
        image_path=img_path,
        question_context=question_context or "",
        full_score=full_score,
        image_name=os.path.basename(img_path),
    )

    import json as _json
    m1 = result.get("M1_feature", {})
    m2 = result.get("M2_elements", {})
    m3 = result.get("M3_judgment", {})

    recognized_text = m1.get("raw_text") or ""
    steps_md = _render_steps_md(m2.get("steps", []))
    score_md = _render_score_md(m3)
    weak_md = _render_weak_md(m3.get("weak_knowledge_points", []))
    feedback = m3.get("feedback", "")

    return (
        recognized_text,
        steps_md,
        score_md,
        weak_md,
        feedback,
        _json.dumps(result, ensure_ascii=False, indent=2),
    )


def _render_steps_md(steps):
    if not steps:
        return "（无解题步骤）"
    lines = ["## 解题步骤"]
    for s in steps:
        v = s.get("verdict", "?")
        marker = {"correct": "✅", "incorrect": "❌", "uncertain": "❓"}.get(v, "❓")
        lines.append(f"{marker} **步骤 {s.get('step_id')}** ({v}) — {s.get('content','')}")
        lines.append(f"   - 中间结果: `{s.get('result','')}`")
        if s.get("error_type"):
            lines.append(f"   - 错误类型: `{s['error_type']}`")
        if s.get("reason"):
            lines.append(f"   - 原因: {s['reason']}")
    return "\n".join(lines)


def _render_score_md(m3):
    if not m3:
        return ""
    lines = [f"### 总分: **{m3.get('total_score')} / {m3.get('full_score')}**"]
    lines.append("| 项目 | 满分 | 得分 | 说明 |")
    lines.append("|---|---|---|---|")
    for b in m3.get("score_breakdown", []):
        lines.append(f"| {b['item']} | {b['full']} | {b['got']} | {b['reason']} |")
    rc = m3.get("reasoning_chain", {})
    lines.append(f"\n**推理链完整度**: {round(rc.get('completeness', 0)*100, 1)}%")
    return "\n".join(lines)


def _render_weak_md(weak):
    if not weak:
        return "（未识别到明显薄弱知识点）"
    lines = ["## 薄弱知识点"]
    for w in weak:
        lines.append(f"- **{w['node_name']}** — 掌握度 {w['mastery']*100:.0f}%\n  - 建议: {w['advice']}")
    return "\n".join(lines)


def build_ui():
    with gr.Blocks(title="答卷智能判题系统") as demo:
        gr.Markdown("# 📝 DeepSeek-Vision 答卷智能判题系统")
        with gr.Row():
            with gr.Column(scale=1):
                img_in = gr.Image(type="pil", label="上传答卷图片")
                qctx = gr.Textbox(label="（可选）题目已知条件/标准信息", lines=4)
                full_score = gr.Slider(1, 20, value=10, step=1, label="满分")
                btn = gr.Button("开始判题", variant="primary")
            with gr.Column(scale=2):
                out_text = gr.Textbox(label="答卷识别文本", lines=6)
                out_steps = gr.Markdown(label="解题步骤")
                out_score = gr.Markdown(label="判分结果")
                out_weak = gr.Markdown(label="薄弱知识点")
                out_feedback = gr.Textbox(label="改进建议", lines=4)
                out_json = gr.Code(label="完整JSON（可保存）", language="json")

        btn.click(
            judge_one,
            inputs=[img_in, qctx, full_score],
            outputs=[out_text, out_steps, out_score, out_weak, out_feedback, out_json],
        )
    return demo


if __name__ == "__main__":
    demo = build_ui()
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False)