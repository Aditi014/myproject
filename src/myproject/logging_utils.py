"""Appends one JSON line per agent call to logs/run_<run_id>.jsonl, for
debugging and auditability (spec requirement: log every agent call with
input, output, retry count, and validation pass/fail)."""

from __future__ import annotations

import datetime
import json
import os


def new_run_id() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")


class RunLogger:
    def __init__(self, logs_dir: str, run_id: str):
        self.logs_dir = logs_dir
        self.run_id = run_id
        os.makedirs(logs_dir, exist_ok=True)
        self.path = os.path.join(logs_dir, f"run_{run_id}.jsonl")

    def log(self, agent: str, input_summary, output_summary, retries: int, passed: bool, note: str = "") -> None:
        entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "run_id": self.run_id,
            "agent": agent,
            "input": input_summary,
            "output": output_summary,
            "retries": retries,
            "validation_passed": passed,
            "note": note,
        }
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
