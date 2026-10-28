"""Apify Actor entrypoint: Podcast Loudness Normalizer (two-pass FFmpeg loudnorm), pay-per-event."""
import asyncio, os, tempfile, uuid
import httpx
from apify import Actor
from .core import normalize, LoudnessError, billable_minutes

MAX_DOWNLOAD = 2 * 1024**3


async def download(url: str, dest: str) -> None:
    if not str(url).startswith(("http://", "https://")):
        raise LoudnessError("url must be an http(s) URL")
    async with httpx.AsyncClient(follow_redirects=True, timeout=120) as c:
        async with c.stream("GET", url) as r:
            r.raise_for_status()
            n = 0
            with open(dest, "wb") as f:
                async for chunk in r.aiter_bytes(1 << 20):
                    n += len(chunk)
                    if n > MAX_DOWNLOAD:
                        raise LoudnessError("File larger than 2 GB limit")
                    f.write(chunk)


async def main() -> None:
    async with Actor:
        inp = await Actor.get_input() or {}
        files = list(inp.get("files") or [])
        if inp.get("url"):
            files.append({"url": inp["url"]})
        if not files:
            raise ValueError("Provide 'url' or 'files' [{url, ...}]")
        defaults = {
            "preset": inp.get("preset", "podcast"),
            "targetLufs": inp.get("targetLufs"),
            "truePeakDbtp": inp.get("truePeakDbtp", -1.0),
            "loudnessRange": inp.get("loudnessRange", 11),
            "outputFormat": inp.get("outputFormat", "mp3"),
            "sampleRate": inp.get("sampleRate"),
            "channels": inp.get("channels"),
        }
        max_dur = float(inp.get("maxDurationSeconds", 14400))
        kvs = await Actor.open_key_value_store()
        for item in files:
            item = item if isinstance(item, dict) else {"url": item}
            o = {**defaults, **{k: v for k, v in item.items() if v is not None and k != "url"}}
            url = item.get("url")
            row = {"sourceUrl": url, "preset": o["preset"], "outputFormat": o["outputFormat"]}
            with tempfile.TemporaryDirectory() as td:
                try:
                    src = os.path.join(td, "input")
                    await download(url, src)
                    ch = {"mono": 1, "stereo": 2}.get(str(o["channels"]).lower()) if o["channels"] not in (None, "", "keep") else None
                    res = await asyncio.to_thread(
                        normalize, src, td, o["outputFormat"], o["preset"], o["targetLufs"], float(o["truePeakDbtp"]),
                        float(o["loudnessRange"]), o["sampleRate"], ch, max_dur)
                    key = f"{uuid.uuid4().hex[:12]}.{res.ext}"
                    with open(res.output_path, "rb") as f:
                        await kvs.set_value(key, f.read(), content_type=res.mime)
                    minutes = billable_minutes(res.input_probe.get("duration") or res.output_duration)
                    row.update(status="ok", outputKey=key, outputUrl=await kvs.get_public_url(key), mime=res.mime,
                               outputBytes=res.output_bytes, outputDurationSeconds=res.output_duration,
                               target=res.target, before=res.before, after=res.after,
                               beforeLufs=res.before["integratedLufs"], afterLufs=res.after["integratedLufs"],
                               afterTruePeakDbtp=res.after["truePeakDbtp"],
                               gainAppliedDb=round(res.after["integratedLufs"] - res.before["integratedLufs"], 2)
                               if res.after["integratedLufs"] is not None else None,
                               normalizationType=res.normalization_type, renderPasses=res.passes,
                               truePeakCompliant=(res.after["truePeakDbtp"] or -99) <= res.target["truePeakDbtp"], input=res.input_probe, billedMinutes=minutes)
                    r = await Actor.charge(event_name="file-normalized", count=1)
                    r = await Actor.charge(event_name="audio-minute", count=minutes)
                    await Actor.push_data(row)
                    if getattr(r, "event_charge_limit_reached", False):
                        Actor.log.info("Spending limit reached; stopping.")
                        break
                except Exception as e:  # never-fail: error rows are free
                    row.update(status="error", error=str(e)[:500])
                    await Actor.push_data(row)
