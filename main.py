"""Sonar - 帮你读懂任何文章的学习助手。"""

import argparse
import sys

from dotenv import load_dotenv
from llm.client import LLMClient

from pipeline import Pipeline


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Sonar - 帮你读懂任何文章的学习助手",
    )
    parser.add_argument("source", nargs="?", help="文章 URL 或本地文件路径（.pdf / .md / .txt / .html）")
    parser.add_argument("--mode", default="explain", choices=["reading", "explain"],
                        help="报告模式: reading=快速摘要, explain=完整学习报告 (default: explain)")
    parser.add_argument("--goal", default="", help="自定义学习目标")
    parser.add_argument("--resume-from", dest="resume_from",
                        choices=["fetch", "analyze", "plan", "research", "synthesize"],
                        help="从指定阶段恢复执行")
    parser.add_argument("--run-id", default="",
                        help="指定运行 ID（用于输出到 output/runs/<run_id>）")
    args = parser.parse_args()

    if not args.source and not args.resume_from:
        parser.print_help()
        sys.exit(1)

    llm = LLMClient()
    source = args.source or ""
    print(f"Sonar - 正在分析: {source or '(从缓存恢复)'}\n")

    pipeline = Pipeline(llm, mode=args.mode, goal=args.goal)
    try:
        output_path = pipeline.run(source, resume_from=args.resume_from, run_id=args.run_id or None)
    except (RuntimeError, ValueError) as e:
        print(f"\n错误: {e}")
        sys.exit(1)

    print(f"\n学习报告已生成: {output_path}")


if __name__ == "__main__":
    main()
