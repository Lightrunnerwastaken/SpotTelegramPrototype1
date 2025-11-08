import logging
import os
from pathlib import Path
import tempfile

import requests

# Support both package execution and direct script execution
try:
    from .config import get_eleven_config  # type: ignore
except Exception:
    import sys
    from pathlib import Path as _P
    sys.path.insert(0, str(_P(__file__).resolve().parent))
    from config import get_eleven_config  # type: ignore

logger = logging.getLogger(__name__)


def eleven_tts_to_file(text: str) -> Path:
    """Call ElevenLabs TTS and save audio to a temp file (.wav or .mp3)."""
    api_key, voice_id, model_id = get_eleven_config()
    if not api_key or not voice_id:
        logger.error("ELEVEN_API_KEY/ELEVEN_VOICE_ID fehlen oder leer.")
        raise RuntimeError("ELEVEN_API_KEY/ELEVEN_VOICE_ID fehlen in .env")

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": api_key,
        "accept": "audio/wav",  # we request WAV; server may still return MP3
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {"stability": 0.4, "similarity_boost": 0.7},
    }

    try:
        r = requests.post(url, headers=headers, json=payload, stream=True, timeout=60)
    except requests.exceptions.RequestException as e:
        logger.error(f"HTTP-Fehler bei ElevenLabs-Anfrage: {e}")
        raise RuntimeError("Netzwerkfehler zur ElevenLabs API") from e

    # HTTP-Status prüfen
    if r.status_code >= 400:
        try:
            err = r.json()
        except Exception:
            err = (r.text or "").strip()[:500]
        logger.error(f"ElevenLabs HTTP-Fehler {r.status_code}: {err}")
        raise RuntimeError(f"ElevenLabs API-Fehler ({r.status_code}): {err}")
    ct = (r.headers.get("Content-Type") or "").lower()

    # JSON => error payload
    if "application/json" in ct:
        try:
            err = r.json()
        except Exception:
            err = {"raw": r.text[:500]}
        logger.error(f"ElevenLabs error: {err}")
        raise RuntimeError(f"ElevenLabs API-Fehler: {err}")

    # Choose file extension
    suffix = ".wav" if "wav" in ct else ".mp3" if ("mpeg" in ct or "mp3" in ct) else ".bin"

    fd, tmp_path = tempfile.mkstemp(prefix="spot_speech_", suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        wrote_any = False
        for chunk in r.iter_content(chunk_size=8192):
            if chunk:
                wrote_any = True
                f.write(chunk)
        if not wrote_any:
            logger.error("ElevenLabs Antwort enthielt keine Audiodaten.")
            raise RuntimeError("Leere Audiodatei von ElevenLabs erhalten")

    return Path(tmp_path)
