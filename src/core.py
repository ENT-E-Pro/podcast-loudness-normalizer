"""Pure two-pass EBU R128 loudness normalization logic (no Apify dependency) so it is unit-testable."""
from __future__ import annotations
import json, math, os, re, subprocess
from dataclasses import dataclass

# preset -> (integrated LUFS target, default LRA target)
PRESETS = {
    "podcast": -16.0,   # Apple Podcasts / general podcast standard
    "apple": -16.0,
    "spotify": -14.0,   # Spotify / YouTube / most streaming
    "youtube": -14.0,
    "ebu-r128": -23.0,  # EBU R128 broadcast
    "atsc-a85": -24.0,  # US broadcast
}
# format -> (extension, ffmpeg codec args, mime)
FORMATS = {
    "wav":  ("wav",  ["-vn", "-c:a", "pcm_s24le"], "audio/wav"),
    "mp3":  ("mp3",  ["-vn", "-c:a", "libmp3lame", "-b:a", "192k"], "audio/mpeg"),
    "m4a":  ("m4a",  ["-vn", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"], "audio/mp4"),
    "flac": ("flac", ["-vn", "-c:a", "flac"], "audio/flac"),
    "mp4":  ("mp4",  ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"], "video/mp4"),
}
MAX_DURATION_DEFAULT = 4 * 3600


class LoudnessError(Exception):
    pass


@dataclass
class Result:
    output_path: str
    ext: str
    mime: str
    input_probe: dict
    output_bytes: int
    output_duration: float | None
    before: dict
    after: dict
    target: dict
    normalization_type: str | None
    passes: int = 1


def probe(path: str) -> dict:
    p = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise LoudnessError(f"Not a readable media file: {p.stderr.strip()[:300]}")
    d = json.loads(p.stdout)
    fmt = d.get("format", {})
    streams = d.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    dur = fmt.get("duration")
    return {
        "format": fmt.get("format_name"),
        "duration": float(dur) if dur not in (None, "N/A") else None,
        "sizeBytes": int(fmt["size"]) if fmt.get("size") else None,
        "video": {"codec": v.get("codec_name"), "width": v.get("width"), "height": v.get("height")} if v else None,
        "audio": {"codec": a.get("codec_name"), "sampleRate": int(a["sample_rate"]) if a.get("sample_rate") else None,
                  "channels": a.get("channels")} if a else None,
    }


def _last_json(stderr: str) -> dict:
    m = list(re.finditer(r"\{[^{}]*\"input_i\"[^{}]*\}", stderr, re.S))
    if not m:
        raise LoudnessError(f"loudnorm produced no measurement: {stderr.strip()[-300:]}")
    return json.loads(m[-1].group(0))


def _num(x) -> float | None:
    try:
        f = float(x)
        return None if math.isinf(f) or math.isnan(f) else round(f, 2)
    except (TypeError, ValueError):
        return None


def measure(path: str, target_i=-16.0, target_tp=-1.0, target_lra=11.0, timeout=3600) -> dict:
    """Pass 1 / verification: measure integrated loudness (LUFS), loudness range (LU), true peak (dBTP)."""
    af = f"loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra}:print_format=json"
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-i", path, "-vn", "-sn", "-dn", "-af", af, "-f", "null", "-"],
                       capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise LoudnessError(f"ffmpeg measurement failed: {p.stderr.strip()[-400:]}")
    return _last_json(p.stderr)


def summarize(m: dict, prefix="input") -> dict:
    return {"integratedLufs": _num(m.get(f"{prefix}_i")), "loudnessRangeLu": _num(m.get(f"{prefix}_lra")),
            "truePeakDbtp": _num(m.get(f"{prefix}_tp")), "thresholdLufs": _num(m.get(f"{prefix}_thresh"))}


def resolve_target(preset: str | None, target_lufs: float | None) -> float:
    preset = (preset or "podcast").lower()
    if preset == "custom":
        if target_lufs is None:
            raise LoudnessError("preset=custom requires targetLufs (e.g. -18)")
        t = float(target_lufs)
    elif preset in PRESETS:
        t = PRESETS[preset]
    else:
        raise LoudnessError(f"Unknown preset '{preset}'. Use one of: {', '.join(list(PRESETS) + ['custom'])}")
    if not -70 <= t <= -5:
        raise LoudnessError("targetLufs must be between -70 and -5 LUFS")
    return t


def normalize(src: str, out_dir: str, output_format: str = "mp3", preset: str = "podcast", target_lufs: float | None = None,
              true_peak: float = -1.0, lra: float = 11.0, sample_rate: int | None = None, channels: int | None = None,
              max_duration: float = MAX_DURATION_DEFAULT, timeout: int = 3600) -> Result:
    fmt = (output_format or "mp3").lower()
    if fmt not in FORMATS:
        raise LoudnessError(f"Unsupported outputFormat '{fmt}'. Use one of: {', '.join(FORMATS)}")
    if not -9 <= float(true_peak) <= 0:
        raise LoudnessError("truePeakDbtp must be between -9 and 0")
    if not 1 <= float(lra) <= 50:
        raise LoudnessError("loudnessRange must be between 1 and 50 LU")
    ti = resolve_target(preset, target_lufs)
    info = probe(src)
    if not info["audio"]:
        raise LoudnessError("Input has no audio stream")
    if fmt == "mp4" and not info["video"]:
        raise LoudnessError("outputFormat=mp4 needs a video input; use m4a for audio-only files")
    if info["duration"] and info["duration"] > max_duration:
        raise LoudnessError(f"Input is {info['duration']:.0f}s, above maxDurationSeconds={max_duration:.0f}")

    m1 = measure(src, ti, true_peak, lra, timeout)
    before = summarize(m1, "input")
    if before["integratedLufs"] is None:
        raise LoudnessError("Input is silent (integrated loudness is -inf); nothing to normalize")
    # loudnorm resamples internally to 192 kHz -> always set an explicit output rate
    sr = int(sample_rate or (info["audio"]["sampleRate"] or 48000))
    sr = min(max(sr, 8000), 192000)
    if fmt == "mp3":
        sr = min(sr, 48000)
    ext, args, mime = FORMATS[fmt]
    # loudnorm's limiter can overshoot the true-peak ceiling after resampling/encoding; verify the encoded
    # file and, if needed, re-render with a tighter internal ceiling (max 2 corrective passes; also nudges the target when dynamic mode under/overshoots by >0.5 LU).
    tp_internal, i_internal = float(true_peak), ti
    best = None  # (score, path, after, m2, passes); true-peak compliance dominates, then distance to target
    for attempt in range(3):
        out = os.path.join(out_dir, f"normalized_{attempt}.{ext}")
        af = (f"loudnorm=I={i_internal}:TP={tp_internal}:LRA={lra}:measured_I={m1['input_i']}:measured_TP={m1['input_tp']}"
              f":measured_LRA={m1['input_lra']}:measured_thresh={m1['input_thresh']}:offset={m1['target_offset']}"
              f":linear=true:print_format=json")
        cmd = ["ffmpeg", "-y", "-hide_banner", "-nostdin", "-i", src, "-map", "0:a:0"]
        if fmt == "mp4":
            cmd += ["-map", "0:v:0"]
        cmd += ["-af", af, "-ar", str(sr)]
        if channels:
            cmd += ["-ac", str(int(channels))]
        cmd += args + [out]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if p.returncode != 0 or not os.path.exists(out) or os.path.getsize(out) == 0:
            raise LoudnessError(f"ffmpeg normalization failed: {p.stderr.strip()[-500:]}")
        m2 = _last_json(p.stderr)
        after = summarize(measure(out, ti, true_peak, lra, timeout), "input")  # verify the actual encoded file
        over = (after["truePeakDbtp"] or -99) - float(true_peak)
        miss = ti - (after["integratedLufs"] if after["integratedLufs"] is not None else ti)
        score = (max(over, 0) * 10 + abs(miss))
        if best is None or score < best[0]:
            if best is not None:
                os.remove(best[1])
            best = (score, out, after, m2, attempt + 1)
        else:
            os.remove(out)
        if over > 0 and tp_internal > -9:  # ceiling first
            tp_internal = max(-9.0, round(tp_internal - over - 0.1, 2))
        elif abs(miss) > 0.5 and abs(i_internal - ti) < 2:  # dynamic-mode undershoot/overshoot: nudge target
            i_internal = round(min(max(i_internal + miss, ti - 2), ti + 2, -5), 2)
        else:
            break
    _, out, after, m2, passes = best
    final = os.path.join(out_dir, f"normalized.{ext}")
    os.replace(out, final); out = final
    out_info = probe(out)
    return Result(out, ext, mime, info, os.path.getsize(out), out_info.get("duration"), before, after,
                  {"integratedLufs": ti, "truePeakDbtp": float(true_peak), "loudnessRangeLu": float(lra)},
                  m2.get("normalization_type"), passes)


BILLING_TOLERANCE_SECONDS = 0.5


def billable_minutes(seconds: float | None) -> int:
    """Per started minute, minimum 1, ignoring up to 0.5 s of encoder/container padding."""
    if not seconds:
        return 1
    return max(1, math.ceil(max(0.0, seconds - BILLING_TOLERANCE_SECONDS) / 60))
