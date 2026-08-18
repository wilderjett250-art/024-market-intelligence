# 024 Market Intelligence Terminal

> Turns public news and video content into source-linked, time-bounded, replayable market intelligence pages.

## Problem

Public information is fragmented, video content is difficult to organize, and recurring questions are hard to track. This project connects collection, video understanding, source checks, and scheduled summaries in a reproducible local workspace.

## Demo

~~~mermaid
flowchart LR
 A[Public news / RSS] --> C[Source checks]
 B[Public Douyin videos] --> D[Audio-visual understanding]
 C --> E[24-hour evidence window]
 D --> E
 E --> F[Question-driven intelligence page]
 F --> G[Historical video replay]
~~~

The page refreshes every 15 seconds while the server polls public videos every two minutes. Archived JSON records can be replayed with their overview, news points, and source information.

## Highlights

- **24-hour evidence window:** Fixed questions cover rate expectations, futures and sector stocks, and Middle East/technology-stock changes.
- **Native video understanding:** Doubao-Seed-2.0-lite performs audio-visual understanding and produces structured news points without treating page chrome or comments as transcripts.
- **Historical video archive:** Current and processed videos are stored by video ID for list and detail replay.
- **Dual-model failover:** Scheduled analysis uses DeepSeek first and automatically switches to the Doubao Responses API when quota, authentication, endpoint, or JSON output errors occur.
- **Evidence coverage labels:** RSS items, market snapshots, and video evidence are indexed by topic; every conclusion keeps its source URL and evidence-strength label.
- **Sources and uncertainty:** Claims remain tied to supplied URLs; single-source or unconfirmed reports are marked `[未证实]`.

## Tech

`Python · HTML/CSS/JavaScript · Node.js · RSS · DeepSeek API · Volcengine Ark Responses API · FFmpeg · systemd`

## Reproduce from source

1. Clone the repository and copy `.env.example` to `.env`. Keep your own API keys and paths local.
2. Install the Python dependencies and run `python app.py`; the default address is `http://127.0.0.1:19083`.
3. Open the home page and use `/health` for a service check.
4. Verify a small set of public sources first, then enable video synchronization and scheduled jobs using the deployment files.

```powershell
python app.py
```

Run the focused tests for DeepSeek primary routing, Doubao failover, and Responses API JSON parsing:

```powershell
python -m unittest discover -s tests -v
```

**Expected result:** The local dashboard loads, the health endpoint responds, and configured public-source summaries appear without exposing credentials.

## Scope and Safety

Process only user-specified public sources. Keep API keys, platform sessions, crawl caches, and server environment files outside the repository, using least-privilege paths and network rules in production.

## Contact

Open to technical exchange.
