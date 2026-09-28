# RUPC Build Scripts

## Contest build script usage

```sh
CONTEST_ID="contestid" ./scripts/build-contest.sh contest-zip-file.zip
```

This outputs all the problem packages and contest data in domjudge-packages/
Polygon C++ generators and solutions are compiled with G++ from
`domjudge/judgehost:9.0.0` (G++ 13.3.0), so Docker must be available when building
packages that need this step. Set `DOMJUDGE_GXX_IMAGE` to match a different
judgehost image if your DOMjudge version changes. The `domserver` image does not
include G++.

## Contest upload script usage

```sh
 ./scripts/upload-contest.py domjudge-packages/ --api_url http://localhost/api/v4 --user admin --password '<admin password>'
```

Pass `--update` to update existing packages instead of creating a new contest.
