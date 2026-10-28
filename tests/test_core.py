import os, subprocess, pytest
from src.core import normalize, measure, summarize, probe, LoudnessError, billable_minutes, resolve_target, FORMATS


@pytest.fixture(scope="session")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("m")
    quiet = str(d / "quiet.wav"); loud = str(d / "loud.mp3"); av = str(d / "in.mp4"); silent = str(d / "silent.wav")
    bad = str(d / "bad.bin"); noaudio = str(d / "noaudio.mp4")
    # speech-like modulated noise, quiet (~ -35 LUFS) and loud (~ -8 LUFS)
    src = "anoisesrc=color=pink:sample_rate=44100:amplitude={a}:seed=7,volume='0.6+0.4*sin(2*PI*t*1.3)':eval=frame"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", src.format(a=0.02), "-t", "20", "-ac", "2", quiet], check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", src.format(a=0.9), "-t", "20", loud], check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15", "-f", "lavfi",
                    "-i", src.format(a=0.05), "-t", "15", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", av], check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=44100", "-t", "5", silent], check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10", "-t", "2", "-c:v", "libx264", noaudio], check=True)
    open(bad, "wb").write(os.urandom(2048))
    return locals()


def lufs(path):
    return summarize(measure(path), "input")


@pytest.mark.parametrize("fmt", [f for f in FORMATS if f != "mp4"])
def test_formats_hit_podcast_target(media, tmp_path, fmt):
    r = normalize(media["quiet"], str(tmp_path), fmt, "podcast")
    assert r.before["integratedLufs"] < -25
    assert abs(r.after["integratedLufs"] - (-16)) <= 1.0, r.after
    assert r.after["truePeakDbtp"] <= -1.0, r.after
    assert os.path.getsize(r.output_path) > 0 and r.output_path.endswith(r.ext)


@pytest.mark.parametrize("preset,target", [("spotify", -14), ("ebu-r128", -23)])
def test_presets(media, tmp_path, preset, target):
    r = normalize(media["loud"], str(tmp_path), "wav", preset)
    # very peaky input: the true-peak ceiling takes precedence, so allow 1.5 LU at -14
    assert abs(r.after["integratedLufs"] - target) <= 1.5, r.after
    assert r.after["truePeakDbtp"] <= -1.0


def test_custom_and_true_peak(media, tmp_path):
    r = normalize(media["quiet"], str(tmp_path), "flac", "custom", target_lufs=-19, true_peak=-2)
    assert abs(r.after["integratedLufs"] + 19) <= 1.0 and r.after["truePeakDbtp"] <= -2.0
    assert r.target == {"integratedLufs": -19.0, "truePeakDbtp": -2.0, "loudnessRangeLu": 11.0}


def test_video_to_audio_and_mp4_passthrough(media, tmp_path):
    r = normalize(media["av"], str(tmp_path), "m4a")
    assert probe(r.output_path)["video"] is None
    r2 = normalize(media["av"], str(tmp_path), "mp4", "youtube")
    p = probe(r2.output_path)
    assert p["video"]["codec"] == "h264" and abs(r2.after["integratedLufs"] + 14) <= 1.0


def test_sample_rate_and_mono(media, tmp_path):
    r = normalize(media["quiet"], str(tmp_path), "wav", sample_rate=48000, channels=1)
    a = probe(r.output_path)["audio"]
    assert a["sampleRate"] == 48000 and a["channels"] == 1
    r = normalize(media["quiet"], str(tmp_path), "wav")
    assert probe(r.output_path)["audio"]["sampleRate"] == 44100  # not loudnorm's 192k


def test_errors(media, tmp_path):
    with pytest.raises(LoudnessError): normalize(media["bad"], str(tmp_path))
    with pytest.raises(LoudnessError): normalize(media["silent"], str(tmp_path))
    with pytest.raises(LoudnessError): normalize(media["noaudio"], str(tmp_path))
    with pytest.raises(LoudnessError): normalize(media["quiet"], str(tmp_path), "ogg")
    with pytest.raises(LoudnessError): normalize(media["quiet"], str(tmp_path), "mp4")
    with pytest.raises(LoudnessError): normalize(media["quiet"], str(tmp_path), max_duration=5)
    with pytest.raises(LoudnessError): normalize(media["quiet"], str(tmp_path), preset="custom")
    with pytest.raises(LoudnessError): normalize(media["quiet"], str(tmp_path), true_peak=3)


def test_resolve_and_billing():
    assert resolve_target("apple", None) == -16 and resolve_target("custom", -18) == -18
    assert billable_minutes(None) == 1 and billable_minutes(60) == 1 and billable_minutes(61) == 2
