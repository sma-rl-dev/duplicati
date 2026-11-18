#!/usr/bin/env python3
"""Deterministic Duplicati seed for Harborline Studio.

The Duplicati server database is version-locked (format 22 for the pinned
release tag), so nothing is baked into /data: this script drives the running
instance's REST API from the host. The backed-up source tree is read-only in
the image at /fixtures (see Dockerfile.tester-env) and the destination folders
live on the /backups named volume.

Usage (through the CLI): ./tester-env seed | ./tester-env verify-seed
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

PASSWORD = os.environ.get("DUPLICATI_PASSWORD", "Duplicati!2026")
PASSPHRASE = "Harborline-Studio-2026"

ALL_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# Schedule anchors are deliberately in the future so the built-in scheduler
# never fires a backup during an episode. Oracles use names, version counts and
# schedule labels only - never the computed next-run timestamps.
BACKUPS = [
    {
        "name": "Studio Documents",
        "description": "Contracts, invoices and the studio handbook",
        "target": "file:///backups/studio-documents/",
        "sources": ["/fixtures/studio-documents/"],
        "settings": [
            {"name": "passphrase", "value": PASSPHRASE},
            {"name": "keep-versions", "value": "5"},
        ],
        "filters": [{"order": 0, "include": False, "expression": "*.tmp"}],
        "schedule": {"time": "2030-01-07T02:00:00Z", "repeat": "1W", "allowedDays": ALL_DAYS},
        "run": True,
        "versions": 1,
    },
    {
        "name": "Project Files",
        "description": "Client website sources and brand assets",
        "target": "file:///backups/project-files/",
        "sources": ["/fixtures/project-files/"],
        "settings": [
            {"name": "passphrase", "value": PASSPHRASE},
            {"name": "keep-versions", "value": "3"},
        ],
        "filters": [],
        "schedule": {"time": "2030-02-01T03:30:00Z", "repeat": "1M", "allowedDays": ALL_DAYS},
        "run": True,
        "versions": 1,
    },
    {
        "name": "Photo Archive",
        "description": "Photo shoots archived from the studio camera cards",
        "target": "file:///backups/photo-archive/",
        "sources": ["/fixtures/photo-archive/"],
        "settings": [{"name": "passphrase", "value": PASSPHRASE}],
        "filters": [],
        "schedule": None,
        "run": False,
        "versions": 0,
    },
    {
        "name": "Website Snapshot",
        "description": "Static export of the portfolio site",
        "target": "file:///backups/website-snapshot/",
        "sources": ["/fixtures/website-snapshot/"],
        "settings": [{"name": "passphrase", "value": PASSPHRASE}],
        "filters": [],
        "schedule": None,
        "run": False,
        "versions": 0,
    },
]

FIXTURE_FILES = [
    "/fixtures/studio-documents/studio-handbook.md",
    "/fixtures/studio-documents/contracts/harborline-client-agreement-2026.txt",
    "/fixtures/studio-documents/invoices/INV-2026-014.md",
    "/fixtures/project-files/harborline-website/index.html",
    "/fixtures/project-files/harborline-brand/palette.md",
    "/fixtures/photo-archive/shoots/2026-05-lighthouse/README.txt",
    "/fixtures/website-snapshot/portfolio/index.html",
]


def api(base_url: str, method: str, path: str, body=None, token: str | None = None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(base_url.rstrip("/") + path, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        message = exc.read().decode(errors="replace")
        raise SystemExit(f"Error: {method} {path} -> {exc.code}: {message}")
    return json.loads(raw) if raw else None


def api_read(base_url: str, path: str, token: str):
    """GET that returns the parsed body for 2xx and None for 4xx, so callers can
    treat an expected client error as "nothing there" (e.g. an empty remote)."""
    request = urllib.request.Request(base_url.rstrip("/") + path, method="GET")
    request.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
    except urllib.error.HTTPError:
        return None
    return json.loads(raw) if raw else None


def login(base_url: str) -> str:
    return api(base_url, "POST", "/api/v1/auth/login", {"Password": PASSWORD, "RememberMe": False})["AccessToken"]


def backup_list(base_url: str, token: str) -> list[dict]:
    # The list endpoint wraps each record as {"Backup": {...}, "Schedule": {...}};
    # sources/settings are only populated on GET /api/v1/backup/{id}.
    return [entry["Backup"] for entry in api(base_url, "GET", "/api/v1/backups", token=token)]


def backup_detail(base_url: str, token: str, backup_id: str) -> dict:
    return api(base_url, "GET", f"/api/v1/backup/{backup_id}", token=token)


def filesets(base_url: str, token: str, backup_id: str) -> list[dict]:
    # An empty destination answers 400 (EmptyRemoteFolder); that is 0 versions.
    return api_read(base_url, f"/api/v1/backup/{backup_id}/filesets", token) or []


def backup_log(base_url: str, token: str, backup_id: str) -> list[dict]:
    return api_read(base_url, f"/api/v1/backup/{backup_id}/log", token) or []


def run_backup(base_url: str, token: str, backup_id: str) -> None:
    task = api(base_url, "POST", f"/api/v1/backup/{backup_id}/run", token=token)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        state = api(base_url, "GET", f"/api/v1/task/{task['ID']}", token=token)
        status = str(state["Status"]).lower()
        if status == "completed":
            return
        if status == "failed":
            raise SystemExit(f"Error: backup task {task['ID']} failed: {state.get('ErrorMessage') or state.get('Exception')}")
        time.sleep(0.5)
    raise SystemExit(f"Error: backup task {task['ID']} did not finish within 180s")


def create_payload(spec: dict) -> dict:
    body = {
        "Backup": {
            "Name": spec["name"],
            "Description": spec["description"],
            "TargetURL": spec["target"],
            "Sources": spec["sources"],
            "Settings": spec["settings"],
            "Filters": spec["filters"],
            "Metadata": {},
        },
        "Schedule": None,
    }
    if spec["schedule"]:
        body["Schedule"] = {
            "Time": spec["schedule"]["time"],
            "Repeat": spec["schedule"]["repeat"],
            "AllowedDays": spec["schedule"]["allowedDays"],
        }
    return body


def docker_exec(container: str, command: str) -> str:
    result = subprocess.run(["docker", "exec", container, "sh", "-c", command], capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"Error: docker exec {container} {command} -> {result.stderr.strip()}")
    return result.stdout


def ensure_destination(container: str, target: str) -> None:
    # The file backend reports folder-missing until the target folder exists.
    # The Add-backup wizard creates it with "Create folder"; the seed does the
    # same as the app user so listing versions works before the first run.
    path = target[len("file://"):]
    result = subprocess.run(["docker", "exec", "-u", "app", container, "mkdir", "-p", path],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"Error: could not create {path} in {container}: {result.stderr.strip()}")


def cmd_seed(base_url: str, container: str) -> int:
    token = login(base_url)
    existing = {b["Name"]: b for b in backup_list(base_url, token)}

    for spec in BACKUPS:
        ensure_destination(container, spec["target"])
        if spec["name"] in existing:
            print(f"    backup present: {spec['name']}")
            continue
        created = api(base_url, "POST", "/api/v1/backups", create_payload(spec), token=token)
        existing[spec["name"]] = {"ID": created["ID"], "Name": spec["name"]}
        print(f"    backup created: {spec['name']}")

    for spec in BACKUPS:
        if not spec["run"]:
            continue
        backup = existing[spec["name"]]
        if backup_log(base_url, token, backup["ID"]):
            print(f"    already run:     {spec['name']}")
            continue
        run_backup(base_url, token, backup["ID"])
        print(f"    backup run:      {spec['name']}")

    print("==> Seed complete.")
    return 0


def fail(message: str) -> None:
    raise SystemExit(f"Error: {message}")


def cmd_verify(base_url: str, container: str) -> int:
    token = login(base_url)
    backups = backup_list(base_url, token)
    by_name = {b["Name"]: b for b in backups}

    expected_names = [spec["name"] for spec in BACKUPS]
    if sorted(by_name) != sorted(expected_names):
        fail(f"backup list is {sorted(by_name)}, expected {sorted(expected_names)}")
    print(f"    backups:  {len(backups)} ({', '.join(expected_names)})")

    for spec in BACKUPS:
        listed = by_name[spec["name"]]
        detail = backup_detail(base_url, token, listed["ID"])
        backup = detail["Backup"]

        if backup["TargetURL"] != spec["target"]:
            fail(f"{spec['name']} target is {backup['TargetURL']}, expected {spec['target']}")
        if backup["Sources"] != spec["sources"]:
            fail(f"{spec['name']} sources are {backup['Sources']}, expected {spec['sources']}")

        schedule = detail.get("Schedule")
        if spec["schedule"] is None:
            if schedule is not None:
                fail(f"{spec['name']} should have no schedule, got {schedule}")
        else:
            if schedule is None:
                fail(f"{spec['name']} is missing its schedule")
            if schedule["Repeat"] != spec["schedule"]["repeat"]:
                fail(f"{spec['name']} repeat is {schedule['Repeat']}, expected {spec['schedule']['repeat']}")

        if spec["versions"]:
            versions = len(filesets(base_url, token, listed["ID"]))
            if versions != spec["versions"]:
                fail(f"{spec['name']} has {versions} versions, expected {spec['versions']}")
            if "LastBackupStarted" not in (backup["Metadata"] or {}):
                fail(f"{spec['name']} has versions but no recorded backup run")
        else:
            # Listing filesets on a never-run backup writes a LastError metadata
            # entry, so the empty destination below is the evidence instead.
            if "LastBackupStarted" in (backup["Metadata"] or {}):
                fail(f"{spec['name']} should not have been run yet")
    print("    versions: " + ", ".join(f"{s['name']}={'1' if s['run'] else 'none (never run)'}" for s in BACKUPS))
    print("    schedules: " + ", ".join(f"{s['name']}={s['schedule']['repeat'] if s['schedule'] else 'none'}" for s in BACKUPS))

    documents = backup_detail(base_url, token, by_name["Studio Documents"]["ID"])["Backup"]
    keep_versions = {x["Name"]: x["Value"] for x in documents["Settings"] or []}.get("keep-versions")
    if keep_versions != "5":
        fail(f"Studio Documents keep-versions is {keep_versions}, expected 5")

    for path in FIXTURE_FILES:
        docker_exec(container, f"test -f {path}")
    print(f"    fixtures: {len(FIXTURE_FILES)} source files present in the container")

    for spec in BACKUPS:
        destination = spec["target"][len("file://"):]
        listing = docker_exec(container, f"ls -A {destination}").strip()
        if spec["run"] and not listing:
            fail(f"destination {destination} is empty")
        if not spec["run"] and listing:
            fail(f"destination {destination} should be empty before its first run")
    print("    destinations: run backups hold files, never-run destinations are empty")

    print("==> Seed verify passed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Duplicati tester-env seed and seed verification.")
    parser.add_argument("command", choices=["seed", "verify"])
    parser.add_argument("--base-url", default=os.environ.get("BASE_URL", "http://127.0.0.1:8291"))
    parser.add_argument("--container", default=os.environ.get("CONTAINER_NAME", "tester-env-duplicati"))
    args = parser.parse_args()
    return cmd_seed(args.base_url, args.container) if args.command == "seed" else cmd_verify(args.base_url, args.container)


if __name__ == "__main__":
    sys.exit(main())
