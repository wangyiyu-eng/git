"""
tests/accuracy_test.py
判题准确率测试：
  - 在 ground_truth.json 中准备若干带标准答案的测试条目
  - 逐条跑流水线，统计：
      * 最终答案判对率
      * 错误类型识别准确率（对比GT中标注的错误步骤）
      * average latency
  - 结果打印 + 导出CSV
ground_truth.json 结构（示例）：
[
  {
    "image_path": "tests/sample_images/p1.jpg",
    "context": "...",
    "full_score": 10,
    "expected_final_verdict": "correct" | "incorrect",
    "expected_error_types": ["calculation_error"],
    "expected_weak_points": ["MATH-LIN-1V"]
  }
]
"""
import argparse
import csv
import json
import os
import sys
import time
from collections import defaultdict


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--gt",
        default=os.path.join(os.path.dirname(__file__), "ground_truth.json"),
        help="ground truth 文件",
    )
    parser.add_argument("--limit", type=int, default=0, help="最多测试几条")
    parser.add_argument("--csv", default="", help="结果导出CSV路径")
    args = parser.parse_args()

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from modules.pipeline import run_judge

    if not os.path.exists(args.gt):
        print(f"❌ 未找到 ground_truth: {args.gt}")
        print("请按 README 中的说明准备测试样本。")
        sys.exit(1)

    gts = json.load(open(args.gt, "r", encoding="utf-8"))
    if args.limit:
        gts = gts[:args.limit]

    # 统计
    n = 0
    n_final_correct = 0
    err_type_match = defaultdict(int)
    err_type_total = defaultdict(int)
    latencies = []
    rows = []

    for gt in gts:
        if not os.path.exists(gt["image_path"]):
            print(f"⚠ 跳过缺失图片: {gt['image_path']}")
            continue
        n += 1
        t0 = time.time()
        try:
            result = run_judge(
                image_path=gt["image_path"],
                question_context=gt.get("context", ""),
                full_score=gt.get("full_score", 10),
                image_name=os.path.basename(gt["image_path"]),
            )
        except Exception as e:
            print(f"❌ judge failed {gt['image_path']}: {e}")
            continue
        latencies.append(int((time.time() - t0) * 1000))

        m2 = result.get("M2_elements", {})
        m3 = result.get("M3_judgment", {})

        # 1. 最终答案判对率
        pred_final = m2.get("final_answer", {}).get("verdict", "uncertain")
        if pred_final == gt.get("expected_final_verdict"):
            n_final_correct += 1

        # 2. 错误类型识别准确率
        expected_types = set(gt.get("expected_error_types", []) or [])
        pred_types = set()
        for s in m2.get("steps", []):
            et = s.get("error_type")
            if et and et != "null":
                pred_types.add(et)
        for t in expected_types:
            err_type_total[t] += 1
            if t in pred_types:
                err_type_match[t] += 1

        rows.append({
            "image": gt["image_path"],
            "expected_final": gt.get("expected_final_verdict"),
            "pred_final": pred_final,
            "final_match": pred_final == gt.get("expected_final_verdict"),
            "expected_error_types": ";".join(expected_types),
            "pred_error_types": ";".join(pred_types),
            "weak_points": ";".join(w["node_name"] for w in m3.get("weak_knowledge_points", [])),
            "total_score": m3.get("total_score"),
            "full_score": m3.get("full_score"),
            "latency_ms": latencies[-1],
        })

    # 输出统计
    print("\n========== 准确率测试报告 ==========")
    print(f"样本数: {n}")
    print(f"最终答案判对率: {n_final_correct}/{n} = "
          f"{(n_final_correct / n * 100 if n else 0):.1f}%")
    print("\n错误类型识别准确率:")
    for t, total in err_type_total.items():
        c = err_type_match.get(t, 0)
        print(f"  - {t}: {c}/{total} = {(c/total*100 if total else 0):.1f}%")
    if latencies:
        print(f"\n平均耗时: {sum(latencies)/len(latencies):.0f} ms / 张")
        print(f"最长: {max(latencies)} ms / 最短: {min(latencies)} ms")

    # 导出CSV
    if args.csv:
        os.makedirs(os.path.dirname(os.path.abspath(args.csv)), exist_ok=True)
        with open(args.csv, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
            if rows:
                writer.writeheader()
                writer.writerows(rows)
        print(f"\n💾 详细结果已导出: {args.csv}")


if __name__ == "__main__":
    main()