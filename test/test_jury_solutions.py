"""Jury submission layout for Java solutions."""

import shutil
from pathlib import Path
from types import SimpleNamespace
from xml.etree.ElementTree import Element, SubElement
from zipfile import ZipFile

from p2d.models import GlobalConfig
from p2d.steps.jury_solutions import add_jury_solutions


def test_java_solutions_with_shared_public_class_remain_separate(tmp_path: Path) -> None:
    package_dir = tmp_path / "polygon"
    solutions = []
    for source_name, tag, content in (
        ("Slow.java", "main", '// public class Wrong\nclass Noise { String text = "public class Fake"; }\npublic class Main { }\n'),
        ("Fast.java", "main", "public final class Main { }\n"),
        ("Other.java", "time-limit-exceeded-or-accepted", "public class Main { }\n"),
        ("Named.java", "wrong-answer", "public class Solver { }\n"),
        ("Helper.java", "main", "class Main { public class Inner { } }\n"),
    ):
        source = package_dir / source_name
        source.parent.mkdir(exist_ok=True)
        source.write_text(content, encoding="utf-8")
        solution = Element("solution", {"tag": tag})
        SubElement(solution, "source", {"path": source_name, "type": "java11"})
        solutions.append(solution)

    ctx = SimpleNamespace(
        package_dir=package_dir,
        temp_dir=tmp_path / "domjudge",
        problem=SimpleNamespace(solutions=solutions),
        config=GlobalConfig(),
    )
    add_jury_solutions(ctx)

    submissions = ctx.temp_dir / "submissions"
    assert (submissions / "accepted" / "Slow" / "Main.java").read_text() == (
        '// public class Wrong\nclass Noise { String text = "public class Fake"; }\npublic class Main { }\n'
    )
    assert (submissions / "accepted" / "Fast" / "Main.java").read_text() == "public final class Main { }\n"
    assert (submissions / "wrong_answer" / "Named" / "Solver.java").read_text() == "public class Solver { }\n"
    assert (submissions / "accepted" / "Helper" / "Helper.java").is_file()
    mixed = (submissions / "mixed" / "Other" / "Main.java").read_text()
    assert "@EXPECTED_RESULTS@: TIMELIMIT, CORRECT" in mixed

    archive = shutil.make_archive(str(tmp_path / "problem"), "zip", ctx.temp_dir)
    with ZipFile(archive) as package:
        assert "submissions/accepted/Slow/" in package.namelist()
        assert "submissions/accepted/Fast/" in package.namelist()


def test_same_java_source_basename_gets_unique_directories(tmp_path: Path) -> None:
    package_dir = tmp_path / "polygon"
    solutions = []
    for subdir in ("a", "b"):
        source = package_dir / subdir / "Main.java"
        source.parent.mkdir(parents=True)
        source.write_text(f"public class Main {{ // {subdir}\n}}\n", encoding="utf-8")
        solution = Element("solution", {"tag": "main"})
        SubElement(solution, "source", {"path": f"{subdir}/Main.java", "type": "java11"})
        solutions.append(solution)

    ctx = SimpleNamespace(
        package_dir=package_dir,
        temp_dir=tmp_path / "domjudge",
        problem=SimpleNamespace(solutions=solutions),
        config=GlobalConfig(),
    )
    add_jury_solutions(ctx)

    accepted = ctx.temp_dir / "submissions" / "accepted"
    assert "// a" in (accepted / "Main" / "Main.java").read_text()
    assert "// b" in (accepted / "Main-2" / "Main.java").read_text()
