# -*- coding: utf-8 -*-
"""
Spot Telegram Bot — with robust ElevenLabs TTS (WAV/MP3) + local playback
- Handles JSON error responses and non-WAV content-types
- Sends audio to chat AND plays locally (with fallbacks)
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
import time
from dataclasses import dataclass, field
from io import BytesIO
from typing import Dict
from pathlib import Path
from html import escape as _html_escape

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler

# Support both package execution (python -m spot_v0_bot.bot)
# and direct script execution (python spot_v0_bot/bot.py)
try:  # relative imports when executed as package
    from .config import BOT_TOKEN, ALLOWED_CHAT_IDS
    from .media import (
        AudioManager,
        capture_frame_bgr,
        encode_jpeg,
        ensure_wav,
    )
    from .tts import eleven_tts_to_file
    from .stt import speech_to_text
    try:
        from .spot_control import SpotController  # type: ignore
    except Exception:
        SpotController = None  # type: ignore
except Exception:  # fallback for direct execution
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from config import BOT_TOKEN, ALLOWED_CHAT_IDS  # type: ignore
    from media import AudioManager, capture_frame_bgr, encode_jpeg, ensure_wav  # type: ignore
    from tts import eleven_tts_to_file  # type: ignore
    from stt import speech_to_text  # type: ignore
    try:
        from spot_control import SpotController  # type: ignore
    except Exception:
        SpotController = None  # type: ignore

# -----------------------------------------------------------------------------
# 1) Configuration & Logging
# -----------------------------------------------------------------------------
logger = logging.getLogger("spot-bot")

# -----------------------------------------------------------------------------
# 2) Security helpers
# -----------------------------------------------------------------------------

def is_authorized(update: Update) -> bool:
    if not ALLOWED_CHAT_IDS:
        return True
    uid = update.effective_user.id if update.effective_user else None
    return uid is not None and str(uid) in ALLOWED_CHAT_IDS

async def reject_if_unauthorized(update: Update) -> bool:
    if is_authorized(update):
        return False
    if update.message:
        await update.message.reply_text("⛔ Nicht autorisiert.")
    elif update.effective_chat:
        await update.get_bot().send_message(chat_id=update.effective_chat.id, text="⛔ Nicht autorisiert.")
    return True

# -----------------------------------------------------------------------------
# 3) Utility functions
# -----------------------------------------------------------------------------

def html_escape(s: str) -> str:
    return _html_escape(s)

def progress_bar(p: float, width: int = 20) -> str:
    p = max(0.0, min(1.0, p))
    filled = int(math.floor(p * width))
    return "▰" * filled + "▱" * (width - filled)

# Audio-Wiedergabe ist in media.AudioManager implementiert

def seconds_to_mmss(sec: int) -> str:
    m, s = divmod(max(0, sec), 60)
    return f"{m:02d}:{s:02d}"

# -----------------------------------------------------------------------------
# 4) Mission model (per-chat state)
# -----------------------------------------------------------------------------

@dataclass
class ChatState:
    active: bool = False
    current_user_id: int | None = None
    current_msg_id: int | None = None
    started_at: float | None = None
    eta_seconds: int = 0
    start_room: str = "Zimmer 3.12"
    target: str = "Mensa"
    queue: list[int] = field(default_factory=list)

states: Dict[int, ChatState] = {}
locks: Dict[int, asyncio.Lock] = {}

def get_state(chat_id: int) -> ChatState:
    if chat_id not in states:
        states[chat_id] = ChatState()
    return states[chat_id]

def get_lock(chat_id: int) -> asyncio.Lock:
    if chat_id not in locks:
        locks[chat_id] = asyncio.Lock()
    return locks[chat_id]

def estimate_eta_seconds(start_room: str, target: str) -> int:
    base = 210  # 3.5 minutes
    fudge = (sum(map(ord, start_room)) + sum(map(ord, target))) % 40
    return base + fudge

def render_status_html(user_name: str, s: ChatState) -> str:
    elapsed = int(time.time() - (s.started_at or time.time()))
    remaining = max(0, s.eta_seconds - elapsed)
    p = 0 if s.eta_seconds <= 0 else elapsed / s.eta_seconds
    bar = progress_bar(p)
    return (
        f"🦾 <b>Mission: Gipfeli holen</b>\n"
        f"👤 Auftrag von: <b>{html_escape(user_name)}</b>\n"
        f"🏁 Route: {html_escape(s.start_room)} → {html_escape(s.target)}\n"
        f"⏱️ Restzeit: {seconds_to_mmss(remaining)}\n"
        f"{bar}  {int(p*100)}%\n"
        f"<i>Simuliert – später via Dijkstra + echte Robotik</i>"
    )

async def _run_mission(context, chat_id: int):
    s = get_state(chat_id)
    lock = get_lock(chat_id)

    try:
        user = await context.bot.get_chat(s.current_user_id)
        display_name = user.first_name or (user.username or str(user.id))

        tick = 2
        while True:
            txt = render_status_html(display_name, s)
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=s.current_msg_id,
                    text=txt,
                    parse_mode="HTML",
                    reply_markup=build_mission_keyboard(),
                )
            except Exception as e:
                logger.debug(f"edit_message_text failed: {e}")

            if time.time() - (s.started_at or 0) >= s.eta_seconds:
                break
            await asyncio.sleep(tick)

        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=s.current_msg_id,
                text="✅ <b>Mission abgeschlossen!</b>\n🥐 Gipfeli abgeholt. Auf dem Rückweg.",
                parse_mode="HTML",
                reply_markup=build_mission_keyboard(),
            )
        except Exception as e:
            logger.debug(f"final edit failed: {e}")

    finally:
        async with lock:
            s.active = False
            s.current_user_id = None
            s.current_msg_id = None
            s.started_at = None
            next_user = s.queue.pop(0) if s.queue else None

        if next_user:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f'➡️ <b>Du bist dran!</b> <a href="tg://user?id={next_user}">Zum Nutzer</a>',
                parse_mode="HTML",
            )
            await _start_for(context, chat_id, next_user, s.start_room, s.target)

async def _start_for(context, chat_id: int, user_id: int, start_room: str, target: str):
    s = get_state(chat_id)
    lock = get_lock(chat_id)
    eta = estimate_eta_seconds(start_room, target)

    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"📝 Auftrag angenommen.\n🥐 Mission: {html_escape(start_room)} → {html_escape(target)}",
        parse_mode="HTML",
        reply_markup=build_mission_keyboard(),
    )

    async with lock:
        s.active = True
        s.current_user_id = user_id
        s.current_msg_id = msg.message_id
        s.started_at = time.time()
        s.eta_seconds = eta
        s.start_room = start_room
        s.target = target

    context.application.create_task(_run_mission(context, chat_id))

# -----------------------------------------------------------------------------
# 5) Command handlers
# -----------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_unauthorized(update):
        return
    await update.message.reply_text("👋 Hallo! Ich bin euer Spot-Bot.\nTippe /help für eine Übersicht der Befehle.")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_unauthorized(update):
        return
    help_text = (
        "<b>Spot-Bot Befehle</b>\n"
        "• <code>/start</code> – Begrüßung\n"
        "• <code>/help</code> – diese Hilfe\n"
        "• <code>/whoami</code> – zeigt deine Telegram-User-ID\n"
        "• <code>/say &lt;text&gt;</code> – Echo (Platzhalter für TTS)\n"
        "• <code>/photo</code> – macht ein Foto mit der Webcam\n"
        "• <code>/play &lt;datei&gt;</code> – spielt WAV/MP3 lokal ab\n"
        "• <code>/gipfeli [Start] [Ziel]</code> – startet die Mission (mit Queue & Fortschritt)\n"
        "• <code>/gipfeli_status</code> – zeigt aktiven Auftrag + Warteschlange\n"
        "• <code>/status</code> – Alias für /gipfeli_status\n"
        "• <code>/abort</code> – bricht deine laufende Mission ab\n"
        "• <code>/speech &lt;text&gt;</code> – erzeugt Stimme via ElevenLabs, sendet & spielt lokal\n"
        "• <i>Tipp:</i> Unter der Missions-Nachricht findest du Buttons für 📷/📊/🛑\n\n"
        "<i>Hinweis:</i> Für produktiven Einsatz Whitelist in .env setzen (ALLOWED_CHAT_IDS)."
    )
    await update.message.reply_text(help_text, parse_mode="HTML", reply_markup=build_help_keyboard())

async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_unauthorized(update):
        return
    uid = update.effective_user.id if update.effective_user else None
    await update.message.reply_text(f"🆔 Deine Telegram-User-ID: {uid}")

async def say(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_unauthorized(update):
        return
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text("Bitte Text angeben: /say Hallo Spot!")
        return
    await update.message.reply_text(f"🔊 {text}")

async def photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_unauthorized(update):
        return
    await update.message.reply_text("📷 Nehme Foto auf…")
    await photo_action(update.effective_chat.id, context)

async def play(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_unauthorized(update):
        return
    if not context.args:
        await update.message.reply_text("Nutze: /play <pfad-zur-Audiodatei>  (WAV/MP3, z. B. spot_speech.wav)")
        return
    file_path = " ".join(context.args).strip()
    if not os.path.isfile(file_path):
        await update.message.reply_text(f"❌ Datei nicht gefunden:\n{file_path}")
        return
    await update.message.reply_text(f"🎵 Spiele ab: {file_path}")

    audio_manager: AudioManager = context.application.bot_data.get("audio_manager")
    if not isinstance(audio_manager, AudioManager):
        await update.message.reply_text("❌ Audio-Manager nicht initialisiert.")
        return
    audio_manager.play_in_background(file_path)

async def gipfeli(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_unauthorized(update):
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    start_room = (context.args[0] if len(context.args) >= 1 else "Zimmer 3.12")
    target = (context.args[1] if len(context.args) >= 2 else "Mensa")

    s = get_state(chat_id)
    lock = get_lock(chat_id)

    async with lock:
        if s.active:
            if s.current_user_id == user_id:
                await update.message.reply_text("ℹ️ Deine Mission läuft bereits.")
                return
            if user_id in s.queue:
                pos = s.queue.index(user_id) + 1
                await update.message.reply_text(f"⏳ Du stehst schon in der Warteschlange (Position {pos}).")
                return
            s.queue.append(user_id)
            pos = len(s.queue)
            await update.message.reply_text(f"⏳ Mission läuft. Ich habe dich eingereiht (Position {pos}).")
            return

    await _start_for(context, chat_id, user_id, start_room, target)

    # Optional: Spot SDK Aktion (Demo)
    spot = context.application.bot_data.get("spot") if hasattr(context, "application") else None
    if spot and SpotController:
        async def _spot_task():
            try:
                waypoint = os.getenv("SPOT_WAYPOINT_MENSA", "") if "mensa" in target.lower() else ""
                if waypoint:
                    msg = await asyncio.to_thread(spot.navigate_to_waypoint, waypoint)
                else:
                    msg = await asyncio.to_thread(spot.power_on_and_stand)
                await update.message.reply_text(str(msg))
            except Exception as e:
                await update.message.reply_text(f"Spot-Aktion fehlgeschlagen: {e}")
        context.application.create_task(_spot_task())

async def gipfeli_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_unauthorized(update):
        return
    chat_id = update.effective_chat.id
    s = get_state(chat_id)
    if not s.active and not s.queue:
        await update.message.reply_text("🟢 Keine aktive Mission. Warteschlange ist leer.")
        return
    lines = []
    if s.active:
        elapsed = int(time.time() - (s.started_at or time.time()))
        remaining = max(0, s.eta_seconds - elapsed)
        lines.append(f"🔵 Aktiv: {s.start_room} → {s.target}, Rest {seconds_to_mmss(remaining)}")
    if s.queue:
        q = ", ".join([f'<a href="tg://user?id={uid}">#{i+1}</a>' for i, uid in enumerate(s.queue)])
        lines.append(f"👥 Queue: {q}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")

async def status_alias(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await gipfeli_status(update, context)

async def abort(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_unauthorized(update):
        return
    await abort_action(update.effective_chat.id, update.effective_user.id, context)

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_unauthorized(update):
        return
    await update.message.reply_text("❓ Unbekannter Befehl. Tippe /help.")

# -----------------------------------------------------------------------------
# 6) /speech command
# -----------------------------------------------------------------------------

async def speech(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /speech <text>  -> erzeugt Stimme via ElevenLabs, sendet Audio (WAV/MP3)
                       und spielt lokal (mit Fallbacks) ab.
    Tipp: Du kannst auch auf eine Textnachricht mit /speech antworten.
    """
    if await reject_if_unauthorized(update):
        return

    # Text: argumente ODER reply (nicht beides)
    text = " ".join(context.args).strip()
    if not text and update.message and update.message.reply_to_message:
        text = (update.message.reply_to_message.text or "").strip()

    if not text:
        await update.message.reply_text(
            "Nutze: /speech <text>\nOder antworte mit /speech auf eine Text-Nachricht."
        )
        return

    status = await update.message.reply_text("🗣️ Erzeuge Audio …")

    try:
        audio_path = await asyncio.to_thread(eleven_tts_to_file, text)

        # In Chat senden
        with open(audio_path, "rb") as f:
            await context.bot.send_audio(
                chat_id=update.effective_chat.id,
                audio=f,
                filename=audio_path.name,
                title="Spot Speech",
                caption=f"🗣️ ElevenLabs TTS ({audio_path.suffix.lstrip('.')})",
            )

        # Lokal abspielen + Cleanup via AudioManager
        audio_manager: AudioManager = context.application.bot_data.get("audio_manager")
        if isinstance(audio_manager, AudioManager):
            audio_manager.play_in_background(str(audio_path))
            audio_manager.schedule_cleanup(audio_path)
        else:
            logger.warning("AudioManager fehlt; überspringe lokales Abspielen/Cleanup.")

        await status.edit_text("✅ Audio erzeugt, gesendet und lokal abgespielt.")
    except Exception as e:
        logger.exception(e)
        await status.edit_text("❌ Konnte Audio nicht erzeugen (siehe Logs).")

