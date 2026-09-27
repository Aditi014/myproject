"""Shared test helper: builds a temp dir with a full, deterministic set of
sample data CSVs (the same generator the real app uses), so parser/e2e
tests can reference real SKU-1..SKU-18 / Plant-*/Line-* ids."""

import os
import sys
import shutil
import tempfile

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from myproject import data_gen  # noqa: E402


def make_sample_data_dir() -> str:
    d = tempfile.mkdtemp(prefix="myproject_test_data_")
    data_gen.ensure_sample_data(d, force=True)
    return d


def cleanup(d: str) -> None:
    shutil.rmtree(d, ignore_errors=True)
