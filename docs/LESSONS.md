# Lessons learned the hard way (read before touching the related code)

**Environment / tooling**
- Git Bash heredocs containing apostrophes inside `python -c "..."` break the whole command
  (nothing runs). Write patch scripts to a file and run them.
- Windows `os.replace` fails with PermissionError while another process reads the target:
  `protocol.write_json` retries; the worker heartbeat never raises.
- Drive for Desktop can fail a read with EINVAL mid-sync: `read_json` treats any OSError as
  "not ready".
- Vite must bind `127.0.0.1` (IPv6-only `localhost` broke the API proxy).
- The in-app browser pane can reach the dev servers started via `.claude/launch.json`.

**Colab**
- Long polling loops get the session terminated → passive notebook (drain, release GPU).
- "Restart session" keeps `/content`: never trust an existing clone; use a `.lb_ready` marker.
- Save progress **per item** (takes written straight into the Drive job folder); a dead runtime
  otherwise loses everything. Logs stream to Drive every heartbeat.
- Fish S2 Pro (5B) needs ~24 GB: runtime dies on free T4 → opt-in only.
- Seed-VC `requirements.txt` pins 2024 versions without Python 3.13 wheels → install the
  imported deps unpinned; patch vendored BigVGAN `_from_pretrained` (`proxies`,
  `resume_download` defaults) for current huggingface_hub.

**Local worker / Arc**
- Intel XPU runtime can hang for minutes at interpreter exit → GPU helper scripts close their
  result file then `os._exit(0)`.
- audio-separator writes models straight to the final name and trusts any existing file →
  route downloads through `deps.fetch` (resume, `.part`, 404 fails fast).
- Slow link (~1 MB/s): download models one at a time via the `prefetch` stage;
  `HF_HUB_DISABLE_XET=1` (Xet CDN failed mid-download).
- pyannote 4 decodes files via torchcodec (needs FFmpeg shared DLLs) → pass the waveform in memory.
- audio-separator needs `audioread` explicitly (newer librosa dropped it).
- XPU separation: overlap 2 ≈ overlap 8 quality (65 dB agreement), 2× faster; fp16/batching no gain.
- Two local workers on one folder would race: stage lists are disjoint by design.

**Pipeline**
- Colab whisper large-v3 (batched) dropped punctuation in the second half of the clip; turbo +
  alignment + boundary rule fixed speaker boundaries.
- A render must delete its previous outputs first, or a failed render lets export use a stale
  mix. Placements past the clip end are cut, not crash.
- Voice job plans snapshot line ids and text: lines merged/re-translated afterwards need
  "Voice missing & changed".
