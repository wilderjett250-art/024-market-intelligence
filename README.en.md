# 024 Market Intelligence Terminal

> Collects public news, video text, and speech on a schedule, then generates source-linked market intelligence pages for fixed questions.

## Problem

Public information is fragmented and hard to verify, video content is difficult to organize, and recurring questions are hard to track.

## Demo

~~~mermaid
flowchart LR
 A[RSS / public news] --> C[Source checks]
 B[Video text / speech] --> C
 C --> D[24-hour evidence window]
 D --> E[Question-driven summary]
~~~

Collection, transcription, source checks, and summaries remain traceable instead of presenting model output as an unsourced conclusion.

## Highlights

- Multi-source public-news and RSS collection.
- Video-text processing and local Vosk transcription.
- A 24-hour evidence window with source links.
- Scheduled DeepSeek summaries and market snapshots.

## Tech

`Python · HTML/CSS/JavaScript · RSS · Vosk · DeepSeek API`

## Reproduce from ZIP

1. Extract the ZIP, copy `.env.example` to `.env`, and fill in your own API key.
2. Run `python app.py`; it listens on `http://127.0.0.1:19083` by default.
3. Open the home page and use `/health` for the health check.
4. Verify a small set of public sources first, then configure scheduled collection and the full scope.

**Expected result:** After these steps, you should see the project's page, window, device output, or test result.

## Scope and Safety

Collect public sources only; API keys, schedules, and fetched results are local runtime data and must not be committed or publicly shared.

## Contact

Open to technical exchange.
