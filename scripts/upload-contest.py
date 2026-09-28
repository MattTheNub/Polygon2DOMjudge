#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import netrc
import os
import secrets
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import yaml

from contest_times import contest_duration, eastern_time


class UploadError(Exception):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}: {body.strip()}")
        self.status = status
        self.body = body


def main() -> int:
    args = parse_args()
    package_dir = args.package_dir
    api_url = args.api_url.rstrip("/")
    auth = auth_header(api_url, args.user, args.password)
    context = ssl._create_unverified_context() if args.insecure else None

    contest_yaml = package_dir / "contest.yaml"
    contest = yaml.safe_load(contest_yaml.read_text(encoding="utf-8"))
    contest_id = str(contest["id"])
    problems = contest.pop("problems", None)
    if not problems:
        raise SystemExit(f"{contest_yaml} does not contain any problems")

    print(f"Uploading contest {contest_id} from {package_dir}")
    if args.update and exists(f"{api_url}/contests/{contest_id}", auth, context, args.dry_run):
        print("  contest already exists; leaving contest metadata unchanged")
    else:
        try:
            start = eastern_time(contest.get("start_time"), "start_time")
            end = eastern_time(contest.get("end_time"), "end_time")
            duration = contest_duration(start, end)
            contest["start_time"] = start.isoformat()
            contest["end_time"] = end.isoformat()
            if "activate_time" in contest:
                contest["activate_time"] = eastern_time(contest["activate_time"], "activate_time").isoformat()
            if not contest.get("duration"):
                contest["duration"] = duration
        except ValueError as exc:
            raise SystemExit(f"cannot create contest {contest_id}: {exc}") from exc
        try:
            post_yaml(
                api_url,
                "contests",
                "yaml",
                contest_yaml.name,
                yaml.safe_dump(contest, sort_keys=False),
                auth,
                context,
                args.dry_run,
            )
        except UploadError as exc:
            if not args.update:
                raise UploadError(exc.status, f"{exc.body}\nContest exists? Re-run with --update.") from exc
            raise

    existing = existing_problems(api_url, contest_id, problems, auth, context, args.dry_run)
    metadata_problems = [problem for problem in problems if str(problem["id"]) not in existing]
    if metadata_problems:
        print(f"Uploading {len(metadata_problems)} problem metadata entries")
        upload_problem_metadata(api_url, contest_id, metadata_problems, auth, context, args.dry_run)
    else:
        print("All problem metadata entries already exist; skipping metadata upload")

    for problem in problems:
        problem_id = str(problem["id"])
        label = str(problem.get("label") or problem.get("letter") or problem_id)
        zip_file = package_dir / f"{label}.zip"
        if not zip_file.is_file():
            raise SystemExit(f"missing problem package: {zip_file}")
        already_exists = problem_id in existing
        if already_exists and not args.update:
            raise SystemExit(f"problem {problem_id} already exists in contest {contest_id}; re-run with --update")

        action = "updating" if already_exists else "uploading"
        print(f"[{label}] {action} {zip_file.name} as {problem_id}")
        post_multipart(
            f"{api_url}/contests/{contest_id}/problems",
            fields={"problem": problem_id},
            files=[("zip", zip_file.name, zip_file.read_bytes(), "application/zip")],
            auth=auth,
            context=context,
            dry_run=args.dry_run,
            label=f"{label} package",
        )

    print("Upload complete.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload built DOMjudge contest packages through the DOMjudge API.")
    parser.add_argument("package_dir", type=Path, help="directory containing contest.yaml and problem ZIP files")
    parser.add_argument(
        "--api-url",
        default=os.environ.get("DOMJUDGE_API_URL", "http://localhost/api/v4"),
        help="DOMjudge API URL (default: %(default)s)",
    )
    parser.add_argument("--user", default=os.environ.get("DOMJUDGE_USER"), help="DOMjudge API username")
    parser.add_argument("--password", default=os.environ.get("DOMJUDGE_PASSWORD"), help="DOMjudge API password")
    parser.add_argument("--update", action="store_true", help="update existing contest problem packages")
    parser.add_argument("--dry-run", action="store_true", help="print API calls without uploading")
    parser.add_argument("--insecure", action="store_true", help="disable TLS certificate verification")
    return parser.parse_args()


