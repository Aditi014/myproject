"""Root-level CLI entry point, per the project spec:

    python main.py "give me next month's production plan for SKU-3 and SKU-7"

Adds src/ to sys.path so this works directly with the stdlib interpreter,
without requiring `uv sync` / an editable install first.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from myproject.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
