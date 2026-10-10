"""
main_cli.py —— 命令行批量判题入口（不需要启 Web 服务）
用法：
  python backend/main_cli.py --images img1.jpg img2.jpg --context "..."
"""
import argparse
import json
import os
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)

from modules.pipeline import run_judge, run_judge_batch
from utils.io_helper import save_csv, save_json


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--images", nargs="+", required=True, help="答卷图片路径列表")
    p.add_argument("--context", default="", help="题目已知条件")
    p.add_argument("--full", type=float, default=10.0, help="满分")
    p.add_argument("--out_json", default="output/批量结果.json")
    p.add_argument("--out_csv", default="output/判题结果汇总.csv")
    args = p.parse_args()

    results = run_judge_batch(args.images, question_context=args.context, full_score=args.full)

    # 导出
    save_json(results, args.out_json)

    rows = []
    for r in results:
        if "error" in r:
            rows.append({"image_name": r["image_name"], "error": r["error"]})
            continue
        m3 = r.get("M3_judgment", {})
        err = r.get("M2_elements", {}).get("error_summary", {})
        rows.append({
            "image_name": r.get("image_name"),
            "total_score": m3.get("total_score"),
            "full_score": m3.get("full_score"),
            "logic_gap": err.get("logic_gap", 0),
            "calculation_error": err.get("calculation_error", 0),
            "concept_error": err.get("concept_error", 0),
            "weak_points": ";".join(w["node_name"] for w in m3.get("weak_knowledge_points", [])),
            "latency_ms": r.get("total_latency_ms"),
            "created_at": r.get("created_at"),
        })
    save_csv(rows, args.out_csv)

    print(f"\n✅ 已完成 {len(results)} 张判题")
    print(f"   JSON: {args.out_json}")
    print(f"   CSV : {args.out_csv}")


if __name__ == "__main__":
    main()