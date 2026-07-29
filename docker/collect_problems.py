#!/usr/bin/env python3
"""Copy the *runtime* subset of each problem folder into the image.

Run during `docker build`. This is an allowlist, not a denylist: a new
authoring artifact an expert invents (design notes, calibration logs, a
spreadsheet of near-misses) is excluded by default rather than silently shipped
next to the answer key.

What ships, per problem:
    problem.md              the task prompt
    config.yaml             display metadata (optional)
    oracle/**               the hidden system, including any helper modules
                            and data files it imports
    golden/expected.json    the graded answer
    grader/grade.py         optional custom grader (and helper .py beside it)

What never ships:
    solution/**             the intended solver and the shortcut/trap solver
    grader/grading_guide.md the near-miss table — names the trap outright
    BRIEF.md STATE.md reasoning_trap.md   authoring and calibration notes
    anything else at the top level of the problem folder

usage: collect_problems.py SRC DEST
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ALLOWED_FILES = ("problem.md", "config.yaml")
ALLOWED_DIRS = ("oracle", "golden")
ALLOWED_GRADER_SUFFIXES = (".py",)
SKIP_DIR_NAMES = {"__pycache__"}


def collect(src: Path, dest: Path) -> int:
    count = 0
    for problem_dir in sorted(p for p in src.iterdir() if p.is_dir()):
        # Templates and scratch folders are not problems (see core.discover_problems).
        if problem_dir.name.startswith(("_", ".")):
            print(f"  skip {problem_dir.name}/ (reserved prefix)")
            continue
        if not (problem_dir / "problem.md").is_file():
            print(f"  skip {problem_dir.name}/ (no problem.md)")
            continue

        target = dest / problem_dir.name
        target.mkdir(parents=True, exist_ok=True)
        shipped: list[str] = []

        for filename in ALLOWED_FILES:
            source = problem_dir / filename
            if source.is_file():
                shutil.copy2(source, target / filename)
                shipped.append(filename)

        for dirname in ALLOWED_DIRS:
            source = problem_dir / dirname
            if source.is_dir():
                shutil.copytree(
                    source,
                    target / dirname,
                    dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(*SKIP_DIR_NAMES, "*.pyc"),
                )
                shipped.append(f"{dirname}/")

        grader_src = problem_dir / "grader"
        if grader_src.is_dir():
            for source in sorted(grader_src.rglob("*")):
                if not source.is_file() or source.suffix not in ALLOWED_GRADER_SUFFIXES:
                    continue
                if any(part in SKIP_DIR_NAMES for part in source.parts):
                    continue
                relative = source.relative_to(problem_dir)
                (target / relative).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target / relative)
                shipped.append(str(relative))

        print(f"  {problem_dir.name}: {', '.join(shipped)}")
        count += 1
    return count


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    src, dest = Path(argv[1]), Path(argv[2])
    if not src.is_dir():
        print(f"error: source {src} is not a directory", file=sys.stderr)
        return 1
    dest.mkdir(parents=True, exist_ok=True)

    print(f"collecting problems from {src} -> {dest}")
    count = collect(src, dest)
    if count == 0:
        print("error: no problems found to collect", file=sys.stderr)
        return 1
    print(f"collected {count} problem(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
