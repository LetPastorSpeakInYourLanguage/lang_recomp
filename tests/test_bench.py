"""The certification benches (E1 GPU, E2 identity) measure what they claim: checked here
on synthetic audio and video, with the models stood in for (no GPU on this machine)."""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pytest
from scipy.io import wavfile

from app import fingerprint as fp
from tests.test_fingerprint import SR, chords

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))
from lb_worker.bench import common, gpu, identity  # noqa: E402


def _wav(path: Path, x: np.ndarray, sr: int = SR) -> Path:
    wavfile.write(path, sr, (x / np.abs(x).max() * 20000).astype(np.int16))
    return path


def _video(path: Path, audio: Path) -> Path:
    common.ffmpeg("-f", "lavfi", "-i", "color=c=gray:s=320x240:r=10", "-i", str(audio), "-shortest",
                  "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-b:a", "128k", str(path))
    return path


def test_nvidia_smi_lines_are_read_and_a_machine_without_a_gpu_reports_nothing():
    assert common.parse_smi("0, 37, 2560, 15360") == (0, 37.0, 2.5, 15.0)
    assert common.parse_smi("garbage") is None and common.parse_smi("0, N/A, 1, 2") is None
    s = common.GpuSampler()
    s.samples = [(0, 10.0, 2.0, 15.0), (0, 30.0, 6.0, 15.0), (1, 50.0, 1.0, 15.0)]
    st = s.stats()
    assert st["0"] == {"util_mean": 20.0, "util_max": 30.0, "mem_max_gb": 6.0, "mem_total_gb": 15.0}
    assert st["1"]["util_mean"] == 50.0


def test_windows_counters_give_the_busiest_engine_and_the_memory_in_use():
    header = ["(PDH-CSV 4.0)",
              r"\\pc\GPU Engine(pid_1_luid_0x0_0x1_phys_0_eng_0_engtype_compute)\Utilization Percentage",
              r"\\pc\GPU Engine(pid_2_luid_0x0_0x1_phys_0_eng_0_engtype_compute)\Utilization Percentage",
              r"\\pc\GPU Engine(pid_1_luid_0x0_0x1_phys_0_eng_1_engtype_3d)\Utilization Percentage",
              r"\\pc\GPU Adapter Memory(luid_0x0_0x1_phys_0)\Shared Usage",
              r"\\pc\GPU Adapter Memory(luid_0x0_0x1_phys_0)\Dedicated Usage"]
    row = ["09/27/2026 20:00:00.000", "40.5", "30.0", "6.0", str(3 * 2**30), str(2**30)]
    assert common.parse_typeperf(header, row, 7.7) == (0, 70.5, 4.0, 7.7)  # two processes on one engine
    assert common.parse_typeperf(header, ["t", " ", " ", " ", " ", " "], 7.7) is None


def test_differences_are_measured_in_db():
    x = np.random.default_rng(0).standard_normal((44100, 2)).astype(np.float32)
    assert common.diff_db(x, x) < -100
    assert common.diff_db(x, 0.5 * x) == pytest.approx(-6.0, abs=0.1)  # the error is half the signal
    assert common.snr_db(x, x + 0.01 * x) == pytest.approx(40.0, abs=0.1)
    assert "setting" in common.table([{"setting": "batch 1", "s": 3}], ["setting", "s"])


def test_quick_hash_is_equal_for_copies_and_reads_only_the_ends(tmp_path):
    data = bytearray(np.random.default_rng(1).integers(0, 256, 10 << 20, dtype=np.uint8).tobytes())
    a, b = tmp_path / "a.bin", tmp_path / "b.bin"
    a.write_bytes(data)
    b.write_bytes(data)
    assert identity.quick_hash(a) == identity.quick_hash(b)
    data[5 << 20] ^= 1  # the middle is not read: by design (8 MB at most, even on Drive)
    b.write_bytes(data)
    assert identity.quick_hash(a) == identity.quick_hash(b)
    data[-1] ^= 1
    b.write_bytes(data)
    assert identity.quick_hash(a) != identity.quick_hash(b)
    b.write_bytes(bytes(data) + b"x")
    assert identity.quick_hash(a) != identity.quick_hash(b)