# -----------------------------------------------------------------------------
# 6) Voice handler: STT -> TTS
# -----------------------------------------------------------------------------

async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_unauthorized(update):
        return
    v = update.message.voice if update.message else None
    if not v:
        return
    status = await update.message.reply_text("🎙️ Verarbeite Sprachnachricht …")
    try:
        # Check for ffmpeg early (required for OGG -> WAV)
        import shutil as _shutil
        if _shutil.which("ffmpeg") is None:
            await status.edit_text(
                "❌ ffmpeg nicht gefunden. Bitte ffmpeg installieren und in PATH aufnehmen (siehe README)."
            )
            return
        f = await context.bot.get_file(v.file_id)
        import tempfile
        import os as _os
        with tempfile.TemporaryDirectory() as td:
            ogg_path = Path(td) / "voice.ogg"
            await f.download_to_drive(custom_path=str(ogg_path))
            wav_path = ensure_wav(ogg_path)
            # STT (default: de)
            stt_lang = (os.getenv("STT_LANGUAGE") or "de").strip()
            text = await asyncio.to_thread(speech_to_text, wav_path, stt_lang)
            if not text:
                text = ""
            # TTS mit ElevenLabs
            audio_path = await asyncio.to_thread(eleven_tts_to_file, text or "…")
            # In Chat senden
            with open(audio_path, "rb") as f_audio:
                await context.bot.send_audio(
                    chat_id=update.effective_chat.id,
                    audio=f_audio,
                    filename=audio_path.name,
                    title="Spot Speech",
                    caption=f"🗣️ STT→TTS: {html_escape(text) if text else '(leer)'}",
                )
            # Lokal abspielen
            audio_manager: AudioManager = context.application.bot_data.get("audio_manager")
            if isinstance(audio_manager, AudioManager):
                audio_manager.play_in_background(str(audio_path))
                audio_manager.schedule_cleanup(audio_path)
        await status.edit_text("✅ Sprachnachricht in Text umgewandelt und vorgelesen.")
    except Exception as e:
        logger.exception(e)
        await status.edit_text("❌ Konnte Sprachnachricht nicht verarbeiten. Prüfe STT/ffmpeg/Modelle.")

