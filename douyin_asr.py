"""Low-resource local Chinese ASR worker for a downloaded WAV file.

The production host uses the small Vosk Chinese model through a manually
unpacked Python 3.6 wheel.  The worker writes JSON to stdout and never writes
to the dashboard data files itself; the browser synchronizer owns publication.
"""
from __future__ import print_function

import argparse
import json
import os
import sys
import wave


def main():
    parser = argparse.ArgumentParser(description="Transcribe a 16 kHz mono PCM WAV locally")
    parser.add_argument("--audio", required=True)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()

    try:
        from vosk import KaldiRecognizer, Model, SetLogLevel
    except ImportError as exc:
        raise SystemExit("vosk runtime unavailable: %s" % exc)

    if not os.path.isfile(args.audio):
        raise SystemExit("audio file not found: %s" % args.audio)
    if not os.path.isdir(args.model):
        raise SystemExit("vosk model not found: %s" % args.model)

    SetLogLevel(-1)
    with wave.open(args.audio, "rb") as audio:
        if audio.getnchannels() != 1 or audio.getsampwidth() != 2:
            raise SystemExit("audio must be mono 16-bit PCM WAV")
        sample_rate = audio.getframerate()
        recognizer = KaldiRecognizer(Model(args.model), sample_rate)
        while True:
            chunk = audio.readframes(4000)
            if not chunk:
                break
            recognizer.AcceptWaveform(chunk)
        result = json.loads(recognizer.FinalResult() or "{}")

    text = " ".join(str(result.get("text", "")).split()).strip()
    words = result.get("result") if isinstance(result.get("result"), list) else []
    print(json.dumps({
        "status": "ok" if text else "empty",
        "text": text,
        "words": words,
        "sample_rate": sample_rate,
        "model": os.path.basename(os.path.normpath(args.model)),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