def test_fpcalc_raw_output_is_read_as_unsigned_either_way():
    assert fp.parse_raw("1,-1,4294967295, 7").tolist() == [1, 4294967295, 4294967295, 7]
    assert len(identity.link_forms("abc")) == 5


def test_a_variant_is_found_with_its_offset_and_other_audio_is_not(tmp_path):
    src = chords(11, 120)
    other = chords(12, 120)
    source_fp = fp.compute(_wav(tmp_path / "src.wav", src))
    trimmed = fp.compute(_wav(tmp_path / "trim.wav", src[10 * SR:]))
    intro = fp.compute(_wav(tmp_path / "intro.wav", np.concatenate([other[:7 * SR], src])))
    off, bits = identity.match(trimmed, source_fp)
    assert off == pytest.approx(10.0, abs=0.25) and bits < 5
    off, bits = identity.match(intro, source_fp)
    assert off == pytest.approx(-7.0, abs=0.25) and bits < 5
    _, bits = identity.match(fp.compute(_wav(tmp_path / "other.wav", other)), source_fp)
    assert bits > 10


def test_the_identity_bench_runs_end_to_end_on_small_videos(tmp_path):
    main = _video(tmp_path / "main.mp4", _wav(tmp_path / "m.wav", chords(21, 100)))
    other = _video(tmp_path / "other.mp4", _wav(tmp_path / "o.wav", chords(22, 100)))
    neg = _video(tmp_path / "neg.mp4", _wav(tmp_path / "n.wav", chords(23, 100)))
    res = identity.run([{"name": "m", "video": main, "redownload": None, "other": other, "links": []}],
                       [neg], tmp_path / "out", log=lambda *_: None)
    assert res["all_offsets_ok"] and res["quick_hash_only_for_copy"] and res["separated"], res
    assert {r["variant"] for r in res["rows"]} == {"copy", "reencode", "mp3", "trim10", "intro7"}
    assert json.loads((tmp_path / "out" / "e2_identity.json").read_text(encoding="utf-8"))["method"] in ("ffmpeg", "fpcalc")


def test_excerpts_and_their_opus_copies_are_prepared_from_files(tmp_path):
    src = _wav(tmp_path / "talk.wav", chords(31, 40))
    items = gpu.prepare([str(src)], tmp_path / "b", seconds=20, start=5, log=lambda *_: None)
    it = items[0]
    assert it["seconds"] == pytest.approx(20, abs=0.1)
    assert all(Path(it[k]).exists() for k in ("wav", "opus160", "opus96"))


def test_the_separation_bench_picks_the_fastest_setting_that_changes_nothing(tmp_path, monkeypatch):
    from lb_worker.stages import analysis

    x = chords(41, 6)
    items = [{"name": "00", "wav": str(_wav(tmp_path / "e.wav", x, 44100)), "seconds": 6.0}]

    class Sep:
        def __init__(self, batch_size, autocast, native_fp16):
            self.b, self.half = batch_size, autocast or native_fp16

    def load(model, overlap, log, batch_size=1, autocast=False, native_fp16=False):
        if batch_size >= 16 and not (autocast or native_fp16):
            raise RuntimeError("CUDA out of memory")
        return Sep(batch_size, autocast, native_fp16)

    def separate(sep, src, tmp, dest, log):
        time.sleep(1.0 / sep.b)  # far apart, so timer noise cannot reorder them
        y = x + (0.05 * np.random.default_rng(sep.b).standard_normal(len(x)) if sep.half else 0)  # half precision: audible
        dest.mkdir(parents=True, exist_ok=True)
        _wav(dest / "vocals.flac", y, 44100)  # WAV bytes: ffmpeg reads by content

    monkeypatch.setattr(analysis, "load_separator", load)
    monkeypatch.setattr(analysis, "separate_file", separate)
    res = gpu.bench_separation(items, tmp_path / "out", log=lambda *_: None)
    rows = {r["setting"]: r for r in res["rows"]}
    assert "error" in rows["batch 16"] and rows["batch 1"]["vs_baseline_db"] is None
    assert not rows["batch 8 +autocast"]["same_result"]
    assert res["best"] == "batch 8"
