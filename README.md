# TLDV Downloader

Export your [tldv.io](https://tldv.io) meeting recordings to local MP4 files — one at a time, or a
whole list in parallel.

[![License](https://img.shields.io/github/license/Cramraika/tldv_downloader)](./LICENSE)
[![Stars](https://img.shields.io/github/stars/Cramraika/tldv_downloader?style=social)](https://github.com/Cramraika/tldv_downloader/stargazers)
[![Issues](https://img.shields.io/github/issues/Cramraika/tldv_downloader)](https://github.com/Cramraika/tldv_downloader/issues)
[![GitHub Sponsors](https://img.shields.io/github/sponsors/Cramraika?logo=github&label=Sponsor)](https://github.com/sponsors/Cramraika)

> **Maintenance status:** low activity. The tool works as described below, and the repository stays
> public and open to issues and pull requests. It depends on an undocumented tldv.io endpoint, so it
> can break without warning if that endpoint changes.

## What it does

`tldv_downloader.py` is a single-file, interactive Python script. You give it a tldv.io meeting URL
and an `Authorization` token copied from your browser. It calls the tldv.io watch-page API to
resolve the meeting's video stream URL, then shells out to **N_m3u8DL-RE** (preferred) or **FFmpeg**
(fallback) to pull the stream down to an `.mp4`. Alongside each video it writes a `.json` file
containing the raw API response for that meeting.

It can also run in a batch mode that downloads several meetings concurrently using a thread pool,
reusing one auth token for all of them.

### Who it is for

Anyone who wants a local copy of their own tldv.io recordings — for offline viewing, personal
archives, or retention requirements — rather than leaving them only in the SaaS.

### What it is not

It is not a scraper, a bulk-export service, or a transcription tool. It downloads meetings your
account can already access, one URL at a time.

## Requirements

- **Python 3.7 or newer.** The floor is set by `subprocess.run(capture_output=...)`. CI runs the
  checks on Python 3.11.
- **`requests`** — the only Python dependency (`requirements.txt` pins `requests==2.34.2`).
- **N_m3u8DL-RE or FFmpeg**, on your `PATH` or pointed at by `TLDV_N_M3U8DL` / `TLDV_FFMPEG`. At
  least one is required; the script exits with `Neither N_m3u8DL-RE nor ffmpeg is available` if it
  finds neither. Having both is best: N_m3u8DL-RE calls FFmpeg to mux the finished stream.

## Install

```bash
git clone https://github.com/Cramraika/tldv_downloader.git
cd tldv_downloader
pip install -r requirements.txt
```

Then install a downloader backend. N_m3u8DL-RE is preferred because it fetches HLS segments in
parallel; FFmpeg is used automatically if N_m3u8DL-RE is missing.

```bash
# N_m3u8DL-RE — see https://github.com/nilaoda/N_m3u8DL-RE/releases
brew install n_m3u8dl-re          # macOS
scoop install n_m3u8dl-re         # Windows

# FFmpeg (fallback)
brew install ffmpeg                       # macOS
choco install ffmpeg                      # Windows
sudo apt update && sudo apt install ffmpeg # Debian/Ubuntu
```

Verify with `N_m3u8DL-RE --version` or `ffmpeg -version`.

## Usage

The script is **fully interactive** — it prompts for everything it needs. There are no configuration
flags. The only recognised argument is help:

```bash
python tldv_downloader.py            # run the tool (prompts for everything)
python tldv_downloader.py --help     # print the auth-token instructions and exit
```

`-h`, `--help`, and `help` are equivalent, and all three only print the token guide.

### Single download

```
$ python tldv_downloader.py
Batch download mode? (y/N): n
Enter the TLDV meeting URL: https://tldv.io/app/meetings/681cc00576bb060013e5fbb7
Enter your Authorization token: Bearer eyJhbGciOi...
Output directory (press Enter for current):
Proceed with download? (y/N): y
```

### Batch download

```
$ python tldv_downloader.py
Batch download mode? (y/N): y
Choose option (1/2): 2
Enter path to URLs file: ./meetings.txt
Enter your Authorization token: Bearer eyJhbGciOi...
Output directory (press Enter for current): ./recordings
Number of parallel downloads (1-8, default 3): 4
Proceed with batch download? (y/N): y
```

Option `1` instead lets you paste URLs one per line, ending with `done`.

The worker count is clamped to the range 1–8; anything outside that range, or any non-numeric input,
falls back to 3.

### URL list file format

One URL per line. Blank lines are skipped, and lines beginning with `#` are treated as comments.

```text
# Q3 customer calls
https://tldv.io/app/meetings/681cc00576bb060013e5fbb7
https://tldv.io/app/meetings/582ab11487cc070012d5fa6c
```

## Getting the authorization token

The script authenticates with a bearer token lifted from your own browser session. There is no
API key and no login flow.

1. Log in at <https://tldv.io> and open the meeting you want.
2. Open DevTools (F12) and select the **Network** tab.
3. Reload the page and filter for `watch-page`.
4. Select the request to `.../meetings/<id>/watch-page?noTranscript=true`.
5. Under **Request Headers**, copy the full `Authorization` value.

You can paste the value with or without the `Bearer ` prefix — the script adds it if missing. One
token works for every download in the same session; it stops working when that browser session ends,
at which point you need a fresh one.

Because the token is entered at a prompt, it is not stored on disk and not read from the
environment.

## Configuration

There is no config file — everything else is answered at the prompts. Two optional environment
variables override the lookup of the external binaries:

| Variable | Effect |
|----------|--------|
| `TLDV_N_M3U8DL` | Full path to the N_m3u8DL-RE executable, instead of searching `PATH`. |
| `TLDV_FFMPEG` | Full path to the FFmpeg executable, instead of searching `PATH`. |

A value pointing at a file that does not exist is reported and then ignored, falling back to `PATH`.

The repository ships a `.env.example`, but it is inaccurate — see *Known issues* below. No other
environment variable is read.

## How the download works

The URL in `video.source` — the one the watch-page API returns and that older versions of this tool
fed straight to the downloader — points at `media-files.tldv.io`, a Wasabi bucket that used to be
world-readable and is now private. Requesting it unsigned answers `403 AccessDenied`, no matter
which downloader you use.

So the tool follows the same path the web player takes:

1. `GET https://gaia.tldv.io/v1/meetings/<id>/playlist.m3u8` with the bearer token. Note the host —
   this endpoint is **not** on the `gw.tldv.io` gateway that serves the watch-page API, which
   answers `502` for it. The response is a redirect to a short-lived signing service.
2. The playlist that comes back carries a custom header line,
   `#TLDVCONF:<ttl-seconds>,<shift>,<base-url>`, and its segment lines are Caesar-shifted.
3. `tldv_playlist.decode_playlist()` shifts the letters back by `<shift>` and prefixes
   `<base-url>`, producing presigned absolute segment URLs, valid for `<ttl-seconds>` (48 hours in
   practice).
4. The decoded playlist is written to a temporary `.m3u8` and handed to the downloader as a local
   file. It is deleted once the download finishes.

If step 1 fails the tool falls back to the raw `video.source` URL and says so, which is only useful
if tldv ever makes the bucket public again.

## Output

Files land in the directory you specify, or the current working directory if you press Enter.

```
recordings/
├── 2025-05-08_14-30-29_Weekly_Sync.mp4
├── 2025-05-08_14-30-29_Weekly_Sync.json
├── 2025-05-08_15-45-12_Customer_Call.mp4
└── 2025-05-08_15-45-12_Customer_Call.json
```

The timestamp comes from the meeting's `createdAt` field; if it is missing or does not parse, the
current time is used instead. Names are sanitised by replacing `< > : " / \ | ? *` with underscores,
collapsing runs of underscores, trimming leading and trailing underscores and spaces, and truncating
to 100 characters. A name that sanitises to nothing becomes `TLDV_Meeting`.

The `.json` file is the **complete, unmodified watch-page API response** for that meeting. The script
does not select or reshape fields, so exactly what it contains is whatever tldv.io returns.

## Known issues and limitations

These are real behaviours in the current source, not hypotheticals.

- **Batch mode always reports failure.** `download_multiple_videos()` prints a correct per-file
  summary but returns nothing, so the caller's success check never passes and you always see
  `Batch download failed!` at the end — even when every download succeeded. Trust the per-file lines
  and the files on disk, not the final message.
- **No resume.** An interrupted download restarts from zero. The FFmpeg path passes `-y` and
  overwrites any existing output file. N_m3u8DL-RE is invoked with `--download-retry-count 5`, which
  retries segments within a run but does not resume across runs.
- **The signed playlist expires.** Segment signatures are valid for 48 hours from the moment the
  playlist is fetched. A download that is paused for longer has to start over with a fresh
  playlist. The tool prints the remaining validity before it starts.
- **Metadata is written before the download runs.** A failed or cancelled download still leaves a
  `.json` file behind with no matching `.mp4`.
- **Parallel output is interleaved.** Each worker prints its own progress and re-runs the backend
  detection, so with more than one worker the console output from different downloads is mixed
  together.
- **Downloads time out after one hour.** The per-download subprocess timeout is fixed and not
  configurable.
- **The API endpoints are undocumented.** The script calls
  `https://gw.tldv.io/v1/meetings/<id>/watch-page?noTranscript=true` for the metadata and
  `https://gaia.tldv.io/v1/meetings/<id>/playlist.m3u8` for the playlist. Both are internal
  tldv.io endpoints, and the `#TLDVCONF` obfuscation they use is not a stable interface. If either
  changes, the tool breaks — it already broke once this way.
- **Meeting IDs are taken from the last URL path segment** and must be at least 10 characters. URLs
  in another shape will be rejected.
- **`fleet_stt_client.py` is unrelated to the downloader.** It is not imported by
  `tldv_downloader.py` and calls an internal service that is not publicly reachable. Ignore it.

Common failures: `Unauthorized: Invalid auth token` means the token expired — get a fresh one.
`Meeting not found` means the ID is wrong or your account cannot access that meeting.

## Responsible use

Download only recordings you are entitled to, and stay within tldv.io's terms of service. This tool
is intended for personal and organisational backup of your own meetings, not for bulk harvesting.

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](./CONTRIBUTING.md).

## License

MIT © 2026 Vagary Labs LLP. See [LICENSE](./LICENSE).

A Vagary Labs project.
