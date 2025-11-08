import asyncio
import logging
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Optional

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    cv2 = None  # type: ignore

try:
    import simpleaudio as sa  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    sa = None  # type: ignore

logger = logging.getLogger(__name__)


def capture_frame_bgr(preferred_index: int = 0, retries: int = 3):
    if cv2 is None:
        logger.warning("OpenCV ist nicht installiert; Kamera nicht verfügbar.")
        return None
    import time as _t

    def try_open(index, backend):
        cap = cv2.VideoCapture(index, backend)
        if not cap.isOpened():
            cap.release()
            return None
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        return cap

    if platform.system() == "Windows":
        candidates = [
            (preferred_index, cv2.CAP_DSHOW),
            (preferred_index, cv2.CAP_MSMF),
            (preferred_index + 1, cv2.CAP_DSHOW),
            (preferred_index + 1, cv2.CAP_MSMF),
        ]
    else:
        candidates = [
            (preferred_index, cv2.CAP_ANY),
            (preferred_index + 1, cv2.CAP_ANY),
        ]

    for cam_index, backend in candidates:
        cap = try_open(cam_index, backend)
        if cap is None:
            continue
        _t.sleep(0.2)
        for _ in range(retries):
            if cap.grab():
                ok, frame = cap.retrieve()
                if ok and frame is not None:
                    cap.release()
                    return frame
            _t.sleep(0.1)
        cap.release()
    return None


def encode_jpeg(frame, quality: int = 90) -> Optional[bytes]:
    if cv2 is None:
        logger.warning("OpenCV ist nicht installiert; JPEG-Encoding nicht verfügbar.")
        return None
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        return None
    return buf.tobytes()


def _play_wav_blocking(path: str) -> None:
    if sa is None:
        raise RuntimeError("WAV-Abspielfunktion benötigt 'simpleaudio'. Bitte installieren oder MP3/ffplay nutzen.")
    wave_obj = sa.WaveObject.from_wave_file(path)
    play_obj = wave_obj.play()
    play_obj.wait_done()


def _play_audio_file(path: str) -> None:
    ext = Path(path).suffix.lower()
    # 1) WAV via simpleaudio (blocking)
    if ext == ".wav":
        try:
            _play_wav_blocking(path)
            return
        except Exception as e:
            logger.warning(f"WAV-Wiedergabe via simpleaudio fehlgeschlagen: {e}. Versuche Fallbacks …")
    # 2) ffplay for mp3/other if available
    if shutil.which("ffplay"):
        subprocess.Popen(
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return
    # 3) Windows default player
    if platform.system() == "Windows":
        try:
            os.startfile(path)  # type: ignore[attr-defined]
            return
        except Exception as e:
            logger.warning(f"os.startfile failed: {e}")
    raise RuntimeError("Kein passender Player für dieses Audioformat gefunden. Installiere ffmpeg/ffplay oder nutze WAV.")


def ensure_wav(input_path: Path) -> Path:
    """Ensure input audio is WAV (16k mono). Uses ffmpeg if needed.
    Returns path to WAV file (may be the original if already WAV)."""
    p = Path(input_path)
    if p.suffix.lower() == ".wav":
        return p
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg nicht gefunden. Benötigt für Audio-Konvertierung (OGG/MP3 -> WAV).")
    out_fd, out_tmp = None, None
    try:
        # Create temp wav path next to input or in temp
        out_tmp = Path(p.parent) / (p.stem + "_conv.wav")
        # Convert to 16k mono PCM for offline STT
        cmd = [
            "ffmpeg", "-y", "-i", str(p),
            "-ac", "1", "-ar", "16000", str(out_tmp)
        ]
        proc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if proc.returncode != 0 or not out_tmp.exists():
            raise RuntimeError("ffmpeg-Konvertierung zu WAV fehlgeschlagen.")
        return out_tmp
    except Exception as e:
        raise



class AudioManager:
    def __init__(self, application):
        self.application = application

    def play_in_background(self, path: str | Path) -> None:
        p = str(path)

        def _play():
            try:
                _play_audio_file(p)
            except Exception as e:
                logger.error(f"Fehler beim Abspielen: {e}")

        self.application.create_task(asyncio.to_thread(_play))

    def schedule_cleanup(self, path: Path, delay_s: int = 120) -> None:
        async def _cleanup_later(p: Path, delay: int):
            try:
                await asyncio.sleep(delay)
                if p.exists():
                    p.unlink()
            except Exception as ce:
                logger.debug(f"Cleanup fehlgeschlagen: {ce}")

        self.application.create_task(_cleanup_later(Path(path), delay_s))
