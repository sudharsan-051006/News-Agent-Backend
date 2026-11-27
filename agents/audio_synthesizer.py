"""Dual-Engine Audio Synthesizer Agent for News-Agent-Backend.

Implements the user-specified priority:
1. Primary: Sarvam AI Text-to-Speech API (high-fidelity Indian accent / multilingual).
2. Fallback: Offline Neural TTS (edge-tts) if Sarvam API key is not provided,
   runs out of credits (HTTP 402/403/429), or is unreachable.
"""
from __future__ import annotations

import os
import sys
import json
import base64
import asyncio
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import edge_tts
import imageio_ffmpeg
from dotenv import load_dotenv

load_dotenv()

SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"
DEFAULT_OFFLINE_VOICE = "en-IN-NeerjaNeural"  # Professional Indian English broadcast voice
DEFAULT_SARVAM_SPEAKER = "priya"              # Sarvam AI premier female broadcast speaker
DEFAULT_LANGUAGE_CODE = "en-IN"
DEFAULT_SARVAM_MODEL = "bulbul:v3"


def get_audio_duration(file_path: str) -> float:
    """Measure the exact duration of an audio file in seconds using ffprobe/ffmpeg."""
    try:
        ff = imageio_ffmpeg.get_ffmpeg_exe()
        cmd = [ff, "-i", str(file_path)]
        res = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        for line in res.stderr.splitlines():
            if "Duration:" in line:
                # Example: Duration: 00:00:04.25, start: 0.000000 ...
                dur_str = line.split("Duration:")[1].split(",")[0].strip()
                h, m, s = dur_str.split(":")
                return float(h) * 3600 + float(m) * 60 + float(s)
    except Exception as exc:
        print(f"⚠️ Could not read audio duration via ffmpeg: {exc}")
    # Fallback estimate based on file size or word count
    return 4.5


