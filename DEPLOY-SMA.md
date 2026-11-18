# Duplicati deployment (tester-env)

Baseline: `v2.4.1.0_stable_2026-10-29` = `3610feb04738c0619406dfb7421919530fb2ca7e`
(newest non-prerelease release, three weeks old at triage; lightweight tag, so the
SHA is pinned). Source builds from this tree; upstream's ReleaseBuilder image only
copies prebuilt release binaries and is not used.

## Quick start

```bash
./tester-env deploy        # build from source, start, seed, verify
./tester-env seed          # re-run the idempotent seed
./tester-env verify        # SPA shell + auth status + login + seeded state
./tester-env verify-seed   # seeded state only
./tester-env reset         # remove container and data/backup volumes
./tester-env stop          # stop, keep volumes
```

URL `http://localhost:8291/`, browser origin `http://host.docker.internal:8291/`,
password `Duplicati!2026` (override with `DUPLICATI_PASSWORD`).

## Seed data

Deterministic, idempotent, API-only (`tester-env-seed.py`, no browser, no SQL):

- `POST /api/v1/auth/login` with the fixed password.
- `POST /api/v1/backups` per backup below (skipped when the name already exists),
  so the version-locked server database is never shipped as a fixture.
- `POST /api/v1/backup/{id}/run` for the two backups marked "run once", then
  poll `GET /api/v1/task/{id}` until `Completed`.
- Destination folders are created as the `app` user (`docker exec -u app mkdir
  -p`); the file backend reports `folder-missing` until they exist.

Theme: Harborline Studio, a small design studio. Sources are the read-only
`/fixtures` tree baked into the image from `.tester-env-fixtures/`; destinations
are `/backups/<name>/` on the backup volume. Every backup uses the passphrase
`Harborline-Studio-2026`.

| Backup | Source | Destination | Schedule | State |
| --- | --- | --- | --- | --- |
| Studio Documents | `/fixtures/studio-documents/` (excludes `*.tmp`, keep-versions 5) | `file:///backups/studio-documents/` | weekly, first run 2030-01-07 02:00Z | run once: 1 version, 4 of 5 files |
| Project Files | `/fixtures/project-files/` (keep-versions 3) | `file:///backups/project-files/` | monthly, first run 2030-02-01 03:30Z | run once: 1 version, 4 files |
| Photo Archive | `/fixtures/photo-archive/` | `file:///backups/photo-archive/` | none (manual only) | never run: "No version yet" |
| Website Snapshot | `/fixtures/website-snapshot/` | `file:///backups/website-snapshot/` | none (manual only) | never run: "No version yet" |

Fixture files (13 committed, 12 backed up; `old-planning-notes.tmp` is the
excluded one): `studio-handbook.md`, `brand-guidelines.md`,
`contracts/harborline-client-agreement-2026.txt`, `invoices/INV-2026-014.md`,
`harborline-website/{index.html,styles.css}`, `harborline-brand/{palette.md,
type-specimen.txt}`, `shoots/2026-05-lighthouse/README.txt`,
`shoots/2026-09-harbor-day/README.txt`, `portfolio/{index.html,README.txt}`.

Stable, clock-independent oracles: the four backup names, "1 Version" vs
"No version yet", `Source: 1.42 KB` / `832 B` and `Destination: 6.33 KiB` /
`6.31 KiB` on the cards, `SourceFilesCount` 4/4, `TargetFilesCount` 3,
`TargetFilesetsCount` 1, the excluded `*.tmp` file in the Source Data tree, and
the schedule summary "Every week" / "Every month" / manual. Do not assert
"Last successful backup: a few seconds ago", "Next scheduled run: in N years",
or the rendered hour: timestamps and schedule hours are clock- and
browser-timezone-dependent.

Schedule anchors are deliberately years in the future so the built-in scheduler
never fires a backup during an episode (the same reason the seeded backups stay
at one version). `./tester-env verify-seed` asserts the whole table above plus
the fixtures and destination contents.

`verify` = deploy smoke (`/ngclient/login` SPA shell, `/api/v1/auth/status`,
`/api/v1/auth/login`) plus `verify-seed`. `reset` + `deploy` was run twice and
produced identical normalized state (names, sources, settings, schedules,
version counts, source/target metadata, destination file suffixes, fixture
sizes).

## Image

`Dockerfile.tester-env` is fork-owned, three stages:

1. `node:22-alpine` — `npm ci` on `Duplicati/Server/webroot/ngclient/package-lock.json`
   (pins `@duplicati/ngclient@0.0.244`) so the modern SPA can be vendored. A Release
   build serves only `webroot/ngclient/`; the runtime npm download is `#if DEBUG`.
2. `mcr.microsoft.com/dotnet/sdk:10.0` — `dotnet restore` / `dotnet publish
   Executables/Duplicati.Server/Duplicati.Server.csproj -c Release` with a BuildKit
   NuGet cache mount. Only the single executable project is published; the slnx also
   contains proprietary and Windows-only projects.
