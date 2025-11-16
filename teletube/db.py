import os
import json
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any

from .config import DATABASE_FILE, COOLDOWN_HOURS

_db_lock = asyncio.Lock()
_inmemory_tasks: Dict[int, asyncio.Task] = {}


def load_data() -> Dict[int, Dict[str, Any]]:
    if not os.path.exists(DATABASE_FILE):
        return {}
    try:
        with open(DATABASE_FILE, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        return {int(k): v for k, v in raw.items()}
    except Exception:
        return {}


async def save_data_async(data: Dict[int, Dict[str, Any]]):
    async with _db_lock:
        tmp = DATABASE_FILE + ".tmp"
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            os.replace(tmp, DATABASE_FILE)
        except Exception:
            if os.path.exists(tmp):
                try: os.remove(tmp)
                except: pass


def get_user_data(user_id: int, data: Dict[int, Dict[str, Any]], username: str) -> Dict[str, Any]:
    if user_id not in data:
        now_ts = datetime.now().timestamp()
        data[user_id] = {
            'username': username,
            'subscribers': 0,
            'last_used_timestamp': 0.0,
            'video_count': 0,
            'active_event': None,
            'currency': 0,
            'achievements_unlocked': [],
            'last_daily_bonus_date': None,
            'daily_bonus_streak': 0,
            'total_subs_from_videos': 0,
            'cooldown_notification_task': None,
            'created_at': now_ts,
        }
    if data[user_id].get('username') != username:
        data[user_id]['username'] = username
    return data[user_id]


async def _cooldown_notify_task(bot, user_id: int, chat_id: int, when_ts: float):
    now = datetime.now().timestamp()
    delay = max(0, when_ts - now)
    try:
        await asyncio.sleep(delay)
        data = load_data()
        u = data.get(user_id)
        if not u:
            return
        last_ts = u.get('last_used_timestamp', 0.0)
        next_allowed = last_ts + COOLDOWN_HOURS * 3600
        if datetime.now().timestamp() >= next_allowed:
            await bot.send_message(chat_id=chat_id, text=f"⏰ Ваш кулдаун завершён! Можете добавить новое видео: /addvideo")
            u['cooldown_notification_task'] = None
            await save_data_async(data)
    except asyncio.CancelledError:
        return
    except Exception:
        return


def schedule_cooldown_notification(bot, user_id: int, chat_id: int, cooldown_end_time: datetime):
    prev = _inmemory_tasks.get(user_id)
    if prev and not prev.done():
        prev.cancel()
    task = asyncio.create_task(_cooldown_notify_task(bot, user_id, chat_id, cooldown_end_time.timestamp()))
    _inmemory_tasks[user_id] = task
    data = load_data()
    u = data.get(user_id)
    if u:
        u['cooldown_notification_task'] = {'ends_at': cooldown_end_time.timestamp()}
        asyncio.create_task(save_data_async(data))
