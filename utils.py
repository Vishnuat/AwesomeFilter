import logging
import re
import os
import asyncio
import functools
from typing import Union, List, Tuple, Dict, Any
import aiohttp
from imdb import Cinemagoer
from pyrogram import Client, enums
from pyrogram.types import Message, InlineKeyboardButton
from pyrogram.errors import (
    InputUserDeactivated,
    UserNotParticipant,
    FloodWait,
    UserIsBlocked,
    PeerIdInvalid
)
from info import (
    AUTH_CHANNEL,
    LONG_IMDB_DESCRIPTION,
    MAX_LIST_ELM,
    SHORTNER_API,
    SHORTNER_SITE,
    SHORTENER_ENABLED
)
from database.users_chats_db import db

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BTN_URL_REGEX = re.compile(
    r"(\[([^\[]+?)\]\((buttonurl|buttonalert):(?:/{0,2})(.+?)(:same)?\))"
)

# Global state - consider refactoring in the future
class temp(object):
    BANNED_USERS: List[int] = []
    BANNED_CHATS: List[int] = []
    ME: Any = None
    CURRENT: int = int(os.environ.get("SKIP", 2))
    CANCEL: bool = False
    MELCOW: Dict[Any, Any] = {}
    U_NAME: str = None
    B_NAME: str = None
    SETTINGS: Dict[int, Dict[str, Any]] = {}

def get_size(size: float) -> str:
    """Converts bytes to a human-readable format."""
    if not size:
        return ""
    power = 1024
    n = 0
    power_labels = {0: 'B', 1: 'KB', 2: 'MB', 3: 'GB', 4: 'TB'}
    while size >= power and n < len(power_labels) - 1:
        size /= power
        n += 1
    return f"{size:.2f} {power_labels[n]}"

def get_file_id(msg: Message) -> Any:
    """Extracts file object from a Pyrogram message."""
    if msg.media:
        for file_type in ("photo", "animation", "audio", "document", "video", "video_note", "voice", "sticker"):
            if obj := getattr(msg, file_type, None):
                return obj
    return None

async def get_poster(query: str, bulk: bool = False, id: bool = False, file: str = None) -> Union[Dict[str, Any], List[Dict[str, Any]], None]:
    """Get poster from IMDb."""
    imdb = Cinemagoer()
    if id:
        movie = imdb.get_movie(query)
    else:
        movies = imdb.search_movie(query.lower(), results=10)
        if not movies:
            return None
        movie = movies[0]
    
    if movie:
        return movie
    return None


async def get_shortlink(link: str) -> str:
    """Get a short link from the shortener API."""
    if not SHORTENER_ENABLED:
        return link
        
    api_url = f'https://{SHORTNER_SITE}/api'
    params = {'api': SHORTNER_API, 'url': link}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, params=params, raise_for_status=True, timeout=5) as response:
                data = await response.json()
                if data.get("status") == "success":
                    return data.get('shortenedUrl')
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.error(f"Shortlink API error: {e}")
    
    return link