def upload_problem_metadata(
    api_url: str,
    contest_id: str,
    problems: list[dict[str, Any]],
    auth: str | None,
    context: ssl.SSLContext | None,
    dry_run: bool,
) -> None:
    content = yaml.safe_dump(problems, sort_keys=False)
    try:
        post_yaml(api_url, f"contests/{contest_id}/problems/add-data", "data", "problems.yaml", content, auth, context, dry_run)
    except UploadError as exc:
        if exc.status not in {404, 405}:
            raise
        post_yaml(api_url, f"contests/{contest_id}/problems", "data", "problems.yaml", content, auth, context, dry_run)


def existing_problems(
    api_url: str,
    contest_id: str,
    problems: list[dict[str, Any]],
    auth: str | None,
    context: ssl.SSLContext | None,
    dry_run: bool,
) -> set[str]:
    if dry_run:
        return set()

    existing = set()
    for problem in problems:
        problem_id = str(problem["id"])
        if exists(f"{api_url}/contests/{contest_id}/problems/{problem_id}", auth, context, dry_run):
            existing.add(problem_id)
    return existing


def post_yaml(
    api_url: str,
    path: str,
    field: str,
    filename: str,
    content: str,
    auth: str | None,
    context: ssl.SSLContext | None,
    dry_run: bool,
) -> None:
    post_multipart(
        f"{api_url}/{path}",
        fields={},
        files=[(field, filename, content.encode(), "application/x-yaml")],
        auth=auth,
        context=context,
        dry_run=dry_run,
        label=filename,
    )


def post_multipart(
    url: str,
    *,
    fields: dict[str, str],
    files: list[tuple[str, str, bytes, str]],
    auth: str | None,
    context: ssl.SSLContext | None,
    dry_run: bool,
    label: str,
) -> None:
    if dry_run:
        print(f"  dry-run POST {url}")
        return

    body, content_type = multipart_body(fields, files)
    headers = {"Content-Type": content_type}
    if auth:
        headers["Authorization"] = auth

    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=120, context=context) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        raise UploadError(exc.code, exc.read().decode(errors="replace")) from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"failed to upload {label}: {exc}") from exc

    print(f"  OK {label}")


def exists(url: str, auth: str | None, context: ssl.SSLContext | None, dry_run: bool) -> bool:
    if dry_run:
        return False

    headers = {}
    if auth:
        headers["Authorization"] = auth

    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=30, context=context) as response:
            response.read()
            return True
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise UploadError(exc.code, exc.read().decode(errors="replace")) from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"failed to query {url}: {exc}") from exc


def multipart_body(fields: dict[str, str], files: list[tuple[str, str, bytes, str]]) -> tuple[bytes, str]:
    boundary = f"----p2d-{secrets.token_hex(16)}"
    body: list[bytes] = []

    for name, value in fields.items():
        body.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode(),
                b"\r\n",
            ]
        )

    for field, filename, content, content_type in files:
        body.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'.encode(),
                f"Content-Type: {content_type}\r\n\r\n".encode(),
                content,
                b"\r\n",
            ]
        )

    body.append(f"--{boundary}--\r\n".encode())
    return b"".join(body), f"multipart/form-data; boundary={boundary}"


def auth_header(api_url: str, user: str | None, password: str | None) -> str | None:
    if user or password:
        if not user or password is None:
            raise SystemExit("--user and --password must be provided together")
        return basic_auth(user, password)

    host = urllib.parse.urlparse(api_url).hostname
    if not host:
        return None

    try:
        credentials = netrc.netrc().authenticators(host)
    except (FileNotFoundError, netrc.NetrcParseError):
        return None
    if credentials is None:
        return None

    login, _, netrc_password = credentials
    return basic_auth(login, netrc_password)


def basic_auth(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {token}"


if __name__ == "__main__":
    raise SystemExit(main())
