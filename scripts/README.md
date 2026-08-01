# RUPC Build Scripts

## Contest build script usage

```sh
CONTEST_ID="contestid" ./scripts/build-contest.sh contest-zip-file.zip
```

This outputs all the problem packages and contest data in domjudge-packages/

## Contest upload script usage

```sh
 ./scripts/upload-contest.py domjudge-packages/ --api_url http://localhost/api/v4 --user admin --password '<admin password>'
```

Pass `--update` to update existing packages instead of creating a new contest.
