from __future__ import annotations

import logging
import shutil
from collections.abc import Iterator
from typing import TYPE_CHECKING

from p2d.utils import ensure_dir, get_normalized_lang

if TYPE_CHECKING:
    from pathlib import Path

    from p2d.models import Result
    from p2d.pipeline import ProcessingContext

logger = logging.getLogger(__name__)

RESULT_REMAP = {
    "ACCEPTED": "CORRECT",
    "WRONG_ANSWER": "WRONG-ANSWER",
    "TIME_LIMIT_EXCEEDED": "TIMELIMIT",
    "RUN_TIME_ERROR": "RUN-ERROR",
    "COMPILER_ERROR": "COMPILER-ERROR",
    "NO_OUTPUT": "NO-OUTPUT",
    "OUTPUT_LIMIT": "OUTPUT-LIMIT",
}
"""Mapping from internal result names to DOMjudge @EXPECTED_RESULTS@ format."""


def _colorize_result(result: str) -> str:
    """Return a Rich-formatted string for the result verdict."""
    if result == "accepted":
        return f"[green italic]{result}[/]"
    if result == "wrong_answer":
        return f"[red italic]{result}[/]"
    return f"[yellow italic]{result}[/]"


def add_jury_solutions(ctx: ProcessingContext) -> None:
    """Copy jury solutions grouped by expected verdicts."""
    logger.info("[bold green reverse]Add jury solutions:[/]", extra={"markup": True})

    for solution in ctx.problem.solutions:
        tag = solution.attrib["tag"]
        results = ctx.config.tag.get(tag, None)

        if results is None:
            relative_dir = "rejected"
        elif len(results) == 1:
            relative_dir = results[0]
        else:
            relative_dir = "mixed"

        target_dir = ctx.temp_dir / "submissions" / relative_dir

        if (source := solution.find("source[@path][@type]")) is not None:
            ensure_dir(target_dir)
            src = ctx.package_dir / source.attrib["path"]
            dst = _solution_destination(src, target_dir)
            lang = source.attrib["type"]
            _add_solutions_with_expected_result(ctx, src, dst, lang, results)


def _solution_destination(src: Path, target_dir: Path) -> Path:
    """Keep Java solutions separate so public types can share the same name."""
    if src.suffix.lower() != ".java":
        return target_dir / src.name

    content = src.read_text(encoding="utf-8", errors="replace")
    filename = f"{public_type}.java" if (public_type := _java_public_type(content)) else src.name

    directory = target_dir / src.stem
    suffix = 2
    while directory.exists():
        directory = target_dir / f"{src.stem}-{suffix}"
        suffix += 1
    ensure_dir(directory)
    return directory / filename


def _java_public_type(source: str) -> str | None:
    """Find the public top-level type in a single-file Java solution."""
    depth = 0
    after_public = False
    after_type = False
    for token in _java_tokens(source):
        if token == "{":
            depth += 1
            after_public = after_type = False
        elif token == "}":
            depth -= 1
            after_public = after_type = False
        elif depth == 0:
            if after_type:
                return token
            if token == "public":
                after_public = True
            elif after_public and token in {"abstract", "final", "sealed", "strictfp"}:
                continue
            elif after_public and token in {"class", "interface", "enum", "record"}:
                after_type = True
            else:
                after_public = False
    return None


def _java_tokens(source: str) -> Iterator[str]:
    """Yield Java identifiers and structural tokens outside comments and literals."""
    index = 0
    while index < len(source):
        if source.startswith("//", index):
            end = source.find("\n", index + 2)
            index = len(source) if end < 0 else end + 1
        elif source.startswith("/*", index):
            end = source.find("*/", index + 2)
            index = len(source) if end < 0 else end + 2
        elif source.startswith('"""', index):
            end = source.find('"""', index + 3)
            index = len(source) if end < 0 else end + 3
        elif source[index] in {"\"", "'"}:
            quote = source[index]
            index += 1
            while index < len(source) and source[index] != quote:
                index += 2 if source[index] == "\\" else 1
            index += 1
        elif source[index].isalpha() or source[index] in {"_", "$"}:
            start = index
            index += 1
            while index < len(source) and (source[index].isalnum() or source[index] in {"_", "$"}):
                index += 1
            yield source[start:index]
        else:
            if source[index] in {"{", "}", ";"}:
                yield source[index]
            index += 1


def _add_solutions_with_expected_result(
    ctx: ProcessingContext,
    src: Path,
    dst: Path,
    lang: str,
    results: list[Result] | None,
) -> None:
    """Copy a solution file, adding @EXPECTED_RESULTS@ annotation if needed."""
    if results is None:
        logger.warning(
            "Find expected result with check_manually, you may add @EXPECTED_RESULTS@ in your source code for validation.",
        )
        shutil.copyfile(src, dst)
        return

    if len(results) == 1:
        logger.info("> %s: %s", src.name, _colorize_result(results[0]), extra={"markup": True})
        shutil.copyfile(src, dst)
        return

    content = src.read_text()

    if "@EXPECTED_RESULTS@" in content or "@EXPECTED_SCORE@" in content:
        logger.warning(
            "Find @EXPECTED_RESULTS@ or @EXPECTED_SCORE@ in %s, skip adding expected result.",
            src.name,
        )
        shutil.copyfile(src, dst)
        return

    logger.info(
        "> %s: %s",
        src.name,
        ", ".join(map(_colorize_result, results)),
        extra={"markup": True},
    )

    normalized_lang = get_normalized_lang(lang)
    if comment_str := ctx.config.comment_str.get(normalized_lang, None):
        remapped = ", ".join(RESULT_REMAP.get(res.upper(), res.upper()) for res in results)
        generated_comment = f"""
{comment_str} AUTO GENERATED BY POLYGON2DOMJUDGE
{comment_str} @EXPECTED_RESULTS@: {remapped}
"""
    else:
        logger.warning(
            "comment_str not found for type %s, skip adding expected result.",
            normalized_lang,
        )
        generated_comment = ""
    dst.write_text(content + generated_comment, encoding="utf-8")
