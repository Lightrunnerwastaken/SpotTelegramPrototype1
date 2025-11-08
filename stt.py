import logging
import os
from pathlib import Path
import wave

logger = logging.getLogger(__name__)


def _stt_vosk(wav_path: Path, language: str | None = None) -> str:
    try:
        import vosk  # type: ignore
    except Exception as e:
        raise RuntimeError("Vosk ist nicht installiert. Bitte 'pip install vosk' ausführen.") from e

    model_path = (os.getenv("VOSK_MODEL_PATH") or "").strip()
    if not model_path:
        raise RuntimeError("VOSK_MODEL_PATH nicht gesetzt. Bitte Pfad zu einem Vosk-Modell angeben.")
    if not Path(model_path).exists():
        raise RuntimeError(f"VOSK_MODEL_PATH existiert nicht: {model_path}")

    wf = wave.open(str(wav_path), "rb")
    try:
        if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getframerate() not in (8000, 16000, 32000, 44100, 48000):
            logger.warning("WAV-Format ist nicht optimal für Vosk. Empfohlen: 16k mono.")

        model = vosk.Model(model_path)
        rec = vosk.KaldiRecognizer(model, wf.getframerate())
        if language:
            try:
                rec.SetWords(True)
            except Exception:
                pass

        text_chunks = []
        while True:
            data = wf.readframes(4000)
            if len(data) == 0:
                break
            if rec.AcceptWaveform(data):
                try:
                    res = rec.Result()
                except Exception:
                    res = None
                if res:
                    import json
                    text_chunks.append((json.loads(res) or {}).get("text", ""))
        try:
            res = rec.FinalResult()
            if res:
                import json
                text_chunks.append((json.loads(res) or {}).get("text", ""))
        except Exception:
            pass
        text = " ".join(t for t in text_chunks if t).strip()
        return text
    finally:
        wf.close()


def speech_to_text(wav_path: Path, language: str | None = None) -> str:
    """Convert WAV to text using configured backend. Currently uses Vosk.
    Set VOSK_MODEL_PATH to a local model directory (e.g., vosk-model-small-de-0.15)."""
    backend = (os.getenv("STT_BACKEND") or "vosk").strip().lower()
    if backend not in {"vosk"}:
        backend = "vosk"
    if backend == "vosk":
        return _stt_vosk(wav_path, language=language)
    raise RuntimeError("Kein STT-Backend verfügbar.")

