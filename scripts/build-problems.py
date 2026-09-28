#!/usr/bin/env python3
from __future__ import annotations

import os
import json
import shlex
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Problem:
    code: str
    slug: str
    color: str


@dataclass(frozen=True)
class Result:
    problem: Problem
    final_zip: Path
    staged_zip: Path
    log_file: Path
    cache_key: str
    returncode: int
    elapsed: float


def main() -> int:
    if len(sys.argv) < 8 or sys.argv[7] != "--":
        raise SystemExit(
            "usage: build-problems.py PROBLEMS_TSV PROBLEMS_DIR STAGE_DIR OUTPUT_DIR MATERIALIZE_SCRIPT JOBS -- [P2D_ARGS...]"
        )

    problems_file = Path(sys.argv[1])
    problems_dir = Path(sys.argv[2])
    stage_dir = Path(sys.argv[3])
    output_dir = Path(sys.argv[4])
    materialize_script = Path(sys.argv[5])
    jobs = parse_jobs(sys.argv[6])
    p2d_args = sys.argv[8:]

    problems = read_problems(problems_file)
    logs_dir = problems_file.parent / "logs"
    logs_dir.mkdir(exist_ok=True)
    stage_dir.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)
    manifest_path = output_dir / ".build-manifest.json"
    manifest = load_manifest(manifest_path)
    p2d_cmd = resolve_p2d_cmd()

    print(f"Building {len(problems)} problems with {jobs} worker{'s' if jobs != 1 else ''}.", flush=True)

    plans = []
    next_manifest = dict(manifest)
    next_manifest["version"] = 1
    next_manifest["problems"] = dict(manifest.get("problems", {}))
    for problem in problems:
        final_zip = output_dir / f"{problem.code}.zip"
        staged_zip = stage_dir / f"{problem.code}.zip"
        log_file = logs_dir / f"{problem.code}-{problem.slug}.log"
        cache_key = problem_cache_key(problem, problems_dir / problem.slug, materialize_script, p2d_cmd, p2d_args)
        entry = manifest.get("problems", {}).get(problem.code, {})

        if (
            entry.get("slug") == problem.slug
            and entry.get("cache_key") == cache_key
            and final_zip.is_file()
            and entry.get("output_sha256") == sha256_file(final_zip)
        ):
            print(f"[{problem.code}] SKIP {problem.slug} (cached)", flush=True)
            continue

        plans.append((problem, staged_zip, final_zip, log_file, cache_key))
        print(f"[{problem.code}] queued {problem.slug} ({problem.color})", flush=True)

    failures: list[Result] = []
    results: list[Result] = []
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = [
            pool.submit(
                build_problem,
                problem,
                problems_dir,
                staged_zip,
                final_zip,
                materialize_script,
                p2d_cmd,
                p2d_args,
                log_file,
                cache_key,
            )
            for problem, staged_zip, final_zip, log_file, cache_key in plans
        ]
        for future in as_completed(futures):
            result = future.result()
            if result.returncode == 0:
                results.append(result)
                print(f"[{result.problem.code}] built {result.problem.slug} ({result.elapsed:.1f}s)", flush=True)
            else:
                failures.append(result)
                print(f"[{result.problem.code}] FAIL {result.problem.slug} ({result.elapsed:.1f}s)", flush=True)

    for result in failures:
        print(f"\n--- {result.problem.code} {result.problem.slug} log ---", flush=True)
        print(log_tail(result.log_file), end="", flush=True)

    if failures:
        print(f"\nFailed {len(failures)} problem{'s' if len(failures) != 1 else ''}.", file=sys.stderr)
        return 1

    for result in sorted(results, key=lambda item: item.problem.code):
        action, output_sha256 = sync_zip(result.staged_zip, result.final_zip)
        next_manifest["problems"][result.problem.code] = {
            "slug": result.problem.slug,
            "cache_key": result.cache_key,
            "output_sha256": output_sha256,
        }
        print(f"[{result.problem.code}] {action} {result.final_zip}", flush=True)

    save_manifest(manifest_path, next_manifest)
    return 0


def parse_jobs(value: str) -> int:
    if not value.isdigit() or int(value) < 1:
        raise SystemExit("CONTEST_JOBS must be a positive integer")
    return int(value)


def read_problems(path: Path) -> list[Problem]:
    problems = []
    for line in path.read_text(encoding="utf-8").splitlines():
        code, slug, color = line.split("\t")
        problems.append(Problem(code, slug, color))
    if not problems:
        raise SystemExit("no problems found")
    return problems


