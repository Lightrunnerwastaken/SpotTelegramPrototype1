Spot v0 Telegram Bot
====================

Kurzüberblick
- Telegram-Bot mit Mission-Queue (Gipfeli), Kamera-Snapshot, lokalem Audio-Playback und ElevenLabs TTS (WAV/MP3).
- Robuste TTS-Fehlerbehandlung (HTTP/JSON), temporäre Dateien werden automatisch aufgeräumt.
- Lokales Audio mit Fallbacks: simpleaudio (WAV) → ffplay → Windows-Default-Player.

Voraussetzungen
- Python 3.10+
- Abhängigkeiten aus `spot_v0_bot/requirements.txt`
- Optionales Binary: `ffplay` (Teil von ffmpeg), empfohlen für MP3/Allgemein

Installation
1) Virtuelle Umgebung (optional) erstellen und aktivieren.
2) Abhängigkeiten installieren:
   - `pip install -r spot_v0_bot/requirements.txt`
   - Hinweis: `opencv-python` ist relativ groß; bei Problemen System-/GPU-abhängige Wheels beachten.

Konfiguration (.env)
Erstelle `spot_v0_bot/.env` mit folgenden Variablen:

```
BOT_TOKEN=123456:abcdefg                     # Telegram Bot-Token
ALLOWED_CHAT_IDS=12345678,23456789           # optional: Telegram User-IDs Whitelist (nicht Chat-IDs!)
ELEVEN_API_KEY=your_elevenlabs_api_key       # für /speech benötigt
ELEVEN_VOICE_ID=voice_id_from_elevenlabs     # z. B. 21m00Tcm4TlvDq8ikWAM
ELEVEN_MODEL_ID=eleven_multilingual_v2       # optional, Default wie gezeigt
```

Starten
- Empfohlen: als Modul starten, damit Paket-Imports funktionieren
  - `python -m spot_v0_bot.bot`
- Der Bot startet Polling und loggt den Status. Beenden mit Strg+C.

Befehle (Auszug)
- `/start` – Begrüßung
- `/help` – Übersicht
- `/whoami` – zeigt deine Telegram-User-ID
- `/say <text>` – Echo
- `/photo` – Snapshot mit der Webcam
- `/play <datei>` – spielt WAV/MP3 lokal ab (siehe Audio-Hinweise)
- `/gipfeli [Start] [Ziel]` – Mission starten, Queue + Fortschritt
- `/gipfeli_status` bzw. `/status` – Status/Queue
- `/abort` – eigene Mission abbrechen
- `/speech <text>` – ElevenLabs TTS, sendet Audio und spielt lokal ab
- Voice → Voice: Schicke eine Sprachnachricht (Voice-Note). Der Bot macht STT (Spracherkennung) und liest den erkannten Text mit ElevenLabs wieder vor.

Audio-Hinweise
- WAV wird bevorzugt über `simpleaudio` abgespielt; fehlt das Paket oder schlägt es fehl, wird auf `ffplay` (falls installiert) oder den Windows-Standardplayer zurückgegriffen.
- Für MP3/andere Formate ist `ffplay` sehr empfehlenswert.
- Von ElevenLabs erzeugte temporäre Audiodateien werden nach ca. 2 Minuten automatisch gelöscht.
 - Für Sprachnachrichten‑Verarbeitung (STT) wird `ffmpeg` zur Konvertierung benötigt.

Webcam-Hinweise
- Windows: es werden DSHOW/MSMF versucht. Andere OS: `CAP_ANY`.
- Ist die Kamera belegt oder `opencv-python` fehlt, meldet `/photo` dies freundlich.

Sicherheit / Zugriff
- `ALLOWED_CHAT_IDS` sind Telegram-User-IDs, nicht Chat-/Gruppen-IDs. Hole deine ID via `/whoami`.
- Ist die Liste leer, sind alle Nutzer zugelassen.

Troubleshooting
- Kein Ton bei MP3: `ffplay` (ffmpeg) installieren oder WAV nutzen.
- `simpleaudio` nicht verfügbar: WAV-Playback fällt auf `ffplay`/Windows-Player zurück.
- Kamera-Fehler: Prüfe, ob eine andere App die Kamera blockiert; auf Linux ggf. andere Indizes testen.
- ElevenLabs-Fehler: Prüfe `ELEVEN_API_KEY`/`ELEVEN_VOICE_ID`; Logs geben HTTP-/JSON-Fehler aus.
- STT nicht verfügbar: `vosk` installieren und `VOSK_MODEL_PATH` setzen (siehe unten).

STT (Speech‑to‑Text)
- Backend: aktuell Vosk (offline)
- Installation: `pip install vosk`
- Modelldownload: Lade ein Sprachmodell herunter (z. B. Deutsch: vosk-model-small-de-0.15) und entpacke es.
- .env/Umgebung:
  - `VOSK_MODEL_PATH=C:\\pfad\\zu\\vosk-model-small-de-0.15`
  - Optional: `STT_LANGUAGE=de`
  - Optional: `STT_BACKEND=vosk` (derzeit nur vosk implementiert)

ffmpeg Installation (für OGG/MP3 → WAV)
- Windows (variante A): `winget install Gyan.FFmpeg` (fügt i. d. R. PATH hinzu)
- Windows (variante B): `choco install ffmpeg` (Chocolatey erforderlich)
- Windows (manuell): Static build von https://www.gyan.dev/ffmpeg/builds/ laden, `bin`-Ordner entpacken und dessen Pfad zur System-Umgebungsvariable `PATH` hinzufügen
- macOS: `brew install ffmpeg`
- Linux (Debian/Ubuntu): `sudo apt-get install ffmpeg`

Hinweise für Entwicklung
- Logging-Konfiguration erfolgt in `main()`. Hintergrundtasks werden an die Telegram-App gebunden (`context.application.create_task`).
- Kleine, eigenständige Utilities: `progress_bar`, `estimate_eta_seconds`, `seconds_to_mmss`.
