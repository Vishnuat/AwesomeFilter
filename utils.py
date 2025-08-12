import logging
import re
import os
import asyncio
import functools
from typing import Union, List, Tuple, Dict, Any

import aiohttp
from bs4 import BeautifulSoup
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
SMART_OPEN = '“'
SMART_CLOSE = '”'
START_CHAR = ('\'', '"', SMART_OPEN)

imdb = Cinemagoer()
aiohttp_session = aiohttp.ClientSession()

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
    """Converts bytes to a human-readable format (e.g., KB, MB, GB)."""
    if not size:
        return ""
    power = 1024
    n = 0
    power_labels = {0: 'B', 1: 'KB', 2: 'MB', 3: 'GB', 4: 'TB'}
    while size >= power and n < len(power_labels) - 1:
        size /= power
        n += 1
    return f"{size:.2f} {power_labels[n]}"

def list_to_str(data: list) -> str:
    if not data:
        return "N/A"
    if MAX_LIST_ELM and len(data) > int(MAX_LIST_ELM):
        data = data[:int(MAX_LIST_ELM)]
    return ", ".join(map(str, data))

def get_file_id(msg: Message) -> Any:
    if msg.media:
        for file_type in ("photo", "animation", "audio", "document", "video", "video_note", "voice", "sticker"):
            if obj := getattr(msg, file_type, None):
                return obj
    return None

def extract_user(message: Message) -> Union[int, str]:
    user_id = None
    if message.reply_to_message:
        user_id = message.reply_to_message.from_user.id
    elif len(message.command) > 1:
        if (
            len(message.entities) > 1 and
            message.entities[1].type == enums.MessageEntityType.TEXT_MENTION
        ):
            user_id = message.entities[1].user.id
        else:
            user_id = message.command[1]
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            pass
    else:
        user_id = message.from_user.id
    return user_id

def split_quotes(text: str) -> List:
    if not any(text.startswith(char) for char in START_CHAR):
        return text.split(None, 1)
    counter = 1
    while counter < len(text):
        if text[counter] == "\\":
            counter += 1
        elif text[counter] == text[0] or \
             (text[0] == SMART_OPEN and text[counter] == SMART_CLOSE):
            break
        counter += 1
    else:
        return text.split(None, 1)
    key = remove_escapes(text[1:counter].strip())
    rest = text[counter + 1:].strip()
    if not key:
        key = text[0] + text[0]
    return list(filter(None, [key, rest]))

def remove_escapes(text: str) -> str:
    res = ""
    is_escaped = False
    for char in text:
        if is_escaped:
            res += char
            is_escaped = False
        elif char == "\\":
            is_escaped = True
        else:
            res += char
    return res

async def is_subscribed(bot: Client, query: Message) -> bool:
    try:
        user = await bot.get_chat_member(AUTH_CHANNEL, query.from_user.id)
        return user.status not in [enums.ChatMemberStatus.BANNED]
    except UserNotParticipant:
        return False
    except Exception as e:
        logger.error(f"Error checking subscription for {query.from_user.id}: {e}")
        return False

async def broadcast_messages(user_id: int, message: Message) -> Tuple[bool, str]:
    try:
        await message.copy(chat_id=user_id)
        return True, "Success"
    except FloodWait as e:
        await asyncio.sleep(e.value)
        return await broadcast_messages(user_id, message)
    except (InputUserDeactivated, UserIsBlocked, PeerIdInvalid) as e:
        await db.delete_user(int(user_id))
        logger.info(f"{user_id} - Removed from DB due to: {e.__class__.__name__}")
        return False, e.__class__.__name__
    except Exception as e:
        logger.error(f"Error broadcasting to {user_id}: {e}")
        return False, "Error"