def build_problem(
    problem: Problem,
    problems_dir: Path,
    staged_zip: Path,
    final_zip: Path,
    materialize_script: Path,
    p2d_cmd: list[str],
    p2d_args: list[str],
    log_file: Path,
    cache_key: str,
) -> Result:
    start = time.monotonic()
    problem_dir = problems_dir / problem.slug

    with log_file.open("w", encoding="utf-8") as log:
        if not (problem_dir / "problem.xml").is_file():
            log.write(f"missing problem.xml: {problem_dir}\n")
            return result(problem, final_zip, staged_zip, log_file, cache_key, 1, start)

        commands = [
            [sys.executable, str(materialize_script), str(problem_dir)],
            [
                *p2d_cmd,
                str(problem_dir),
                "--code",
                problem.code,
                "--color",
                problem.color,
                "--output",
                str(staged_zip),
                "--yes",
                "--with-statement",
                "--auto",
                *p2d_args,
            ],
        ]

        for command in commands:
            returncode = run_logged(command, log)
            if returncode != 0:
                return result(problem, final_zip, staged_zip, log_file, cache_key, returncode, start)

    return result(problem, final_zip, staged_zip, log_file, cache_key, 0, start)


def resolve_p2d_cmd() -> list[str]:
    if raw := os.environ.get("P2D_CMD"):
        return shlex.split(raw)
    repo_dir = Path(__file__).resolve().parents[1]
    if shutil.which("uv") and (repo_dir / "pyproject.toml").is_file():
        return ["uv", "run", "p2d"]
    return ["p2d"]


def run_logged(command: list[str], log) -> int:
    log.write(f"$ {shlex.join(command)}\n")
    log.flush()
    try:
        completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=False)
    except OSError as exc:
        log.write(f"error: {exc}\n")
        return 127
    return completed.returncode


def result(
    problem: Problem,
    final_zip: Path,
    staged_zip: Path,
    log_file: Path,
    cache_key: str,
    returncode: int,
    start: float,
) -> Result:
    return Result(problem, final_zip, staged_zip, log_file, cache_key, returncode, time.monotonic() - start)


def sync_zip(staged_zip: Path, final_zip: Path) -> tuple[str, str]:
    output_sha256 = sha256_file(staged_zip)
    if final_zip.is_file() and sha256_file(final_zip) == output_sha256:
        return "unchanged", output_sha256

    existed = final_zip.is_file()
    tmp = final_zip.with_name(f".{final_zip.name}.tmp")
    shutil.copy2(staged_zip, tmp)
    tmp.replace(final_zip)
    return "updated" if existed else "created", output_sha256


def problem_cache_key(
    problem: Problem,
    problem_dir: Path,
    materialize_script: Path,
    p2d_cmd: list[str],
    p2d_args: list[str],
) -> str:
    digest = new_hash()
    update_text(digest, "cache-v1")
    update_text(digest, problem.code)
    update_text(digest, problem.color)
    update_text(digest, shlex.join(p2d_cmd))
    update_text(digest, shlex.join(p2d_args))
    update_text(digest, os.environ.get("DOMJUDGE_GXX_IMAGE", "domjudge/judgehost:9.0.0"))
    update_file(digest, materialize_script)
    update_tree(digest, problem_dir)

    repo_dir = Path(__file__).resolve().parents[1]
    for path in sorted((repo_dir / "p2d").rglob("*.py")):
        update_file(digest, path)
    for path in [repo_dir / "pyproject.toml", repo_dir / "config.toml"]:
        if path.exists():
            update_file(digest, path)

    return digest.hexdigest()


def update_tree(digest, root: Path) -> None:
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative_path = path.relative_to(root)
        if ".p2d-build" in relative_path.parts:
            continue
        update_file(digest, path, relative_path)


def update_file(digest, path: Path, cache_path: Path | None = None) -> None:
    update_text(digest, (cache_path or path).as_posix())
    digest.update(path.read_bytes())


def update_text(digest, text: str) -> None:
    digest.update(text.encode())
    digest.update(b"\0")


def sha256_file(path: Path) -> str:
    digest = new_hash()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def new_hash():
    import hashlib

    return hashlib.sha256()


def load_manifest(path: Path) -> dict:
    if not path.is_file():
        return {"version": 1, "problems": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": 1, "problems": {}}
    if not isinstance(data, dict) or not isinstance(data.get("problems"), dict):
        return {"version": 1, "problems": {}}
    return data


def save_manifest(path: Path, manifest: dict) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def log_tail(path: Path, max_lines: int = 200) -> str:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    if len(lines) <= max_lines:
        return "".join(lines)
    return f"... showing last {max_lines} lines\n" + "".join(lines[-max_lines:])


if __name__ == "__main__":
    raise SystemExit(main())
