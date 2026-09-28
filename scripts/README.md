# RUPC Build Scripts

## Contest build script usage

```sh
CONTEST_ID="contestid" \
CONTEST_START_TIME="2026-10-24T10:00:00" \
CONTEST_END_TIME="2026-10-24T15:00:00" \
./scripts/build-contest.sh contest-zip-file.zip
```

This outputs all the problem packages and contest data in domjudge-packages/
Set both times when creating a contest. Times are local to `America/New_York`;
the build writes the correct Eastern UTC offset for each date and calculates
the contest duration. A time during the repeated hour when daylight saving
time ends needs an explicit `-04:00` or `-05:00` offset. A time during the
skipped hour when daylight saving time begins is rejected.
Polygon C++ generators and solutions are compiled with G++ from
`domjudge/judgehost:9.0.0` (G++ 13.3.0), so Docker must be available when building
packages that need this step. Set `DOMJUDGE_GXX_IMAGE` to match a different
judgehost image if your DOMjudge version changes. The `domserver` image does not
include G++.

## Contest upload script usage

```sh
 ./scripts/upload-contest.py domjudge-packages/ --api-url http://localhost/api/v4 --user admin --password '<admin password>'
```

Creating a contest requires `start_time` and `end_time` in `contest.yaml`.
Pass `--update` to update existing packages without changing the contest's
schedule. If `--update` creates a missing contest, the times are required.