async def get_poster(query: str, bulk: bool = False, id: bool = False, file: str = None) -> Union[Dict[str, Any], List[Dict[str, Any]], None]:
    loop = asyncio.get_running_loop()
    if not id:
        query = query.strip().lower()
        title = query
        year_match = re.findall(r'[1-2]\d{3}$', query, re.IGNORECASE) or \
                     (file and re.findall(r'[1-2]\d{3}', file, re.IGNORECASE))
        year = year_match[0] if year_match else None
        if year:
            title = query.replace(year, "").strip()
        search_func = functools.partial(imdb.search_movie, title, results=10)
        movies = await loop.run_in_executor(None, search_func)
        if not movies:
            return None
        if year:
            movies = [m for m in movies if str(m.get('year')) == year] or movies
        filtered = [m for m in movies if m.get('kind') in ['movie', 'tv series']] or movies
        if bulk:
            return filtered
        if not filtered:
            return None
        movie_id = filtered[0].movieID
    else:
        movie_id = query
    get_movie_func = functools.partial(imdb.get_movie, movie_id)
    movie = await loop.run_in_executor(None, get_movie_func)
    plot = movie.get('plot outline') if LONG_IMDB_DESCRIPTION else (movie.get('plot') and movie.get('plot')[0])
    if plot and len(plot) > 800:
        plot = plot[:800] + "..."
    return {
        'title': movie.get('title', 'N/A'),
        'votes': movie.get('votes', 'N/A'),
        "aka": list_to_str(movie.get("akas")),
        "seasons": movie.get("number of seasons"),
        "box_office": movie.get('box office'),
        'localized_title': movie.get('localized title'),
        'kind': movie.get("kind"),
        "imdb_id": f"tt{movie.get('imdbID')}",
        "cast": list_to_str(movie.get("cast")),
        "runtime": list_to_str(movie.get("runtimes")),
        "countries": list_to_str(movie.get("countries")),
        "certificates": list_to_str(movie.get("certificates")),
        "languages": list_to_str(movie.get("languages")),
        "director": list_to_str(movie.get("director")),
        "writer": list_to_str(movie.get("writer")),
        "producer": list_to_str(movie.get("producer")),
        "composer": list_to_str(movie.get("composer")),
        "cinematographer": list_to_str(movie.get("cinematographer")),
        "music_team": list_to_str(movie.get("music department")),
        "distributors": list_to_str(movie.get("distributors")),
        'release_date': movie.get("original air date") or movie.get("year", "N/A"),
        'year': movie.get('year', 'N/A'),
        'genres': list_to_str(movie.get("genres")),
        'poster': movie.get('full-size cover url'),
        'plot': plot or "N/A",
        'rating': str(movie.get("rating", "N/A")),
        'url': f'https://www.imdb.com/title/tt{movie_id}'
    }

async def get_shortlink(link: str) -> str:
    if not SHORTENER_ENABLED:
        return link
    api_url = f'https://{SHORTNER_SITE}/api'
    params = {'api': SHORTNER_API, 'url': link}
    try:
        async with aiohttp_session.get(api_url, params=params, raise_for_status=True, timeout=5) as response:
            data = await response.json()
            return data.get('shortenedUrl') if data.get("status") == "success" else link
    except aiohttp.ClientError as e:
        logger.error(f"Shortlink API error: {e}")
        return link
    except asyncio.TimeoutError:
        logger.error("Shortlink API request timed out.")
        return link

async def get_settings(group_id: int) -> Dict[str, Any]:
    if group_id not in temp.SETTINGS:
        temp.SETTINGS[group_id] = await db.get_settings(group_id)
    return temp.SETTINGS[group_id]

async def save_group_settings(group_id: int, key: str, value: Any):
    settings = await get_settings(group_id)
    settings[key] = value
    temp.SETTINGS[group_id] = settings
    await db.update_settings(group_id, settings)

def parser(text: str, keyword: str) -> Tuple[str, List[List[InlineKeyboardButton]], List[str]]:
    buttons = []
    alerts = []
    note_data = ""
    prev = 0
    alert_index = 0
    for match in BTN_URL_REGEX.finditer(text):
        n_escapes = text[:match.start(1)].count('\\')
        if n_escapes % 2 != 0:
            note_data += text[prev:match.start(1)-1]
            prev = match.start(1)
            continue
        note_data += text[prev:match.start(1)]
        prev = match.end(1)
        btn_text = match.group(2)
        btn_type = match.group(3)
        btn_content = match.group(4)
        same_line = bool(match.group(5)) and buttons
        if btn_type == "buttonalert":
            callback_data = f"alertmessage:{alert_index}:{keyword}"
            button = InlineKeyboardButton(text=btn_text, callback_data=callback_data)
            alerts.append(btn_content)
            alert_index += 1
        else:
            button = InlineKeyboardButton(text=btn_text, url=btn_content.replace(" ", ""))
        if same_line:
            buttons[-1].append(button)
        else:
            buttons.append([button])
    note_data += text[prev:]
    return note_data, buttons, alerts

async def search_gagala(text):
    if " " in text:
        text = text.replace(" ", "+")
    url = f"https://www.google.com/search?q={text}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=5) as response:
                if response.status == 200:
                    soup = BeautifulSoup(await response.text(), "html.parser")
                    results = []
                    for g in soup.find_all('div', class_='g'):
                        t = g.find('h3')
                        if t:
                            results.append(t.text)
                    return results
                else:
                    return []
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.error(f"Google search error: {e}")
        return []