# -----------------------------------------------------------------------------
# 7) Audio message handler (file uploads)
# -----------------------------------------------------------------------------

async def on_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_unauthorized(update):
        return
    a = update.message.audio if update.message else None
    if not a:
        return
    status = await update.message.reply_text("🎶 Verarbeite Audiodatei …")
    try:
        f = await context.bot.get_file(a.file_id)
        import tempfile
        import shutil as _shutil
        with tempfile.TemporaryDirectory() as td:
            in_path = Path(td) / (a.file_name or "audio")
            await f.download_to_drive(custom_path=str(in_path))
            try:
                wav_path = ensure_wav(in_path)
            except Exception as conv_err:
                # Wenn bereits WAV und Konvertierung nicht nötig ist, nutzen
                if in_path.suffix.lower() == ".wav":
                    wav_path = in_path
                else:
                    await status.edit_text(
                        "❌ Konnte Audiodatei nicht in WAV konvertieren. Prüfe ffmpeg-Installation."
                    )
                    return
            stt_lang = (os.getenv("STT_LANGUAGE") or "de").strip()
            text = await asyncio.to_thread(speech_to_text, wav_path, stt_lang)
            audio_path = await asyncio.to_thread(eleven_tts_to_file, text or "…")
            with open(audio_path, "rb") as f_audio:
                await context.bot.send_audio(
                    chat_id=update.effective_chat.id,
                    audio=f_audio,
                    filename=audio_path.name,
                    title="Spot Speech",
                    caption=f"🗣️ STT→TTS: {html_escape(text) if text else '(leer)'}",
                )
            audio_manager: AudioManager = context.application.bot_data.get("audio_manager")
            if isinstance(audio_manager, AudioManager):
                audio_manager.play_in_background(str(audio_path))
                audio_manager.schedule_cleanup(audio_path)
        await status.edit_text("✅ Audiodatei in Text umgewandelt und vorgelesen.")
    except Exception as e:
        logger.exception(e)
        await status.edit_text("❌ Konnte Audiodatei nicht verarbeiten. Prüfe STT/ffmpeg/Modelle.")

