Spot v0 Telegram Bot
====================

Überblick
- Telegram‑Bot mit Mission‑Queue (Gipfeli), Kamera‑Snapshot, Audio‑Ausgabe und ElevenLabs TTS (WAV/MP3).
- Optionale Spot‑Integration (Boston Dynamics): nutzt Spot‑Kameras für `/photo`, spielt Audio auf Spot ab; Status, Power‑On/Stand, GraphNav navigate_to (Demo).

Voraussetzungen
- Python 3.10+
- Abhängigkeiten: `pip install -r spot_v0_bot/requirements.txt`
- Optional: `ffplay` (ffmpeg) für robustes MP3‑Playback

Schnellstart
- .env auf Basis von `spot_v0_bot/.env.example` erstellen
- Start: `python -m spot_v0_bot.bot`

Konfiguration (.env)
Erstelle `spot_v0_bot/.env` mit folgenden Variablen (siehe `.env.example`):

```
# Telegram
BOT_TOKEN=123456:abcdefg
ALLOWED_CHAT_IDS=12345678,23456789

# ElevenLabs TTS
ELEVEN_API_KEY=your_elevenlabs_api_key
ELEVEN_VOICE_ID=voice_id_from_elevenlabs
ELEVEN_MODEL_ID=eleven_multilingual_v2

# Spot SDK (optional)
SPOT_HOST=192.168.80.3
SPOT_USERNAME=admin
SPOT_PASSWORD=change_me
# Optional: Waypoint‑ID für Demo‑Navigation
# SPOT_WAYPOINT_MENSA=waypoint-id-123

# Optional: Kameraquelle für /photo
SPOT_IMAGE_SOURCE=frontleft_fisheye_image

# STT (Vosk)
STT_BACKEND=vosk
VOSK_MODEL_PATH=C:\\pfad\\zu\\vosk-model-small-de-0.15
STT_LANGUAGE=de
```

Bot‑Befehle
- `/start` – Begrüßung
- `/help` – Übersicht
- `/whoami` – zeigt deine Telegram‑User‑ID
- `/say <text>` – Echo
- `/photo` – Snapshot; mit Spot‑Konfiguration von der Spot‑Kamera, sonst lokale Webcam
- `/play <datei>` – spielt WAV/MP3 lokal ab
- `/gipfeli [Start] [Ziel]` – Mission starten (Queue + Fortschritt)
- `/gipfeli_status` bzw. `/status` – Status/Queue; `/status` ergänzt Spot‑Status
- `/abort` – eigene Mission abbrechen
- `/speech <text>` – ElevenLabs TTS, sendet Audio und spielt lokal ab
- `/spot_status` – kompakter Spot‑Status (optional)
- Voice → Voice: Sprachnachricht wird via STT erkannt und per TTS vorgelesen

Spot‑Integration (optional)
- Pakete: `bosdyn-client bosdyn-mission bosdyn-api` (bereits in requirements.txt)
- .env: `SPOT_HOST`, `SPOT_USERNAME`, `SPOT_PASSWORD` setzen; optional `SPOT_WAYPOINT_MENSA` für Demo‑Navigation.
- Verhalten:
  - `/status` hängt automatisch “🤖 Spot: …” an.
  - `/spot_status` zeigt den Status auf Abruf.
  - `/photo` nutzt Spot‑Kamera.
  - Audio‑Wiedergabe (z. B. bei `/speech`, Voice→TTS, `/play`) erfolgt auf Spot; fällt bei Fehler lokal zurück.
  - `/gipfeli` startet optional eine Demo‑Aktion:
    - Wenn `SPOT_WAYPOINT_MENSA` gesetzt und das Ziel „Mensa“ enthält → GraphNav `navigate_to`.
    - Sonst: `power_on + stand`.
- Hinweise:
  - Für GraphNav muss eine Karte geladen und der Roboter lokalisiert sein; Waypoint‑IDs müssen bekannt sein.
  - Das offizielle Spot SDK ist gRPC‑basiert. Für reine HTTP/GET‑Flows empfiehlt sich eine kleine Bridge (REST‑Service), die intern `spot_control.py` nutzt.

Audio‑Hinweise
- WAV bevorzugt via `simpleaudio`; Fallback zu `ffplay` oder Windows‑Standardplayer.
- Für OGG/MP3 → WAV (STT) wird `ffmpeg` benötigt.

Webcam‑Hinweise
- Windows: DSHOW/MSMF; andere OS: `CAP_ANY`.
- Bei belegter Kamera oder fehlendem `opencv-python` gibt `/photo` eine freundliche Meldung aus.

Sicherheit / Zugriff
- `ALLOWED_CHAT_IDS` sind Telegram‑User‑IDs (nicht Chat‑/Gruppen‑IDs). Deine ID via `/whoami`.
- Ist die Liste leer, sind alle Nutzer zugelassen.

STT (Speech‑to‑Text)
- Backend: Vosk (offline)
- Installation: `pip install vosk`
- Modell: z. B. vosk‑model‑small‑de‑0.15 herunterladen, Pfad in `VOSK_MODEL_PATH` setzen.

ffmpeg Installation
- Windows (A): `winget install Gyan.FFmpeg`
- Windows (B): `choco install ffmpeg`
- Windows (manuell): Build von gyan.dev laden, `bin` in PATH aufnehmen
- macOS: `brew install ffmpeg`
- Linux (Debian/Ubuntu): `sudo apt-get install ffmpeg`

Entwicklung
- Logging‑Konfiguration in `main()`; Hintergrundtasks via `context.application.create_task`.
- Nützliche Utilities: `progress_bar`, `estimate_eta_seconds`, `seconds_to_mmss`.
