import os
import logging
from typing import Set, Tuple

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load environment variables once at import
load_dotenv()

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()

_raw_allowed = (os.getenv("ALLOWED_CHAT_IDS") or "").strip()
ALLOWED_CHAT_IDS: Set[str] = {cid.strip() for cid in _raw_allowed.split(",") if cid.strip()}


def get_eleven_config() -> Tuple[str, str, str]:
    api_key = (os.getenv("ELEVEN_API_KEY") or "").strip()
    voice_id = (os.getenv("ELEVEN_VOICE_ID") or "").strip()
    model_id = (os.getenv("ELEVEN_MODEL_ID") or "eleven_multilingual_v2").strip()
    return api_key, voice_id, model_id


def get_spot_config() -> Tuple[str, str, str]:
    """Return Spot SDK connection parameters (host, username, password).
    Empty strings indicate not configured.
    """
    host = (os.getenv("SPOT_HOST") or "").strip()
    user = (os.getenv("SPOT_USERNAME") or "").strip()
    pwd = (os.getenv("SPOT_PASSWORD") or "").strip()
    return host, user, pwd
