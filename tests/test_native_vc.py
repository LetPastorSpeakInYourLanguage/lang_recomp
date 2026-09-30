import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))
from lb_worker import native_vc as NV  # noqa: E402


def test_native_path_where_native_voices_exist_else_cloning():
    assert NV.path_for("am", None) == "native_vc"  # the default
    assert NV.path_for("am", "native_vc") == "native_vc"
    assert NV.path_for("am", "clone") == "clone"  # forced everywhere
    assert NV.path_for("fr", None) == "clone"  # no native voices for it yet


def test_every_native_language_has_a_model_and_both_voices():
    for lang, v in NV.NATIVE.items():
        assert v["model"]
        for g in ("female", "male"):
            assert v[g]["file"].startswith("audio/") and v[g]["text"].strip() and v[g]["source"]


def test_ethiopic_punctuation_for_the_voice_model():
    assert NV.fix_punct("የተገናኘንበት, በጣም አስደሳች", "am") == "የተገናኘንበት፣ በጣም አስደሳች።"
    assert NV.fix_punct("ስለራስ ትንሽ ሊነግሩኝ?", "am") == "ስለራስ ትንሽ ሊነግሩኝ?"
    assert NV.fix_punct("አንዲት ታናሽ እህት አለኝ.", "am") == "አንዲት ታናሽ እህት አለኝ።"
    assert NV.fix_punct("እና ከዚያ...", "am") == "እና ከዚያ..."  # trailing off stays so
    assert NV.fix_punct("Hello, world", "en") == "Hello, world"  # other scripts untouched


def test_convert_runs_the_whisper_model_from_the_checkout(tmp_path):
    cmd = [str(c) for c in NV.convert_cmd(tmp_path / "tts", tmp_path / "svc", tmp_path / "m.json", tmp_path / "r.json", 25)]
    assert cmd[1].endswith("svc_batch.py") and cmd[cmd.index("--model") + 1] == "whisper"
    assert cmd[cmd.index("--seedvc") + 1] == str(tmp_path / "svc") and cmd[-1] == "25"
