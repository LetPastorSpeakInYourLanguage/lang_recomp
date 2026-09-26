# Team hub (approved 2026-09-26): shared metadata, media on everyone's devices, compute where the media is

## Context

Libraries, runs and packages now let one person catalogue folders (Drive or local disks)
and run the pipeline on a chosen device. The owner wants **teams**: a coordinator (the
team's creator) and members who each hold *part* of the media — on their own PC/disk or
their own Drive — yet **everyone sees the metadata of every media being worked on**
(works, lines, cast, translations, run state). Members can add media, place a file in the
designated folder or **locate it on their device** (a script copies it into their working
folder), preview it, and take part fully. For now the central metadata lives on the
**coordinator's PC** (members reach it by IP); later it moves to a server. Compute stays
**distributed**: each device runs the work on the media it has.

## Shape

```
          members' apps ── metadata (read/write, token) ──►  HUB = coordinator's app in hub mode
   (UI = the same web app)                                    · the one library DB (works, lines, cast,
        │                                                        translations, runs, members, devices)
        ├─ local services (never proxied):                    · media registry: every media + where
        │   media playback, locate/copy a file,                  copies of it are (device, path)
        │   folder scan, run on this device                   · run queue addressed to devices
        └─ its devices: this PC (local worker), its Drive (Colab)
```

- **One codebase, three modes** of `python -m app`: `solo` (today), `hub` (serves the API
  on the LAN, members + tokens), `member --hub http://<ip>:8765 --token …` (the local app
  forwards metadata calls to the hub; serves media, locating, scanning and runs itself).
  The web UI is unchanged: it always talks to its own local app.
- **Media identity by content**: `media(uid, qhash, size, duration, name, kind)` —
  `qhash` = SHA-256 of size + first 4 MB + last 4 MB (fast, same for every copy);
  `media_copies(media_uid, device_uid, path, state present|missing, seen)`. A source
  (project) points at a media uid instead of one path. Playback, runs and scans resolve
  *this device's* copy; "not on this device" offers **Locate** (pick the file → hash
  must match → copy into the device's working folder → registered) or **Fetch** (from the
  team Drive folder when a copy is there).
- **Devices**: `devices(uid, member, name, roots)` — a member's PC (local worker folder +
  working folder) and their Drive (Colab job folder). Library folders belong to a device.
- **Adding media**: a member adds a file or a folder on their device (scan = catalogue +
  qhash) → metadata registered at the hub; the file stays with them (or they drop it in
  the team's designated Drive folder, per docs/LIBRARY_FOLDERS.md).
- **Distributed compute**: a run is addressed to a device that holds the media. The hub
  queues it; that member's app picks it up (`GET /api/team/runs?device=…`), exports the
  work from the hub (packages with media `ref` against *its* device roots), runs it through
  its own worker/Colab exactly as runs do now, and uploads `results/*.lbwork` to the hub,
  which imports them (manual truth, by uid). Outputs stay on the device that made them and
  are registered as copies (a dubbed MP4 can be pushed to the team Drive folder to share).
- **Manual truth + versions**: every metadata row already has uids/provenance; hub writes
  carry the member and a row `version` (409 on stale write) so two editors cannot silently
  overwrite each other; edits are attributed (op log: who, what, when).
- **Later server**: the hub is the same FastAPI app; moving it to a server = run hub mode
  there (Postgres later), members change `--hub`.

## Steps

0. **Finish the execution path first** (in flight): App fetches the open project's full
   summary (lists are brief now); Libraries screen (add folder, scan, explore tree, load
   subtitles, select → run on device), Runs panel (status, open results); notebook text +
   publishing `app/` to Drive; first real Colab run (6 Minute English, a PCDL sample).
1. **Media identity**: `media`, `media_copies`, qhash in scans/imports; sources get
   `media_uid`; resolve-this-device's-copy used by playback, runs, packages.
2. **Devices & modes**: `devices` table, `--mode hub|member`, member proxy (forward
   `/api/*` except local services), tokens, members list/invite link (coordinator only).
3. **Locate & fetch**: file picker path → hash check → copy into the working folder
   (resumable copy, progress) → copy registered; Fetch from team Drive.
4. **Distributed runs**: hub run queue by device; member app picks up, runs, uploads
   results; hub imports; run board for the coordinator (who runs what where).
5. **Edit safety**: row versions + op log on hub writes; UI shows who changed what.

## Files

- New: `app/media.py` (identity, copies, resolve, locate/copy), `app/team.py` (members,
  devices, tokens, hub run queue, result upload), `app/remote.py` (member → hub proxy),
  `docs/TEAM.md`, screens `Libraries.tsx`, `Team.tsx`, `Runs` panel.
- Change: `app/main.py` (modes), `app/api.py` (team routes, token check, media routes
  resolving device copies), `app/libraries.py` (qhash, device), `app/runs.py` (device-
  addressed runs), `app/package.py` (media uids), `app/db.py`.

## Verification

- Tests: qhash equal across copies / different for different files; locate refuses a
  wrong file; two apps in one test (hub on a temp DB + a member proxying to it via
  TestClient) — member edits land in the hub, a stale write gets 409, the member's run
  results appear in the hub; media resolution picks this device's copy.
- Real: hub on this PC; a second app instance as a member (`--data` sandbox, own device
  folder) on the same PC: add a folder, locate a file, run, see the results at the hub.
