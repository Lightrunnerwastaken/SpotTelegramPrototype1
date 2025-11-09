from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path

from flask import Flask, jsonify, request, send_file

try:
    from .spot_control import SpotController  # type: ignore
except Exception:  # fallback
    from spot_control import SpotController  # type: ignore

try:
    from .tts import eleven_tts_to_file  # type: ignore
    from .media import ensure_wav  # type: ignore
except Exception:
    from tts import eleven_tts_to_file  # type: ignore
    from media import ensure_wav  # type: ignore


def create_app() -> Flask:
    app = Flask(__name__)
    spot = SpotController.from_env()

    api_token = (os.getenv("API_TOKEN") or "").strip()

    def _check_auth() -> tuple[bool, str | None]:
        if not api_token:
            return True, None
        # Accept Authorization: Bearer <token> or query param api_token
        auth = request.headers.get("Authorization", "")
        parts = auth.split()
        if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1] == api_token:
            return True, None
        if request.args.get("api_token") == api_token:
            return True, None
        return False, "Unauthorized"

    @app.get("/health")
    def health():
        ok, msg = _check_auth()
        if not ok:
            return jsonify({"error": msg}), 401
        return jsonify({"ok": True})

    @app.get("/")
    def index():
        # Root overview does not require auth; shows how to authenticate if configured
        return jsonify({
            "ok": True,
            "message": "Spot v0 Bot REST API",
            "auth": {
                "token_required": bool(api_token),
                "how": "Authorization: Bearer <token> header or ?api_token=<token> query param" if api_token else "disabled"
            },
            "endpoints": [
                {"method": "GET", "path": "/health", "auth": "required" if api_token else "optional"},
                {"method": "GET", "path": "/spot/status", "auth": "required" if api_token else "optional"},
                {"method": "GET", "path": "/spot/photo?source=frontleft_fisheye_image", "auth": "required" if api_token else "optional"},
                {"method": "POST", "path": "/spot/power_on_and_stand", "auth": "required" if api_token else "optional"},
                {"method": "POST", "path": "/spot/navigate", "body": {"waypoint_id": "..."}, "auth": "required" if api_token else "optional"},
                {"method": "POST", "path": "/spot/say", "body": {"text": "..."}, "auth": "required" if api_token else "optional"}
            ]
        })

    @app.get("/spot/status")
    def spot_status():
        ok, msg = _check_auth()
        if not ok:
            return jsonify({"error": msg}), 401
        if not spot:
            return jsonify({"error": "Spot nicht konfiguriert"}), 400
        return jsonify({"summary": spot.get_status_summary()})

    @app.get("/spot/photo")
    def spot_photo():
        ok, msg = _check_auth()
        if not ok:
            return jsonify({"error": msg}), 401
        if not spot:
            return jsonify({"error": "Spot nicht konfiguriert"}), 400
        source = request.args.get("source") or (os.getenv("SPOT_IMAGE_SOURCE") or "frontleft_fisheye_image")
        data = spot.capture_image_jpeg(source)
        return send_file(BytesIO(data), mimetype="image/jpeg", download_name="spot.jpg")

    @app.post("/spot/power_on_and_stand")
    def spot_power_on():
        ok, msg = _check_auth()
        if not ok:
            return jsonify({"error": msg}), 401
        if not spot:
            return jsonify({"error": "Spot nicht konfiguriert"}), 400
        msg = spot.power_on_and_stand()
        return jsonify({"message": msg})

    @app.post("/spot/navigate")
    def spot_navigate():
        ok, msg = _check_auth()
        if not ok:
            return jsonify({"error": msg}), 401
        if not spot:
            return jsonify({"error": "Spot nicht konfiguriert"}), 400
        payload = request.get_json(silent=True) or {}
        waypoint_id = payload.get("waypoint_id") or request.args.get("waypoint_id")
        if not waypoint_id:
            return jsonify({"error": "waypoint_id fehlt"}), 400
        msg = spot.navigate_to_waypoint(str(waypoint_id))
        return jsonify({"message": msg})

    @app.post("/spot/say")
    def spot_say():
        ok, msg = _check_auth()
        if not ok:
            return jsonify({"error": msg}), 401
        if not spot:
            return jsonify({"error": "Spot nicht konfiguriert"}), 400
        payload = request.get_json(silent=True) or {}
        text = (payload.get("text") or "").strip()
        if not text:
            return jsonify({"error": "text fehlt"}), 400
        audio_path = eleven_tts_to_file(text)
        wav_path = ensure_wav(Path(audio_path)) if isinstance(audio_path, (str, Path)) else audio_path
        msg = spot.play_audio_file(str(wav_path))
        return jsonify({"message": msg})

    return app


if __name__ == "__main__":
    host = os.getenv("API_HOST") or "127.0.0.1"
    port = int(os.getenv("API_PORT") or 8000)
    app = create_app()
    app.run(host=host, port=port)
