"""CLI entry point. Usage:

    python main.py "give me next month's production plan"
    python main.py "what if demand for SKU-12 spikes 20%?" --data-dir data
    python main.py "Plant-A Line-1 is down for maintenance next month, replan" --regenerate-data
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback

from myproject import data_gen, reporting
from myproject.agents import orchestrator

DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
DEFAULT_LOGS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Multi-agent SKU demand forecasting, capacity reconciliation, and production allocation.",
    )
    parser.add_argument("request", help="Plain-English request, e.g. \"give me next month's production plan\"")
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR, help="Directory for sample data CSVs (default: ./data)")
    parser.add_argument("--logs-dir", default=DEFAULT_LOGS_DIR, help="Directory for run logs (default: ./logs)")
    parser.add_argument("--regenerate-data", action="store_true", help="Regenerate sample data even if it already exists")
    return parser


def run(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)

    try:
        data_gen.ensure_sample_data(args.data_dir, force=args.regenerate_data)
    except Exception as exc:  # data generation must never crash the CLI silently
        print(f"Failed to prepare sample data: {exc}")
        return 1

    try:
        result, run_id = orchestrator.handle_request(args.request, args.data_dir, args.logs_dir)
    except Exception as exc:  # last-resort guard: never dump a raw traceback to the user
        os.makedirs(args.logs_dir, exist_ok=True)
        with open(os.path.join(args.logs_dir, "crash.log"), "a", encoding="utf-8") as f:
            f.write(traceback.format_exc() + "\n")
        print(f"Internal error while handling the request: {exc}")
        print(f"Details were written to {os.path.join(args.logs_dir, 'crash.log')}")
        return 1

    print(reporting.render_report(result))
    print(f"\n(run log: {os.path.join(args.logs_dir, f'run_{run_id}.jsonl')})")
    return 0


def main() -> None:
    sys.exit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
