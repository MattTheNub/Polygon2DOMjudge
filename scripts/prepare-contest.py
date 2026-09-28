#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath

from contest_times import contest_duration, eastern_time


COLORS = (
    ("#4E79A7", "blue"),
    ("#F28E2B", "orange"),
    ("#59A14F", "green"),
    ("#E15759", "red"),
    ("#B07AA1", "purple"),
    ("#76B7B2", "teal"),
    ("#EDC948", "yellow"),
    ("#FF9DA7", "pink"),
    ("#9C755F", "brown"),
    ("#BAB0AC", "gray"),
    ("#D37295", "rose"),
    ("#499894", "darkcyan"),
    ("#86BCB6", "lightteal"),
    ("#FABFD2", "lightpink"),
    ("#8CD17D", "lightgreen"),
    ("#B6992D", "olive"),
    ("#A0CBE8", "lightblue"),
    ("#FFBE7D", "peach"),
)


def main() -> int:
    contest_xml = Path(sys.argv[1])
    problems_dir = Path(sys.argv[2])
    contest_yaml = Path(sys.argv[3])
    contest_zip_name = sys.argv[4]

    contest_root = ET.parse(contest_xml).getroot()
    problems = contest_root.find("problems")
    if problems is None:
        raise SystemExit("contest.xml does not contain a <problems> section")

    try:
        start = eastern_time(os.environ["CONTEST_START_TIME"], "CONTEST_START_TIME") if "CONTEST_START_TIME" in os.environ else None
        end = eastern_time(os.environ["CONTEST_END_TIME"], "CONTEST_END_TIME") if "CONTEST_END_TIME" in os.environ else None
        if (start is None) != (end is None):
            raise ValueError("CONTEST_START_TIME and CONTEST_END_TIME must be set together")
        duration = contest_duration(start, end) if start and end else None
        activate = (
            eastern_time(os.environ["CONTEST_ACTIVATE_TIME"], "CONTEST_ACTIVATE_TIME")
            if "CONTEST_ACTIVATE_TIME" in os.environ
            else start
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    formal_name = english_name(contest_root, Path(contest_zip_name).stem)
    rows: list[tuple[str, str, str]] = []
    problem_entries: list[tuple[str, str, str, str, str]] = []

    for index, problem in enumerate(problems.findall("problem")):
        label = problem.attrib["index"].upper()
        slug = PurePosixPath(problem.attrib["url"]).name
        problem_root = ET.parse(problems_dir / slug / "problem.xml").getroot()
        rgb, color_name = COLORS[index % len(COLORS)]

        rows.append((label, slug, rgb))
        problem_entries.append(
            (
                problem_root.attrib.get("short-name") or slug,
                label,
                english_name(problem_root, slug.replace("-", " ").title()),
                color_name,
                rgb,
            )
        )

    contest_id = os.environ.get("CONTEST_ID")
    if not contest_id:
        raise SystemExit("CONTEST_ID is required")
    write_contest_yaml(
        contest_yaml,
        contest_id,
        formal_name,
        start.isoformat() if start else None,
        end.isoformat() if end else None,
        os.environ.get("CONTEST_DURATION") or duration,
        activate.isoformat() if activate else None,
        problem_entries,
    )
    for row in rows:
        print("\t".join(row))
    return 0


def write_contest_yaml(
    path: Path,
    contest_id: str,
    formal_name: str,
    start_time: str | None,
    end_time: str | None,
    duration: str | None,
    activate_time: str | None,
    problems: list[tuple[str, str, str, str, str]],
) -> None:
    lines = [
        f"id: {scalar(contest_id)}",
        f"formal_name: {scalar(formal_name)}",
        f"name: {scalar(os.environ.get('CONTEST_NAME') or formal_name)}",
        f"penalty_time: {int(os.environ.get('CONTEST_PENALTY_TIME', '20'))}",
        "medals:",
        f"    gold: {int(os.environ.get('CONTEST_GOLD', '4'))}",
        f"    silver: {int(os.environ.get('CONTEST_SILVER', '4'))}",
        f"    bronze: {int(os.environ.get('CONTEST_BRONZE', '4'))}",
        "problems:",
    ]

    schedule = [
        ("start_time", start_time),
        ("end_time", end_time),
        ("duration", duration),
        ("activate_time", activate_time),
    ]
    lines[3:3] = [f"{key}: {scalar(value)}" for key, value in schedule if value is not None]

    for problem_id, label, name, color_name, rgb in problems:
        lines.extend(
            [
                "    -",
                f"        id: {scalar(problem_id)}",
                f"        label: {scalar(label)}",
                f"        letter: {scalar(label)}",
                f"        name: {scalar(name)}",
                f"        color: {scalar(color_name)}",
                f"        rgb: {scalar(rgb)}",
            ]
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def english_name(root: ET.Element, fallback: str) -> str:
    names = root.find("names")
    if names is None:
        return fallback

    first = None
    for name in names.findall("name"):
        value = name.attrib.get("value")
        if not value:
            continue
        first = first or value
        if name.attrib.get("language") == "english":
            return value
    return first or fallback


def scalar(value: str | int) -> str:
    text = str(value)
    if re.fullmatch(r"[A-Za-z0-9_-]+", text):
        return text
    return "'" + text.replace("'", "''") + "'"


if __name__ == "__main__":
    raise SystemExit(main())