def build_help_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📇 Whoami", callback_data="whoami"),
            InlineKeyboardButton("📊 Status", callback_data="status"),
        ]
    ])

def build_mission_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📷 Foto", callback_data="photo"),
            InlineKeyboardButton("📊 Status", callback_data="status"),
            InlineKeyboardButton("🛑 Abbrechen", callback_data="abort"),
        ]
    ])


async def photo_action(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    frame = await asyncio.to_thread(capture_frame_bgr, 0, 3)
    if frame is None:
        await context.bot.send_message(chat_id, "❌ Kamera nicht verfügbar (anderes Programm offen? Index falsch?).")
        return
    buf = encode_jpeg(frame, quality=90)
    if buf is None:
        await context.bot.send_message(chat_id, "❌ Konnte Bild nicht encodieren.")
        return
    bio = BytesIO(buf)
    bio.name = "snapshot.jpg"
    await context.bot.send_photo(chat_id=chat_id, photo=bio, caption="📸 Snapshot")


async def abort_action(chat_id: int, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    s = get_state(chat_id)
    lock = get_lock(chat_id)
    async with lock:
        if not s.active:
            await context.bot.send_message(chat_id, "ℹ️ Es läuft gerade keine Mission.")
            return
        if s.current_user_id != user_id:
            await context.bot.send_message(chat_id, "⛔ Du kannst nur deine eigene Mission abbrechen.")
            return
        s.eta_seconds = 0
        s.started_at = time.time() - 1
    await context.bot.send_message(chat_id, "🛑 Mission abgebrochen.")


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = (query.data or "") if query else ""
    if not query or not query.message:
        return
    chat_id = query.message.chat_id
    user_id = query.from_user.id

    if not is_authorized(update):
        await query.answer("⛔ Nicht autorisiert.", show_alert=True)
        return

    try:
        if data == "photo":
            await query.answer("📷 Foto…")
            await photo_action(chat_id, context)
        elif data == "whoami":
            await query.answer("📇 Whoami…")
            await context.bot.send_message(chat_id, f"🆔 Deine Telegram-User-ID: {user_id}")
        elif data == "status":
            await query.answer("📊 Status…")
            s = get_state(chat_id)
            if not s.active:
                await context.bot.send_message(chat_id, "🟢 Keine aktive Mission. Warteschlange ist leer.")
            else:
                user = await context.bot.get_chat(s.current_user_id)
                display_name = user.first_name or (user.username or str(user.id))
                txt = render_status_html(display_name, s)
                await context.bot.send_message(chat_id, txt, parse_mode="HTML")
        elif data == "abort":
            await query.answer("🛑 Abbruch…")
            await abort_action(chat_id, user_id, context)
        else:
            await query.answer("Unbekannte Aktion.", show_alert=True)
    except Exception as e:
        logger.exception(e)
        await query.answer("Fehler ausgeführt. Siehe Logs.", show_alert=True)


# -----------------------------------------------------------------------------
# 6) Spot status (optional)
# -----------------------------------------------------------------------------

async def spot_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_if_unauthorized(update):
        return
    spot = context.application.bot_data.get("spot") if hasattr(context, "application") else None
    if not spot:
        await update.message.reply_text("Spot ist nicht konfiguriert. Setze SPOT_HOST/USERNAME/PASSWORD in .env.")
        return
    try:
        txt = await asyncio.to_thread(spot.get_status_summary)
    except Exception as e:
        txt = f"nicht verfügbar ({e})"
    await update.message.reply_text(f"🤖 {txt}")

# -----------------------------------------------------------------------------
# 7) App bootstrap
# -----------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s:%(name)s: %(message)s")
    if not BOT_TOKEN:
        raise RuntimeError("Kein BOT_TOKEN gefunden. Trage es in .env ein (BOT_TOKEN=...).")

    app = Application.builder().token(BOT_TOKEN).build()

    # Globalen AudioManager bereitstellen
    app.bot_data["audio_manager"] = AudioManager(app)
    # Optional: SpotController (aus .env)
    try:
        from .spot_control import SpotController as _SC  # type: ignore
    except Exception:
        try:
            from spot_control import SpotController as _SC  # type: ignore
        except Exception:
            _SC = None  # type: ignore
    app.bot_data["spot"] = (_SC.from_env() if _SC else None)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("whoami", whoami))
    app.add_handler(CommandHandler("say", say))
    app.add_handler(CommandHandler("photo", photo))
    app.add_handler(CommandHandler("play", play))
    app.add_handler(CommandHandler("gipfeli", gipfeli))
    app.add_handler(CommandHandler("gipfeli_status", gipfeli_status))
    app.add_handler(CommandHandler("status", status_alias))
    app.add_handler(CommandHandler("spot_status", spot_status))
    app.add_handler(CommandHandler("abort", abort))
    app.add_handler(CommandHandler("speech", speech))
    app.add_handler(CallbackQueryHandler(on_button))
    # Voice messages: STT -> TTS pipeline
    app.add_handler(MessageHandler(filters.VOICE, on_voice))
    app.add_handler(MessageHandler(filters.AUDIO, on_audio))

    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    logger.info("Bot startet Polling … (Strg+C zum Beenden)")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