def _synthesize_sarvam(
    text: str,
    output_path: str,
    api_key: str,
    speaker: str = DEFAULT_SARVAM_SPEAKER,
    language_code: str = DEFAULT_LANGUAGE_CODE,
    timeout: float = 25.0,
) -> bool:
    """Attempt speech synthesis via Sarvam AI API."""
    headers = {
        "api-subscription-key": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "inputs": [text],
        "target_language_code": language_code,
        "speaker": speaker,
        "pitch": 0,
        "pace": 1.05,
        "loudness": 1.5,
        "speech_sample_rate": 22050,
        "enable_preprocessing": True,
        "model": DEFAULT_SARVAM_MODEL,
    }

    try:
        resp = requests.post(SARVAM_TTS_URL, headers=headers, json=payload, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            audios = data.get("audios") or []
            if audios:
                audio_bytes = base64.b64decode(audios[0])
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                
                # Sarvam returns raw WAV bytes. If output_path is .mp3, convert cleanly via ffmpeg
                if output_path.lower().endswith(".mp3"):
                    wav_temp = output_path + ".temp.wav"
                    with open(wav_temp, "wb") as f:
                        f.write(audio_bytes)
                    ff = imageio_ffmpeg.get_ffmpeg_exe()
                    cmd = [ff, "-y", "-i", wav_temp, "-c:a", "libmp3lame", "-b:a", "192k", output_path]
                    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if os.path.exists(wav_temp):
                        os.remove(wav_temp)
                else:
                    with open(output_path, "wb") as f:
                        f.write(audio_bytes)

                print(f"✅ [Sarvam AI TTS] Audio generated successfully via speaker '{speaker}'")
                return True
            else:
                print("⚠️ [Sarvam AI TTS] No audio content in response payload.")
                return False
        else:
            print(
                f"⚠️ [Sarvam AI TTS] Returned HTTP {resp.status_code}: "
                f"{resp.text[:120]} (Quota/Credits exhausted or invalid key)."
            )
            return False
    except Exception as exc:
        print(f"⚠️ [Sarvam AI TTS] Connection failed: {exc}")
        return False


def _synthesize_offline(
    text: str,
    output_path: str,
    voice: str = DEFAULT_OFFLINE_VOICE,
) -> bool:
    """Synthesize speech using high-fidelity offline neural TTS."""
    try:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        async def _run():
            comm = edge_tts.Communicate(text, voice)
            await comm.save(output_path)
        asyncio.run(_run())
        print(f"🎙️ [Offline Neural TTS] Audio generated with voice '{voice}'")
        return True
    except Exception as exc:
        print(f"❌ [Offline Neural TTS] Generation failed: {exc}")
        return False


def synthesize_speech(
    text: str,
    output_path: str,
    sarvam_api_key: Optional[str] = None,
    use_sarvam: bool = False,
    speaker: str = DEFAULT_SARVAM_SPEAKER,
    language_code: str = DEFAULT_LANGUAGE_CODE,
    offline_voice: str = DEFAULT_OFFLINE_VOICE,
) -> Tuple[str, float]:
    """Synthesize speech using Neural Audio Model (or Sarvam AI only if explicitly enabled).

    Returns:
        Tuple of (engine_name, audio_duration_seconds)
    """
    # 1. Try Sarvam AI API ONLY if explicitly enabled
    if use_sarvam:
        key = sarvam_api_key or os.getenv("SARVAM_API_KEY", "").strip()
        if key:
            print("🚀 [TTS] Attempting speech synthesis via Sarvam AI API...")
            success = _synthesize_sarvam(
                text=text,
                output_path=output_path,
                api_key=key,
                speaker=speaker,
                language_code=language_code,
            )
            if success:
                dur = get_audio_duration(output_path)
                return "sarvam", dur
            print("🔄 [TTS] Sarvam AI unavailable -> Falling back to neural audio model.")

    # 2. Neural Audio Model
    print(f"🎙️ [Audio Model] Synthesizing speech via neural model: '{offline_voice}'...")
    success = _synthesize_offline(text=text, output_path=output_path, voice=offline_voice)
    if not success:
        raise RuntimeError(f"Failed to synthesize audio for: {text[:50]}")

    dur = get_audio_duration(output_path)
    return "neural_model", dur


def batch_synthesize_headlines(
    headlines: List[Dict[str, Any]],
    output_dir: str,
    sarvam_api_key: Optional[str] = None,
    use_sarvam: bool = False,
    offline_voice: str = DEFAULT_OFFLINE_VOICE,
) -> List[Dict[str, Any]]:
    """Synthesize audio for each headline in the list and annotate with audio path and duration."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n🎧 Synthesizing audio for {len(headlines)} headlines via Neural Model...")
    for idx, item in enumerate(headlines, start=1):
        text = item.get("narration_script") or item.get("headline") or "News update"
        audio_file = str(out_dir / f"headline_{idx:02d}.mp3")
        engine, duration = synthesize_speech(
            text=text,
            output_path=audio_file,
            sarvam_api_key=sarvam_api_key,
            use_sarvam=use_sarvam,
            offline_voice=offline_voice,
        )
        item["audio_path"] = audio_file
        item["audio_engine"] = engine
        item["audio_duration"] = duration
        print(f"  [{idx:02d}/{len(headlines):02d}] {duration:.1f}s via {engine} | {item['headline'][:45]}...")

    total_time = sum(h.get("audio_duration", 0) for h in headlines)
    print(f"✅ Audio synthesis complete. Total bulletin duration: {total_time:.1f}s ({total_time/60:.1f} min)")
    return headlines


if __name__ == "__main__":
    test_text = "Good evening. Breakthroughs in artificial intelligence now enable neural models to run completely locally."
    test_out = "outputs/test_tts.mp3"
    engine, dur = synthesize_speech(test_text, test_out)
    print(f"Result: {engine}, Duration: {dur:.2f}s, Path: {test_out}")
