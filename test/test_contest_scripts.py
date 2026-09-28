import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts.contest_times import contest_duration, eastern_time


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def test_eastern_offsets_and_elapsed_duration() -> None:
    spring_start = eastern_time("2026-03-08T01:30:00", "start_time")
    spring_end = eastern_time("2026-03-08T03:30:00", "end_time")
    assert spring_start.isoformat() == "2026-03-08T01:30:00-05:00"
    assert spring_end.isoformat() == "2026-03-08T03:30:00-04:00"
    assert contest_duration(spring_start, spring_end) == "1:00:00.000"

    fall_start = eastern_time("2026-11-01T00:30:00", "start_time")
    fall_end = eastern_time("2026-11-01T02:30:00", "end_time")
    assert fall_start.isoformat() == "2026-11-01T00:30:00-04:00"
    assert fall_end.isoformat() == "2026-11-01T02:30:00-05:00"
    assert contest_duration(fall_start, fall_end) == "3:00:00.000"


@pytest.mark.parametrize(
    "value",
    ["2026-03-08T02:30:00", "2026-11-01T01:30:00", "2026-07-01T12:00:00-05:00"],
)
def test_invalid_eastern_times(value: str) -> None:
    with pytest.raises(ValueError):
        eastern_time(value, "start_time")


def test_build_omits_unset_times_and_new_upload_requires_them(tmp_path: Path) -> None:
    contest_xml = tmp_path / "contest.xml"
    contest_xml.write_text('<contest><problems><problem index="A" url="problems/a" /></problems></contest>')
    problem_dir = tmp_path / "problems" / "a"
    problem_dir.mkdir(parents=True)
    (problem_dir / "problem.xml").write_text('<problem short-name="a" />')
    contest_yaml = tmp_path / "packages" / "contest.yaml"
    contest_yaml.parent.mkdir()

    env = os.environ.copy()
    env["CONTEST_ID"] = "test"
    for key in ("CONTEST_START_TIME", "CONTEST_END_TIME", "CONTEST_DURATION", "CONTEST_ACTIVATE_TIME"):
        env.pop(key, None)
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "prepare-contest.py"), str(contest_xml), str(tmp_path / "problems"),
         str(contest_yaml), "contest.zip"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    contest = yaml.safe_load(contest_yaml.read_text())
    assert "start_time" not in contest
    assert "end_time" not in contest
    (contest_yaml.parent / "A.zip").write_bytes(b"")

    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "upload-contest.py"), str(contest_yaml.parent), "--dry-run"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "start_time is required" in result.stderr

    contest["start_time"] = "2026-07-01T12:00:00"
    contest["end_time"] = "2026-07-01T14:00:00"
    contest_yaml.write_text(yaml.safe_dump(contest))
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "upload-contest.py"), str(contest_yaml.parent), "--dry-run"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    env["CONTEST_START_TIME"] = "2026-03-08T01:30:00"
    env["CONTEST_END_TIME"] = "2026-03-08T03:30:00"
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "prepare-contest.py"), str(contest_xml), str(tmp_path / "problems"),
         str(contest_yaml), "contest.zip"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    contest = yaml.safe_load(contest_yaml.read_text())
    assert contest["start_time"] == "2026-03-08T01:30:00-05:00"
    assert contest["end_time"] == "2026-03-08T03:30:00-04:00"
    assert contest["duration"] == "1:00:00.000"
