# Operations: backup, restore, logs, production

Run from the repo root. `docker compose` picks this clone's project from `.env` or the folder name.

## Backup

```bash
mkdir -p backup
docker compose exec -T postgres pg_dump -U app -d app -Fc > backup/app.dump
docker compose stop rustfs
docker compose run --rm --no-deps -T --entrypoint tar --user root rustfs -C /data -cf - . > backup/files.tar
docker compose start rustfs
cp -p logs/audit/audit.log backup/
```

Copy `backup/` to another machine. It holds user data: do not commit it.

## Restore

Into an empty stack (new clone, or after `make clean`). **This replaces the data.**

```bash
docker compose up -d --wait postgres redis rustfs
docker compose exec -T postgres pg_restore -U app -d app --clean --if-exists < backup/app.dump
docker compose stop rustfs
docker compose run --rm --no-deps -T --entrypoint tar --user root rustfs -C /data -xf - < backup/files.tar
docker compose up -d
```

`init` then migrates the restored data if the code is newer.

## Audit log

`logs/audit/audit.log` grows forever. Rotation example for `/etc/logrotate.d/<project>` (use the full path):

```
/path/to/clone/logs/audit/audit.log {
    weekly
    rotate 12
    compress
    delaycompress
    missingok
    notifempty
    create 0640 1000 1000
    su <owner> <group>
}
```

The app reopens the file by itself, so `copytruncate` is not needed.

## Before production

This repo is a starter. It has no production compose file. Add at least:

- TLS and one public origin in front of the frontend, the API and the file storage (pages on HTTPS cannot upload to `http://...:9000`).
- The client IP: behind a proxy the API sees the proxy's address, so login rate limits and audit IPs need trusted proxy headers.
- A production frontend image (`next build`), no `--reload`, no source mounts.
- Secrets and guards: README_CLONING section 5. `APP_ENV=prod` refuses the defaults.
- No published ports for Postgres, storage console and Mailpit. A real SMTP relay: login uses STARTTLS (port 587); port 465 is not supported.
- Scheduled backups and a restore test.
