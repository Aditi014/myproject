def main() -> None:
    """Console-script entry point (`uv run myproject "..."`). Delegates to
    the same CLI as the root-level main.py."""
    import sys

    from myproject.cli import run

    sys.exit(run(sys.argv[1:]))
