#!/usr/bin/env python3
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


GXX_IMAGE = os.environ.get("DOMJUDGE_GXX_IMAGE", "domjudge/judgehost:9.0.0")


def main() -> int:
    problem_dir = Path(sys.argv[1])
    root = ET.parse(problem_dir / "problem.xml").getroot()
    build_dir = problem_dir / ".p2d-build"
    tools: dict[str, list[str]] = {}
    made_inputs = 0
    made_answers = 0

    executable_sources = {
        Path(source.attrib["path"]).stem: Path(source.attrib["path"])
        for source in root.findall("files/executables/executable/source[@path]")
    }
    solution = root.find("assets/solutions/solution[@tag='main']/source[@path]")
    solution_source = None if solution is None else Path(solution.attrib["path"])
    solution_cmd: list[str] | None = None
    interactive = root.find("assets/interactor") is not None

    for testset in root.findall("judging/testset"):
        input_pattern = required_text(testset, "input-path-pattern")
        answer_pattern = required_text(testset, "answer-path-pattern")

        for index, test in enumerate(testset.findall("tests/test"), 1):
            input_path = problem_dir / (input_pattern % index)
            answer_path = problem_dir / (answer_pattern % index)

            if not input_path.exists():
                if command := test.attrib.get("cmd"):
                    run_generator(problem_dir, build_dir, command, input_path, executable_sources, tools)
                else:
                    copy_statement_file(problem_dir, root, index, "", input_path)
                made_inputs += 1

            if not answer_path.exists():
                if interactive:
                    copy_statement_file(problem_dir, root, index, ".a", answer_path, allow_missing=True)
                    answer_path.touch(exist_ok=True)
                elif solution_source is not None:
                    solution_cmd = solution_cmd or command_for_source(problem_dir, build_dir, solution_source, tools)
                    run_to_file(problem_dir, solution_cmd, answer_path, stdin=input_path)
                else:
                    copy_statement_file(problem_dir, root, index, ".a", answer_path)
                made_answers += 1

    if made_inputs or made_answers:
        print(f"  materialized {made_inputs} inputs, {made_answers} answers")
    return 0


def required_text(parent: ET.Element, tag: str) -> str:
    value = parent.findtext(tag)
    if value is None:
        raise SystemExit(f"missing <{tag}>")
    return value


def run_generator(
    problem_dir: Path,
    build_dir: Path,
    command: str,
    output: Path,
    executable_sources: dict[str, Path],
    tools: dict[str, list[str]],
) -> None:
    parts = shlex.split(command)
    if not parts:
        raise SystemExit("empty generator command")
    name = Path(parts[0]).stem
    source = executable_sources.get(name)
    if source is None:
        raise SystemExit(f"no source found for generator: {parts[0]}")
    run_to_file(problem_dir, command_for_source(problem_dir, build_dir, source, tools) + parts[1:], output)


def command_for_source(problem_dir: Path, build_dir: Path, source: Path, tools: dict[str, list[str]]) -> list[str]:
    source_path = problem_dir / source
    key = source.as_posix()
    if key in tools:
        return tools[key]

    if source.suffix == ".cpp":
        if shutil.which("docker") is None:
            raise SystemExit("Docker is required to build Polygon C++ generators and solutions")
        build_dir.mkdir(exist_ok=True)
        binary = build_dir / source.stem
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "--volume",
                f"{problem_dir.resolve()}:/work",
                "--workdir",
                "/work",
                "--entrypoint",
                "g++",
                GXX_IMAGE,
                "-std=gnu++23",
                "-O2",
                "-pipe",
                str(Path("/work") / source),
                "-o",
                str(Path("/work/.p2d-build") / source.stem),
            ],
            check=True,
        )
        tools[key] = [str(binary)]
    elif source.suffix == ".py":
        tools[key] = [sys.executable, str(source_path)]
    else:
        raise SystemExit(f"unsupported source type: {source}")

    return tools[key]


def run_to_file(problem_dir: Path, command: list[str], output: Path, *, stdin: Path | None = None) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.name + ".tmp")
    input_file = None
    try:
        if stdin is not None:
            input_file = stdin.open("rb")
        with tmp.open("wb") as output_file:
            subprocess.run(
                command,
                cwd=problem_dir,
                stdin=input_file or subprocess.DEVNULL,
                stdout=output_file,
                check=True,
            )
        tmp.replace(output)
    finally:
        if input_file is not None:
            input_file.close()
        tmp.unlink(missing_ok=True)


def copy_statement_file(
    problem_dir: Path,
    root: ET.Element,
    index: int,
    suffix: str,
    target: Path,
    *,
    allow_missing: bool = False,
) -> None:
    for language in statement_languages(root):
        source = problem_dir / "statements" / language / f"example.{index:02d}{suffix}"
        if source.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            return
    if not allow_missing:
        raise SystemExit(f"missing manual test file: {target.relative_to(problem_dir)}")


def statement_languages(root: ET.Element) -> list[str]:
    languages = ["english"]
    for statement in root.findall("statements/statement[@language]"):
        language = statement.attrib["language"]
        if language not in languages:
            languages.append(language)
    return languages


if __name__ == "__main__":
    raise SystemExit(main())
