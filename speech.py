import os
import re
import sys
import time
import uuid
import tempfile
import threading
import subprocess

from playsound import playsound


VOICE = "en-US-AriaNeural"
audio_lock = threading.Lock()


def timestamp_to_seconds(ts):
    ts = ts.strip().replace(",", ".")
    hours, minutes, rest = ts.split(":")

    if "." in rest:
        seconds, frac = rest.split(".", 1)
        frac = float("0." + frac)
    else:
        seconds = rest
        frac = 0.0

    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + frac


def parse_vtt(vtt_path):
    with open(vtt_path, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = re.compile(
        r"(\d\d:\d\d:\d\d[,.]?\d*)\s*-->\s*(\d\d:\d\d:\d\d[,.]?\d*)\s*\n(.+?)(?=\n\n|\Z)",
        re.DOTALL,
    )

    cues = []

    for match in pattern.finditer(content):
        start_raw, end_raw, text_raw = match.groups()

        text = " ".join(
            line.strip()
            for line in text_raw.splitlines()
            if line.strip() and not line.strip().isdigit()
        )

        cues.append({
            "start": timestamp_to_seconds(start_raw),
            "end": timestamp_to_seconds(end_raw),
            "text": text,
        })

    return cues


def run_edge_tts_cli(text, branch):
    if branch == "negative":
        rate, pitch = "-15%", "-3Hz"
    elif branch == "positive":
        rate, pitch = "+5%", "+2Hz"
    else:
        rate, pitch = "+0%", "+0Hz"

    base = os.path.join(tempfile.gettempdir(), f"reachy_{uuid.uuid4().hex}")
    mp3_path = base + ".mp3"
    vtt_path = base + ".vtt"

    cmd = [
        "edge-tts",
        "--voice", VOICE,
        f"--rate={rate}",
        f"--pitch={pitch}",
        "--text", text,
        "--write-media", mp3_path,
        "--write-subtitles", vtt_path,
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError:
        cmd = [
            sys.executable, "-m", "edge_tts",
            "--voice", VOICE,
            f"--rate={rate}",
            f"--pitch={pitch}",
            "--text", text,
            "--write-media", mp3_path,
            "--write-subtitles", vtt_path,
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)

    cues = parse_vtt(vtt_path)
    print(f"[TTS] cues: {len(cues)}")

    return mp3_path, vtt_path, cues


def play_audio(path):
    with audio_lock:
        playsound(path)


def reveal_cue_text(cue_text, cue_duration, on_subtitle):
    if not cue_text:
        return

    # Reveal letters only while this cue is actually being spoken.
    reveal_duration = max(0.12, cue_duration * 0.88)
    delay = reveal_duration / max(len(cue_text), 1)

    visible = ""

    for char in cue_text:
        visible += char

        if on_subtitle:
            on_subtitle(visible + "▌")

        time.sleep(delay)

    if on_subtitle:
        on_subtitle(cue_text)


def speak_blocking(text, branch="neutral", on_subtitle=None, on_done=None):
    mp3_path = None
    vtt_path = None

    try:
        mp3_path, vtt_path, cues = run_edge_tts_cli(text, branch)

        audio_thread = threading.Thread(
            target=play_audio,
            args=(mp3_path,),
            daemon=True,
        )

        audio_thread.start()

        # Playsound delay
        AUDIO_START_DELAY = 0.35
        time.sleep(AUDIO_START_DELAY)

        start_time = time.time() - AUDIO_START_DELAY

        if cues:
            for cue in cues:
                # Wait until this exact spoken cue begins.
                wait = cue["start"] - (time.time() - start_time)
                if wait > 0:
                    time.sleep(wait)

                cue_duration = max(0.1, cue["end"] - cue["start"])
                reveal_cue_text(cue["text"], cue_duration, on_subtitle)

        else:
            if on_subtitle:
                on_subtitle(text)

        audio_thread.join()

        if on_done:
            on_done()

    finally:
        for path in [mp3_path, vtt_path]:
            if path:
                try:
                    os.remove(path)
                except OSError:
                    pass


def speak_async(text, branch="neutral", on_subtitle=None, on_done=None):
    threading.Thread(
        target=speak_blocking,
        args=(text, branch, on_subtitle, on_done),
        daemon=True,
    ).start()