3. `mcr.microsoft.com/dotnet/aspnet:10.0` — non-root `app` (uid 1654), `/data` and
   `/backups` created `0700` (named volumes inherit that, satisfying Duplicati's
   insecure-datafolder guard without `--allow-insecure-datafolder`), curl healthcheck.

Measured on a 28-core host: cold build 132 s (empty cache), C#-edit rebuild 51 s,
warm reset + deploy + verify 7.5 s. Dependency layers are keyed on the whole source
tree, so any edit costs a restore (cache-mount backed) plus a full compile.

## Determinism

Passed as `DUPLICATI__*` env vars in `docker-compose.tester-env.yml` (argv would
leak the password into `docker ps`):

| Option | Value |
| --- | --- |
| `webservice-interface` / `webservice-port` | `any` / `8200` (host port from `--port`, default 8291) |
| `webservice-password` | fixed `Duplicati!2026` |
| `webservice-suppress-welcome-page` | `true` |
| `webservice-disable-signin-tokens` | `true` |
| `webservice-timezone` | `UTC` |
| `webservice-allowed-hostnames` | `*` (browser container reaches the app by hostname) |
| `server-datafolder` / `DUPLICATI_HOME` | `/data` |
| `disable-update-check`, `reduced-reporting` | `true` |
| `disable-db-encryption` | `true` |

## State and reset

Whole state is the `/data` named volume (embedded SQLite `Duplicati-server.sqlite`,
`installation.txt`, `machineid.txt`, `control_dir_v2`) plus the `/backups` destination
volume. `./tester-env reset` removes the container, both volumes and the network; the
next `deploy` rebuilds the image only if the source changed. Database format is 22 for
this tag, so do not bake a database fixture across releases — seed through the API.

## Evidence

Fork integration 2026-11-18, from a fresh submodule checkout of
`tester-env-baseline` (commit `46cf3de8b8239eb6321b3bdd96fa7b0396e12f21`):

```bash
cd apps/duplicati
IMAGE_TAG=tester-env-duplicati:integrator-check ./tester-env deploy --run-id integrator --port 8391
./tester-env seed --run-id integrator --port 8391    # idempotency re-run
./tester-env reset --run-id integrator --port 8391
```

- `deploy` built from editable source, was healthy in 3s, and passed `verify`
  (`/ngclient/login` SPA shell, `auth/status` `authorized:false`, login token) plus
  `seed` + `verify-seed`: 4 backups created, Studio Documents and Project Files run
  once, version counts 1/1/none/none, schedules 1W/1M/none/none, 7 fixture paths
  present, run destinations populated, never-run destinations empty.
- The second `seed` was a no-op ("already run: Studio Documents / Project Files"),
  so seeding is idempotent.
- `reset` removed only its own container, network and both volumes; the image was
  kept. The default run on port 8291 was left untouched during this check.
- Earlier gates on the same tooling: cold build 132 s, C#-edit rebuild 51 s, warm
  reset+deploy+verify 7.5 s; two reset+deploy cycles reproduced a byte-identical
  normalized seed fingerprint; browser smoke (login + wizard-created backup card)
  passed.

Browser evidence for the seeded state, from browser-checker 2026-11-18 (reported by
the orchestrator; fork-integrator ran no browser): at
`http://host.docker.internal:8291/ngclient/` Home > My backups lists the four
backups, Studio Documents and Project Files show "1 Version", Photo Archive and
Website Snapshot show "No version yet"; Edit backup shows the `/fixtures` source
tree with the `*.tmp` exclusion and the "Every week" / "Every month" schedules.

## Caveats

- The modern UI is a prebuilt npm package, not editable here: no client-side-only
  mutants. Backend (C#) mutants remain observable through the SPA.
- `/api/v1/auth/status` and `/api/v1/auth/login` are POST; `/` always answers 200.
- Access tokens expire after 15 minutes; seeding scripts must re-login.
- `GET /api/v1/backups` wraps each record as `{"Backup": {...}, "Schedule": {...}}`
  and leaves `Sources`/`Settings` empty; read those from `GET /api/v1/backup/{id}`.
- `GET /api/v1/backup/{id}/filesets` answers 400 `No filesets found on remote
  target` for a never-run backup and records a `LastError*` metadata entry, so
  verify uses `LastBackupStarted` and the empty destination for those instead.
- Timestamps are clock-dependent and schedule hours render in the browser
  timezone: assert counts/labels/state chips, not exact times.
- Restore writes inside the container; verify via the UI completion card, not host files.
- `tester-env-duplicati:probe` may exist as a leftover from the rebuild timing probe;
  remove it with `scripts/rl-env gc --prune-images`, never with a direct `docker rmi`.
