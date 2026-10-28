# Podcast Loudness Normalizer (LUFS, True Peak) for AI Agents

The Loudness Normalization API from ENT-E turns any podcast, voice or video file URL into a broadcast-grade file at -16, -14, -23 or -24 LUFS, with a true-peak ceiling, so every episode meets platform specs automatically, with no DAW, plugins or ffmpeg setup.

## Loudness normalization API: hit platform LUFS targets in one call

Send one URL, or a whole batch. Pick a preset (`podcast`, `apple`, `spotify`, `youtube`, `ebu-r128`, `atsc-a85`) or set your own target. You get back a normalized MP3, M4A, WAV, FLAC or MP4 file, plus a before/after loudness report you can log, check or show to a client.

How it works:
1. The Actor measures the whole file first (two-pass EBU R128 loudness normalization with FFmpeg's `loudnorm`, linear mode where possible).
2. It applies gain with a 4× oversampled true-peak limiter.
3. It **re-measures the encoded file** and re-renders when the ceiling or target is missed, up to 3 attempts. The row you receive reports the file that was actually delivered.

## What you get

- **Platform presets with fixed targets**:

  | `preset` | Integrated loudness |
  |---|---|
  | `podcast`, `apple` | -16 LUFS |
  | `spotify`, `youtube` | -14 LUFS |
  | `ebu-r128` | -23 LUFS |
  | `atsc-a85` | -24 LUFS |
  | `custom` | your `targetLufs` (-70 to -5) |

  The true-peak ceiling defaults to -1 dBTP (`truePeakDbtp`) and the loudness range to 11 LU (`loudnessRange`).
- **Measured, not assumed.** Every row includes `beforeLufs`, `afterLufs`, `afterTruePeakDbtp`, `gainAppliedDb` and `truePeakCompliant`, plus full `before`/`after` objects with integrated loudness, loudness range and true peak.
- **Output formats**:
  - `mp3` (192 kbps), the default
  - `m4a` (AAC 192 kbps)
  - `wav` (24-bit)
  - `flac`
  - `mp4`, which copies the video stream and re-encodes the audio to AAC, so you can normalize a video podcast without re-rendering the picture
- **Batch.** Use `files` for many episodes in one run. Any setting can be overridden per file.
- **Failed files are free.** A bad URL, a silent file, an audio-free input or an over-length file returns an error row and isn't charged.

## Read this first: true peak beats the target

The true-peak ceiling always takes priority over the loudness target. For loud, very peaky audio, reaching -14 LUFS on the `spotify` or `youtube` preset can be impossible without crossing the -1 dBTP ceiling. In that case the Actor keeps the ceiling and lets the file land a little below -14 LUFS. You still get a clean, non-clipping file, and the row tells you exactly what happened: the measured `afterLufs`, `truePeakCompliant: true`, and `normalizationType: "dynamic"`. No row will claim -14.0 LUFS if the file isn't at -14.0 LUFS. In our tests, integrated loudness typically lands within ±0.5 LU of the target.

## Use cases

### Normalize audio to LUFS for a podcast feed (-16 LUFS)

Apple Podcasts and most podcast hosts recommend around -16 LUFS. This is the default.

```json
{
  "url": "https://example.com/episodes/ep-142-raw.wav",
  "preset": "podcast",
  "outputFormat": "mp3"
}
```

### Spotify -14 LUFS and YouTube loudness

```json
{
  "url": "https://example.com/episodes/ep-142-master.wav",
  "preset": "spotify",
  "truePeakDbtp": -1
}
```

For a video podcast going to YouTube, keep the picture and fix only the audio:

```json
{
  "url": "https://example.com/video/ep-142.mp4",
  "preset": "youtube",
  "outputFormat": "mp4"
}
```

### Apple Podcasts loudness with a stricter true-peak limiter

Some distributors ask for -2 dBTP or lower to leave headroom for lossy encoders.

```json
{
  "url": "https://example.com/episodes/ep-142.wav",
  "preset": "apple",
  "truePeakDbtp": -2,
  "outputFormat": "m4a"
}
```

### EBU R128 and ATSC A/85 for broadcast delivery

```json
{
  "url": "https://example.com/broadcast/segment-07.wav",
  "preset": "ebu-r128",
  "outputFormat": "wav",
  "sampleRate": 48000
}
```

Use `"preset": "atsc-a85"` for -24 LUFS (US broadcast). For anything else, use `"preset": "custom"` with `"targetLufs": -18`.

### Batch normalize audio for a whole back catalog

Top-level settings are the defaults, and each item in `files` can override them. Plain URL strings work too.

```json
{
  "preset": "podcast",
  "outputFormat": "mp3",
  "channels": "mono",
  "files": [
    "https://example.com/episodes/ep-001.mp3",
    "https://example.com/episodes/ep-002.mp3",
    { "url": "https://example.com/promos/trailer.wav", "preset": "spotify", "outputFormat": "wav" }
  ]
}
```

Files are processed one after another in the same run. Each one gets its own dataset row.

## Pricing (pay per event)

| Event | Price |
|---|---|
| File normalized (per successful file) | $0.01 |
| Audio minute (per started minute of **input** audio) | $0.008 |
| Actor start (per run, one event per GB of memory, minimum one; default 4 GB = 4 events) | $0.00005 per event |

There are no platform usage fees on top (compute is included). Failed files are free.

**Worked example: a weekly one-hour show**
- One 60-minute episode: $0.01 + 60 × $0.008 = **$0.49**.
- One year of episodes (52) in one batch run: 52 × $0.49 = **$25.48**, plus $0.0002 actor start.
- A 59 min 13 s recording counts as 60 started minutes, so it is also $0.49.
- A 30-second promo: $0.01 + 1 × $0.008 = **$0.018**.

Billing counts **started** minutes of the input file, rounded up, with a minimum of 1. Up to 0.5 s of container padding is ignored, so a 60 min 00.4 s file counts as 60 minutes, while 60 min 01 s counts as 61 ($0.498). Set a spending limit on the run to cap the total; the Actor stops cleanly when the limit is reached.

## Input reference

| Field | Type | Default | Notes |
|---|---|---|---|
| `url` | string | (none) | Direct link to one audio or video file. Any FFmpeg-readable format, up to 2 GB. The first audio stream is normalized. |
| `files` | array | (none) | Batch. Items are `{ "url": ..., <any setting below> }` or plain URL strings. |
| `preset` | string | `podcast` | `podcast`, `apple`, `spotify`, `youtube`, `ebu-r128`, `atsc-a85`, `custom` |
| `targetLufs` | number | (none) | Required for `custom`. -70 to -5. |
| `truePeakDbtp` | number | `-1` | Ceiling, -9 to 0 dBTP (4× oversampled). |
| `loudnessRange` | number | `11` | Target LRA, 1–50 LU. |
| `outputFormat` | string | `mp3` | `mp3`, `m4a`, `wav`, `flac`, `mp4` (`mp4` needs a video input) |
| `sampleRate` | integer | same as input | 8000–192000 Hz. MP3 is capped at 48000. |
| `channels` | string | `keep` | `keep`, `mono`, `stereo` |
| `maxDurationSeconds` | integer | `14400` | Longer inputs are rejected (free). |

You must provide either `url` or `files`.

## Output reference

Each file produces one dataset row. Here is a real 59-minute spoken-word test run (URLs shortened):

```json
{
  "sourceUrl": "https://example.com/episodes/ep-142.mp3",
  "preset": "podcast",
  "outputFormat": "mp3",
  "status": "ok",
  "outputKey": "a1b2c3d4e5f6.mp3",
  "outputUrl": "https://api.apify.com/v2/key-value-stores/<storeId>/records/a1b2c3d4e5f6.mp3?signature=<sig>",
  "mime": "audio/mpeg",
  "target": { "integratedLufs": -16, "truePeakDbtp": -1, "loudnessRangeLu": 11 },
  "beforeLufs": -24.41,
  "afterLufs": -16.32,
  "afterTruePeakDbtp": -1.32,
  "gainAppliedDb": 8.09,
  "normalizationType": "dynamic",
  "renderPasses": 2,
  "truePeakCompliant": true,
  "input": {
    "format": "mp3",
    "duration": 3553.2,
    "sizeBytes": 28426087,
    "video": null,
    "audio": { "codec": "mp3", "sampleRate": 22050, "channels": 1 }
  },
  "billedMinutes": 60
}
```

Rows also include `outputBytes`, `outputDurationSeconds`, and full `before` and `after` objects (`integratedLufs`, `loudnessRangeLu`, `truePeakDbtp`, `thresholdLufs`). A failed file returns only `sourceUrl`, `preset`, `outputFormat`, `status: "error"` and `error`.

`normalizationType` is `linear` when plain gain was enough. It is `dynamic` when the limiter or range control had to work, which is usually the case for peaky audio or a large gain change.

## Use it from AI agents and automations

**MCP (Claude, Cursor, other MCP clients).** Add `https://mcp.apify.com?tools=ent-e/podcast-loudness-normalizer` as a remote MCP server and sign in with OAuth. Your agent can then call the Actor with a URL and a preset. Long files take a while (roughly 8–9 minutes of processing per hour of audio), so the agent should check the run and read the dataset when it finishes.

**n8n.** Use the Apify node (`@apify/n8n-nodes-apify`):
- **Run an Actor and get dataset** for short clips.
- For full episodes, use **Run an Actor**, then **Get Dataset Items**.

**Make.** Use the Apify app:
- The **Run an Actor** module with *Run synchronously* waits up to 120 s, which suits promos and short clips.
- For episodes, run asynchronously. Use the **Watch Actor Runs** trigger, then **Get Dataset Items**.

**Zapier.** Use the Apify app:
- **Run Actor and Fetch Results** for runs under 5 minutes.
- Otherwise, use **Run Actor**, then the **Finished Actor Run** trigger and **Fetch Dataset Items**.

**API.** Use async for episodes. Start a run, then fetch the dataset when it succeeds:

```bash
curl -X POST "https://api.apify.com/v2/acts/ent-e~podcast-loudness-normalizer/runs?token=$APIFY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com/episodes/ep-142.wav","preset":"podcast"}'
# then: GET https://api.apify.com/v2/datasets/<defaultDatasetId>/items?token=$APIFY_TOKEN
```

For short clips you can use `/run-sync-get-dataset-items`, which waits up to 5 minutes.

## FAQ

**Do I need a DAW, plugins or ffmpeg?**
No. Send a URL and get a normalized file and a loudness report back. Nothing to install.

**Which preset should I use for Spotify, Apple Podcasts and YouTube?**
- `apple` or `podcast` (-16 LUFS) for podcast feeds and Apple Podcasts.
- `spotify` or `youtube` (-14 LUFS) for music-style streaming targets.
- `ebu-r128` (-23) or `atsc-a85` (-24) for broadcast.

**Why is my file at -14.6 LUFS and not -14?**
The true-peak ceiling always wins. If reaching -14 LUFS would push peaks above `truePeakDbtp`, the Actor stops short so the file doesn't clip on playback. The row shows the measured `afterLufs` and `truePeakCompliant`. If you want the full -14, allow more headroom (for example `"truePeakDbtp": -0.5`) or reduce the peaks in your mix.

**Can I normalize a video podcast?**
Yes. Use `"outputFormat": "mp4"`. The video stream is copied untouched, and only the audio is normalized and re-encoded to AAC.

**Is the loudness measured on the final file?**
Yes. The `after` values come from measuring the encoded output, not from the filter's estimate. If the first render misses the ceiling or the target, it re-renders, and `renderPasses` tells you how many passes it took.

**What isn't supported?**
- Only the first audio stream is processed.
- Files must be direct download URLs (not streaming pages), up to 2 GB and 4 hours by default.
- It doesn't remove noise or EQ. It only sets loudness and peaks.

**Am I charged if a file fails?**
No. Error rows are free. You pay only for files that were normalized and delivered.

## ENT-E media toolkit

Every tool takes a public file URL, needs nothing installed, charges per file, doesn't charge for failures, and works from MCP, n8n, Make, Zapier and the API.

- **[Media Converter for AI Agents (FFmpeg)](https://apify.com/ent-e/media-converter-ffmpeg)**: audio/video to MP3, Whisper-ready 16 kHz WAV, MP4, WebM, GIF or thumbnails, with trim and batch.
- **[Image Converter & Compressor](https://apify.com/ent-e/image-converter-compressor)**: convert to WebP or AVIF, compress to a target file size, resize, strip EXIF/GPS.
- **[Podcast Loudness Normalizer](https://apify.com/ent-e/podcast-loudness-normalizer)**: normalize to -16, -14, -23 or -24 LUFS with a true-peak ceiling, plus a before/after report.
- **Video to Captions** (coming soon): SRT, VTT, TXT and word-level JSON from any video or audio URL, with Whisper.
- **[Video to Shorts](https://apify.com/ent-e/video-to-shorts-captions)**: vertical 9:16 clips with burned-in animated captions for TikTok, Reels and Shorts.

