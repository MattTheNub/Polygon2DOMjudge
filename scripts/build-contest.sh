#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: scripts/build-contest.sh CONTEST_ZIP [OUTPUT_DIR] [-- P2D_ARGS...]

Convert every problem in a Polygon contest export, such as contest-55570.zip,
into separate DOMjudge packages.

Examples:
  scripts/build-contest.sh contest-55570.zip
  scripts/build-contest.sh contest-55570.zip domjudge-packages --with-attachments
  P2D_CMD="p2d" scripts/build-contest.sh contest-55570.zip out --log-level debug

Environment:
  P2D_CMD   Command used to run the converter. Defaults to "uv run p2d" when
            uv and pyproject.toml are present, otherwise "p2d".
  CONTEST_JOBS Number of problems to build concurrently. Defaults to CPU count.
  CONTEST_ID Required contest.yaml id.
  CONTEST_*  Optional contest.yaml overrides.
EOF
}

die() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

if [[ $# -lt 1 || "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
fi

contest_zip=$1
shift

output_dir=domjudge-packages
if [[ $# -gt 0 && "${1:-}" != --* ]]; then
    output_dir=$1
    shift
fi

if [[ $# -gt 0 && "${1:-}" == "--" ]]; then
    shift
fi

[[ -f "$contest_zip" ]] || die "contest zip not found: $contest_zip"
command -v unzip >/dev/null 2>&1 || die "unzip is required"
command -v python3 >/dev/null 2>&1 || die "python3 is required"

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

default_jobs() {
    if command -v nproc >/dev/null 2>&1; then
        nproc
    else
        getconf _NPROCESSORS_ONLN 2>/dev/null || printf '4\n'
    fi
}

job_count=${CONTEST_JOBS:-$(default_jobs)}
[[ "$job_count" =~ ^[1-9][0-9]*$ ]] || die "CONTEST_JOBS must be a positive integer"

tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT

mkdir -p "$output_dir"
unzip -q "$contest_zip" -d "$tmp_dir"
python3 "$script_dir/normalize-line-endings.py" "$tmp_dir"

contest_xml=$tmp_dir/contest.xml
[[ -f "$contest_xml" ]] || die "contest.xml not found at the root of $contest_zip"

contest_yaml=$tmp_dir/contest.yaml
final_contest_yaml=$output_dir/contest.yaml
problems_file=$tmp_dir/problems.tsv
python3 "$script_dir/prepare-contest.py" \
    "$contest_xml" \
    "$tmp_dir/problems" \
    "$contest_yaml" \
    "$(basename -- "$contest_zip")" \
    > "$problems_file"

problem_count=$(wc -l < "$problems_file" | tr -d '[:space:]')
[[ "$problem_count" -gt 0 ]] || die "no problems found in $contest_xml"

printf 'Prepared %s\n' "$final_contest_yaml"
printf 'Converting %d problems from %s into %s\n' "$problem_count" "$contest_zip" "$output_dir"
python3 "$script_dir/build-problems.py" \
    "$problems_file" \
    "$tmp_dir/problems" \
    "$tmp_dir/packages" \
    "$output_dir" \
    "$script_dir/materialize-polygon-tests.py" \
    "$job_count" \
    -- \
    "$@"

if [[ ! -f "$final_contest_yaml" ]] || ! cmp -s "$contest_yaml" "$final_contest_yaml"; then
    cp "$contest_yaml" "$final_contest_yaml"
    printf 'Updated %s\n' "$final_contest_yaml"
else
    printf 'Unchanged %s\n' "$final_contest_yaml"
fi

printf 'Done. DOMjudge packages are in %s\n' "$output_dir"
