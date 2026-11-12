"""quiver-check: check a Quiver pack against the pack standard."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from quiver_check import __version__
from quiver_check.check import check, read_names


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="quiver-check", description=__doc__)
    p.add_argument("path", nargs="?", default=".", type=Path, help="the pack's root (default: .)")
    p.add_argument("--tag", default="", help="the release tag being checked, e.g. v1.0.0; empty means none")
    p.add_argument(
        "--forbid-names",
        type=Path,
        metavar="FILE",
        help="a file of names the pack must not carry, one per line (# starts a comment)",
    )
    p.add_argument(
        "--allow-slash",
        action="append",
        default=[],
        metavar="NAME",
        help="a /name that is not a skill of this pack but may be written, e.g. healthz (repeatable)",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    a = p.parse_args(argv)
    root = a.path.resolve()
    if not root.is_dir():
        p.error(f"{a.path} is not a directory")
    names = read_names(a.forbid_names) if a.forbid_names else []
    count, errors = check(root, a.tag or None, names, a.allow_slash)
    for message in errors:
        print(message)
    print(f"{count} artifact(s), {len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
