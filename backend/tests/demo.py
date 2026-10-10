"""
tests/demo.py
单文件 demo：示例答卷图片全流程跑通 + 打印判题结果。
用法：
  python -m tests.demo --image backend/data/sample_images/sample.jpg
"""
import json
import os
import sys
import argparse


def main():
    parser = argparse.ArgumentParser(description="答卷判题 Demo")
    parser.add_argument(
        "--image", "-i",
        default=os.path.join(os.path.dirname(__file__), "..", "data", "sample_images", "sample.jpg"),
        help="答卷图片路径",
    )
    parser.add_argument("--context", "-c", default="", help="题目已知条件")
    parser.add_argument("--full", "-f", type=float, default=10.0, help="满分")
    parser.add_argument("--save", "-s", action="store_true", help="保存完整JSON到 output/")
    args = parser.parse_args()

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from modules.pipeline import run_judge

    if not os.path.exists(args.image):
        print(f"❌ 图片不存在: {args.image}")
        print("   请把示例答卷放到该路径，或用 --image 指定。")
        sys.exit(1)

    save_to = None
    if args.save:
        out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "output")
        os.makedirs(out_dir, exist_ok=True)
        save_to = os.path.join(out_dir, f"demo_{os.path.basename(args.image)}.json")

    print(f"▶ 开始判题: {args.image}")
    result = run_judge(
        image_path=args.image,
        question_context=args.context,
        full_score=args.full,
        image_name=os.path.basename(args.image),
        save_to=save_to,
    )

    # 简洁打印
    m1 = result.get("M1_feature", {})
    m2 = result.get("M2_elements", {})
    m3 = result.get("M3_judgment", {})
    print("\n========== 文本识别 ==========")
    print(m1.get("raw_text", "")[:500])
    print("\n========== 解题步骤 ==========")
    for s in m2.get("steps", []):
        print(f"  [{s.get('verdict')}] 步骤{s.get('step_id')}: {s.get('content')} -> {s.get('result')}")
        if s.get("error_type"):
            print(f"      错误类型: {s['error_type']} | 原因: {s.get('reason')}")
    print("\n========== 判分 ==========")
    print(f"总分: {m3.get('total_score')} / {m3.get('full_score')}")
    for b in m3.get("score_breakdown", []):
        print(f"  - {b['item']}: {b['got']}/{b['full']} | {b['reason']}")
    print("\n========== 薄弱知识点 ==========")
    for w in m3.get("weak_knowledge_points", []):
        print(f"  - {w['node_name']} ({w['mastery']*100:.0f}%) → {w['advice']}")
    print("\n========== 反馈 ==========")
    print(m3.get("feedback", ""))

    print(f"\n📦 完整 JSON 字段: image_id={result.get('image_id')}, latency={result.get('total_latency_ms')}ms")
    if save_to:
        print(f"💾 已保存到: {save_to}")


if __name__ == "__main__":
    main()