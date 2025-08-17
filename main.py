import asyncio
import logging
import os
import random
import json
from datetime import datetime, timedelta, date
from typing import Dict, Any, Optional, List, Callable, Coroutine

from dotenv import load_dotenv

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from aiogram import Bot, Dispatcher, types
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardButton, InlineKeyboardMarkup, InputFile
)
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.enums import ChatMemberStatus

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CREATOR_ID = int(os.getenv("CREATOR_ID", "0") or 0)
CHANNEL_ID = os.getenv("CHANNEL_ID")
BOT_NAME = os.getenv("BOT_NAME", "Мой Бот")

DATABASE_FILE = os.getenv("DATABASE_FILE", "database.json")
KEYWORDS_FILE = os.getenv("KEYWORDS_FILE", "keywords.txt")
LEADERBOARD_IMAGE_FILE = os.getenv("LEADERBOARD_IMAGE_FILE", "leaderboard_pic.png")

COOLDOWN_HOURS = float(os.getenv("COOLDOWN_HOURS", 12))
POPULARITY_THRESHOLD_BONUS = int(os.getenv("POPULARITY_THRESHOLD_BONUS", 7))
KEYWORD_BONUS_POINTS = int(os.getenv("KEYWORD_BONUS_POINTS", 2))
POPULARITY_RANDOM_MIN = int(os.getenv("POPULARITY_RANDOM_MIN", -10))
POPULARITY_RANDOM_MAX = int(os.getenv("POPULARITY_RANDOM_MAX", 20))
BONUS_SUBSCRIBERS_MIN = int(os.getenv("BONUS_SUBSCRIBERS_MIN", 1))
BONUS_SUBSCRIBERS_MAX = int(os.getenv("BONUS_SUBSCRIBERS_MAX", 5))
NEGATIVE_POPULARITY_THRESHOLD = int(os.getenv("NEGATIVE_POPULARITY_THRESHOLD", -5))

DEFAULT_CURRENCY_NAME = os.getenv("DEFAULT_CURRENCY_NAME", "TeleCoin")
DAILY_BONUS_AMOUNT = int(os.getenv("DAILY_BONUS_AMOUNT", 10))
DAILY_BONUS_STREAK_MULTIPLIER = float(os.getenv("DAILY_BONUS_STREAK_MULTIPLIER", 1.2))

LOG_LEVEL_STR = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL_STR, logging.INFO),
                    format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

achievements_definition: Dict[str, Dict[str, Any]] = {
    "newbie_blogger": {"name": "🌱 Новичок Блогер", "condition_videos": 1, "reward_coins": 5},
    "rising_star": {"name": "🌟 Восходящая Звезда", "condition_videos": 5, "reward_coins": 25},
    "serial_publisher": {"name": "🎬 Серийный Публицист", "condition_videos": 10, "reward_coins": 50},
    "first_hundred": {"name": "💯 Первая Сотня", "condition_subs": 100, "reward_coins": 100},
    "popular_choice": {"name": "🔥 Народный Любимец", "condition_subs": 500, "reward_coins": 250},
    "video_marathoner": {"name": "🏃 Видеомарафонец", "condition_videos": 25, "reward_coins": 100},
    "content_machine": {"name": "⚙️ Контент-Машина", "condition_videos": 50, "reward_coins": 250},
    "first_thousand": {"name": "🌐 Первая Тысяча", "condition_subs": 1000, "reward_coins": 500},
    "influencer": {"name": "👑 Инфлюенсер", "condition_subs": 5000, "reward_coins": 1000},
    "superstar": {"name": "🚀 Суперзвезда", "condition_subs": 10000, "reward_coins": 2500},
    "early_bird": {"name": "🐣 Ранний Пташка", "condition_days_since_signup": 7, "reward_coins": 10},
    "dedicated_creator": {"name": "📅 Преданный Создатель", "condition_days_active": 30, "reward_coins": 100},
    "loyal_fanbase": {"name": "🤝 Преданная Аудитория", "condition_subs": 2500, "reward_coins": 750},
    "milestone_master": {"name": "🏆 Мастер Этапов", "condition_videos": 100, "reward_coins": 500},
    "viral_hit": {"name": "💥 Вирусный Хит", "condition_video_views": 100000, "reward_coins": 1000},
}

shop_items: Dict[str, Dict[str, Any]] = {
    "popularity_boost_small": {
        "name": "🚀 Малый Усилитель Популярности",
        "description": "Увеличивает популярность следующего видео на +5.",
        "price": 50,
        "effect": {"type": "event_modifier", "modifier": 5, "target": "next_video_popularity"}
    },
    "cooldown_reset": {
        "name": "⏱️ Сброс Кулдауна",
        "description": "Позволяет немедленно опубликовать следующее видео.",
        "price": 100,
        "effect": {"type": "cooldown_reset"}
    },
}

_db_lock = asyncio.Lock()
_inmemory_tasks: Dict[int, asyncio.Task] = {}

def load_data() -> Dict[int, Dict[str, Any]]:
    if not os.path.exists(DATABASE_FILE):
        return {}
    try:
        with open(DATABASE_FILE, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        return {int(k): v for k, v in raw.items()}
    except Exception as e:
        logger.error("load_data error: %s", e)
        return {}

async def save_data_async(data: Dict[int, Dict[str, Any]]):
    async with _db_lock:
        tmp = DATABASE_FILE + ".tmp"
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            os.replace(tmp, DATABASE_FILE)
        except Exception as e:
            logger.exception("save_data_async error: %s", e)
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

def load_keywords(filename: str = KEYWORDS_FILE) -> List[str]:
    if not os.path.exists(filename):
        with open(filename, 'w', encoding='utf-8') as f:
            f.write("популярное\nхайп\n")
        return ["популярное", "хайп"]
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return [ln.strip().lower() for ln in f if ln.strip() and not ln.startswith('#')]
    except Exception as e:
        logger.error("load_keywords error: %s", e)
        return []

def evaluate_video_popularity(video_title: str, base_popularity_modifier: int = 0, user_subs: int = 0) -> int:
    title = video_title.strip().lower()
    keywords = load_keywords()
    keyword_bonus = sum(KEYWORD_BONUS_POINTS for k in keywords if k in title)
    words = max(1, len(title.split()))
    length_bonus = min(3, (words // 4))
    volatility = 1.0 + max(0, 10 - min(user_subs, 100)) / 20.0
    rand = random.randint(POPULARITY_RANDOM_MIN, POPULARITY_RANDOM_MAX)
    raw = keyword_bonus + length_bonus + rand + base_popularity_modifier
    adjusted = int(round(raw * volatility))
    return max(-50, min(500, adjusted))

def get_random_event(user_subscribers: int) -> Optional[Dict[str, Any]]:
    r = random.random()
    if r < 0.03 and user_subscribers >= 5:
        bonus = random.randint(20, 60)
        return {"type": "event_modifier", "modifier": bonus, "target": "next_video_popularity",
                "message": f"🎉 Вирусный всплеск! +{bonus} к популярности следующего видео!"}
    if 0.03 <= r < 0.12:
        bonus = random.randint(3, 7)
        return {"type": "event_modifier", "modifier": bonus, "target": "next_video_popularity",
                "message": f"✨ Местный хайп: +{bonus} к следующему видео."}
    if 0.12 <= r < 0.16 and user_subscribers > 20:
        malus = random.randint(2, 6)
        return {"type": "event_modifier", "modifier": -malus, "target": "next_video_popularity",
                "message": f"📉 Технические проблемы: -{malus} к следующему видео."}
    return None

async def check_and_grant_achievements(user_data: Dict[str, Any], bot: Bot, chat_id: int) -> List[str]:
    newly = []
    for aid, adef in achievements_definition.items():
        if aid in user_data.get('achievements_unlocked', []):
            continue
        unlocked = False
        if "condition_videos" in adef and user_data.get('video_count', 0) >= adef['condition_videos']:
            unlocked = True
        if "condition_subs" in adef and user_data.get('subscribers', 0) >= adef['condition_subs']:
            unlocked = True
        if unlocked:
            user_data.setdefault('achievements_unlocked', []).append(aid)
            rc = adef.get('reward_coins', 0)
            user_data['currency'] = user_data.get('currency', 0) + rc
            text = f"🏆 Новое достижение: <b>{adef['name']}</b>! (+{rc} {DEFAULT_CURRENCY_NAME})"
            newly.append(text)
            try:
                await bot.send_message(chat_id=chat_id, text=text)
            except Exception as e:
                logger.error("notify achievement error: %s", e)
    return newly

def require_subscription(require: bool = True) -> Callable[[Callable[..., Coroutine]], Callable[..., Coroutine]]:
    def decorator(handler: Callable[..., Coroutine]) -> Callable[..., Coroutine]:
        async def wrapper(message: types.Message, bot: Bot, **kwargs):
            if not require or not CHANNEL_ID:
                return await handler(message, bot, **kwargs)
            
            user_id = message.from_user.id
            username = message.from_user.username or message.from_user.first_name
            logger.info(f"Checking subscription for user {user_id} (@{username}) in channel {CHANNEL_ID}")
            
            try:
                member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
                logger.info(f"User {user_id} status in {CHANNEL_ID}: {member.status}")
                
                if member.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR):
                    logger.info(f"User {user_id} is subscribed to {CHANNEL_ID}")
                    return await handler(message, bot, **kwargs)
                else:
                    logger.warning(f"User {user_id} is not subscribed to {CHANNEL_ID}. Status: {member.status}")
                    
            except Exception as e:
                logger.error(f"Error checking subscription for user {user_id} in {CHANNEL_ID}: {e}")
            
            logger.info(f"User {user_id} needs to subscribe to {CHANNEL_ID}")
            
            channel_link = CHANNEL_ID
            if CHANNEL_ID.startswith('@'):
                channel_link = f"https://t.me/{CHANNEL_ID[1:]}"
            elif CHANNEL_ID.startswith('-100'):
                channel_link = f"https://t.me/c/{CHANNEL_ID[4:]}"
            
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Перейти к каналу", url=channel_link)]])
            await message.answer(f"Подпишитесь на канал {CHANNEL_ID} чтобы пользоваться этой командой.", reply_markup=kb)
            return
        return wrapper
    return decorator

async def _cooldown_notify_task(bot: Bot, user_id: int, chat_id: int, when_ts: float):
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
            await bot.send_message(chat_id=chat_id, text=f"⏰ Ваш кулдаун в {BOT_NAME} завершён! Можете добавить новое видео: /addvideo")
            u['cooldown_notification_task'] = None
            await save_data_async(data)
    except asyncio.CancelledError:
        logger.debug("Cooldown notify task cancelled for user %s", user_id)
        return
    except Exception:
        logger.exception("Error in cooldown notify task for %s", user_id)

def schedule_cooldown_notification(bot: Bot, user_id: int, chat_id: int, cooldown_end_time: datetime):
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

async def cmd_start(message: types.Message, bot: Bot, **kwargs):
    data = load_data()
    ud = get_user_data(message.from_user.id, data, message.from_user.username or message.from_user.first_name)
    if ud.get('video_count', 0) == 0:
        await check_and_grant_achievements(ud, bot, message.chat.id)
        await save_data_async(data)
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="/addvideo Название Видео")],
        [KeyboardButton(text="/myprofile"), KeyboardButton(text="/shop")],
        [KeyboardButton(text="/leaderboard"), KeyboardButton(text="/achievements")],
        [KeyboardButton(text="/daily"), KeyboardButton(text="/help")]
    ], resize_keyboard=True)
    await message.answer(f"🚀 Привет, {message.from_user.first_name}! Ты в игре {BOT_NAME}!\nИспользуй /help или кнопки.", reply_markup=kb)

@require_subscription(require=True)
async def cmd_addvideo(message: types.Message, bot: Bot, **kwargs):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Укажи название: /addvideo Название")
        return
    video_title = args[1].strip()
    data = load_data()
    ud = get_user_data(message.from_user.id, data, message.from_user.username or message.from_user.first_name)

    last_used = datetime.fromtimestamp(ud.get('last_used_timestamp', 0.0))
    next_allowed = last_used + timedelta(hours=COOLDOWN_HOURS)
    if datetime.now() < next_allowed:
        rem = next_allowed - datetime.now()
        hours = rem.seconds // 3600
        minutes = (rem.seconds % 3600) // 60
        await message.answer(f"⏳ Кулдаун! Через {hours} ч {minutes} мин.")
        return

    event_mod = 0
    msgs = []
    ae = ud.get('active_event')
    if ae:
        msgs.append(f"✨ Активное событие: {ae.get('message')}")
        if ae.get('target') == 'next_video_popularity' and 'modifier' in ae:
            event_mod = ae['modifier']
        ud['active_event'] = None

    pop_score = evaluate_video_popularity(video_title, base_popularity_modifier=event_mod, user_subs=ud.get('subscribers', 0))
    subs_change = pop_score
    bonus_subs = 0
    msg_parts = [f"🎬 {ud['username']}, «{video_title}» опубликовано!"]
    if msgs:
        msg_parts.extend(msgs)

    if pop_score > POPULARITY_THRESHOLD_BONUS:
        bonus_subs = random.randint(BONUS_SUBSCRIBERS_MIN, BONUS_SUBSCRIBERS_MAX)
        subs_change += bonus_subs
        msg_parts.append(f"🌟 Супер! +{bonus_subs} бонус пдп.")
    elif pop_score < NEGATIVE_POPULARITY_THRESHOLD:
        msg_parts.append("📉 Не зашло...")
    elif pop_score < 0:
        msg_parts.append("😕 Не очень популярно.")
    else:
        msg_parts.append("👍 Неплохо!")

    ud['subscribers'] = max(0, ud.get('subscribers', 0) + subs_change)
    ud['last_used_timestamp'] = datetime.now().timestamp()
    ud['video_count'] = ud.get('video_count', 0) + 1
    ud['total_subs_from_videos'] = ud.get('total_subs_from_videos', 0) + (subs_change if subs_change > 0 else 0)

    if subs_change > 0:
        msg_parts.append(f"📈 +{subs_change} пдп.")
    elif subs_change < 0:
        msg_parts.append(f"📉 {subs_change} пдп.")
    else:
        msg_parts.append("🤷 Пдп не изменились.")
    msg_parts.append(f"Итого: {ud['subscribers']} пдп. (Видео: {ud['video_count']})")

    cooldown_end = datetime.fromtimestamp(ud['last_used_timestamp']) + timedelta(hours=COOLDOWN_HOURS)
    schedule_cooldown_notification(bot, message.from_user.id, message.chat.id, cooldown_end)

    new_ev = get_random_event(ud.get('subscribers', 0))
    if new_ev:
        ud['active_event'] = new_ev
        msg_parts.append(f"\n🔔 Событие: {new_ev['message']}")

    ach_msgs = await check_and_grant_achievements(ud, bot, message.chat.id)
    if ach_msgs:
        msg_parts.extend(ach_msgs)

    await save_data_async(data)
    await message.answer("\n".join(msg_parts))

async def cmd_leaderboard(message: types.Message, bot: Bot, **kwargs):
    data = load_data()
    if not data:
        await message.answer("🏆 В боте пока нет данных.")
        return
    users = sorted(data.values(), key=lambda u: u.get('subscribers', 0), reverse=True)
    msg = "🏆 <b>Топеры:</b>\n\n"
    shown = 0
    for u in users:
        if shown >= 15: break
        msg += f"{shown+1}. {u.get('username','N/A')} - {u.get('subscribers',0)} пдп. (видео: {u.get('video_count',0)})\n"
        shown += 1
    await message.answer(msg)

async def cmd_leaderboardpic(message: types.Message, bot: Bot, **kwargs):
    data = load_data()
    if not data:
        await message.answer("📊 Данных нет.")
        return
    df = pd.DataFrame.from_dict(data, orient='index')
    if 'subscribers' not in df.columns or df['subscribers'].isnull().all():
        await message.answer("📊 Проблема с данными пдп.")
        return
    df_valid = df[df['subscribers'] > 0].sort_values(by='subscribers', ascending=False)
    if df_valid.empty:
        await message.answer("📊 Нет юзеров с пдп > 0.")
        return
    top = df_valid.head(15)
    names = top['username'].astype(str).values
    subs = top['subscribers'].astype(int).values
    fig, ax = plt.subplots(figsize=(10, 7))
    wedges, texts, autotexts = ax.pie(subs, autopct=lambda p: f'{p:.1f}%' if p > 3 else '', startangle=140)
    ax.legend(wedges, [f"{n} ({s})" for n, s in zip(names, subs)], title="Топ", loc="center left", bbox_to_anchor=(1, 0, 0.5, 1))
    ax.set_title(f"🏆 Топ {BOT_NAME}еров")
    plt.tight_layout(rect=[0, 0, 0.75, 1])
    try:
        plt.savefig(LEADERBOARD_IMAGE_FILE, dpi=150, bbox_inches='tight')
        plt.close(fig)
        await message.answer_photo(photo=InputFile(LEADERBOARD_IMAGE_FILE))
    except Exception as e:
        logger.exception("leaderboard pic error: %s", e)
        await message.answer("Ошибка генерации картинки.")
    finally:
        if os.path.exists(LEADERBOARD_IMAGE_FILE):
            try: os.remove(LEADERBOARD_IMAGE_FILE)
            except: pass

async def cmd_myprofile(message: types.Message, bot: Bot, **kwargs):
    data = load_data()
    ud = get_user_data(message.from_user.id, data, message.from_user.username or message.from_user.first_name)
    uname = ud.get('username', message.from_user.first_name)
    subs = ud.get('subscribers', 0)
    vids = ud.get('video_count', 0)
    curr = ud.get('currency', 0)
    tot = ud.get('total_subs_from_videos', 0)
    avg = (tot / vids) if vids > 0 else 0.0
    out = [f"👤 <b>Твой профиль, {uname}:</b>",
           f"👥 Пдп: {subs}",
           f"💰 {DEFAULT_CURRENCY_NAME}: {curr}",
           f"📹 Видео: {vids}"]
    if vids > 0:
        out.append(f"📈 Сред. пдп/видео: {avg:.2f}")
    luts = ud.get('last_used_timestamp', 0)
    if luts == 0:
        out.append("🕓 Посл. видео: — (опубликуй что-нибудь /addvideo Название)")
    else:
        lut = datetime.fromtimestamp(luts)
        out.append(f"🕓 Посл. видео: {lut.strftime('%y-%m-%d %H:%M')}")
        nextt = lut + timedelta(hours=COOLDOWN_HOURS)
        if datetime.now() < nextt:
            rem = nextt - datetime.now()
            h = rem.seconds // 3600
            m = (rem.seconds % 3600) // 60
            out.append(f"⏳ Сл. видео через: {h}ч {m}м")
        else:
            out.append("✅ Можно публиковать новое!")
    if ud.get('active_event'):
        out.append(f"\n✨ <b>Активное событие:</b> {ud['active_event']['message']}")
    await save_data_async(data)
    await message.answer("\n".join(out), parse_mode="HTML")

async def cmd_achievements(message: types.Message, bot: Bot, **kwargs):
    data = load_data()
    ud = get_user_data(message.from_user.id, data, message.from_user.username or message.from_user.first_name)
    unlocked = ud.get('achievements_unlocked', [])
    if not unlocked:
        await message.answer("Пока нет достижений.")
        await save_data_async(data)
        return
    txt = "🏆 <b>Ваши достижения:</b>\n\n"
    for aid in unlocked:
        if aid in achievements_definition:
            txt += f"- {achievements_definition[aid]['name']}\n"
    txt += "\n🔍 <i>Неразблокированные (первые 3):</i>\n"
    cnt = 0
    for aid, ad in achievements_definition.items():
        if aid not in unlocked:
            txt += f"- ❓ {ad['name']}\n"
            cnt += 1
            if cnt >= 3:
                break
    await save_data_async(data)
    await message.answer(txt, parse_mode="HTML")

async def cmd_daily(message: types.Message, bot: Bot, **kwargs):
    data = load_data()
    ud = get_user_data(message.from_user.id, data, message.from_user.username or message.from_user.first_name)
    today_s = date.today().isoformat()
    last = ud.get('last_daily_bonus_date')
    streak = ud.get('daily_bonus_streak', 0)
    if last == today_s:
        await message.answer("Уже получили бонус сегодня. Приходи завтра!")
        await save_data_async(data)
        return
    if last:
        prev = date.fromisoformat(last)
        if (date.today() - prev).days == 1:
            streak = streak + 1
        else:
            streak = 1
    else:
        streak = 1
    bonus = int(DAILY_BONUS_AMOUNT * (DAILY_BONUS_STREAK_MULTIPLIER ** (streak - 1)))
    ud['currency'] = ud.get('currency', 0) + bonus
    ud['last_daily_bonus_date'] = today_s
    ud['daily_bonus_streak'] = streak
    ach = await check_and_grant_achievements(ud, bot, message.chat.id)
    await save_data_async(data)
    res = f"🎁 Ежедневный бонус: +{bonus} {DEFAULT_CURRENCY_NAME}!\n🔥 Ваш стрик: {streak} дн."
    if ach:
        res += "\n" + "\n".join(ach)
    await message.answer(res)

async def cmd_shop(message: types.Message, bot: Bot, **kwargs):
    data = load_data()
    ud = get_user_data(message.from_user.id, data, message.from_user.username or message.from_user.first_name)
    bal = ud.get('currency', 0)
    txt = f"🛍️ <b>Магазин {BOT_NAME}</b>\nБаланс: {bal} {DEFAULT_CURRENCY_NAME}\n\n"
    kb_rows = []
    for item_id, item in shop_items.items():
        txt += f"🔹 <b>{item['name']}</b> - {item['price']} {DEFAULT_CURRENCY_NAME}\n   <i>{item['description']}</i>\n\n"
        kb_rows.append([InlineKeyboardButton(text=f"Купить {item['name']} ({item['price']})", callback_data=f"shop_buy:{item_id}")])
    markup = InlineKeyboardMarkup(inline_keyboard=kb_rows) if kb_rows else None
    await save_data_async(data)
    await message.answer(txt, parse_mode="HTML", reply_markup=markup)

async def cb_shop_buy(query: types.CallbackQuery, bot: Bot, **kwargs):
    await query.answer()
    data = load_data()
    user_id = query.from_user.id
    ud = get_user_data(user_id, data, query.from_user.username or query.from_user.first_name)
    payload = query.data.split(":", 1)
    if len(payload) != 2:
        await query.message.edit_text("Ошибка формата.")
        return
    item_id = payload[1]
    if item_id not in shop_items:
        await query.message.edit_text("Товар не найден.")
        await save_data_async(data)
        return
    item = shop_items[item_id]
    price = item['price']
    if ud.get('currency', 0) < price:
        await query.message.edit_text(f"Мало средств! Нужно {price}, у вас {ud.get('currency', 0)}.")
        await save_data_async(data)
        return
    ud['currency'] -= price
    effect = item['effect']
    app_msg = f"✅ Куплено «{item['name']}» за {price} {DEFAULT_CURRENCY_NAME}.\n"
    if effect['type'] == 'event_modifier' and effect.get('target') == 'next_video_popularity':
        ud['active_event'] = {
            "type": "event_modifier",
            "modifier": effect['modifier'],
            "target": "next_video_popularity",
            "message": f"Использован «{item['name']}» ({effect['modifier']:+})"
        }
        app_msg += "Эффект применён к следующему видео."
    elif effect['type'] == 'cooldown_reset':
        ud['last_used_timestamp'] = 0.0
        app_msg += "Кулдаун сброшен!"
        t = _inmemory_tasks.get(user_id)
        if t and not t.done():
            t.cancel()
            _inmemory_tasks.pop(user_id, None)
        ud['cooldown_notification_task'] = None
    await check_and_grant_achievements(ud, bot, query.message.chat.id)
    await save_data_async(data)
    await query.message.edit_text(app_msg)

async def cmd_help(message: types.Message, bot: Bot, **kwargs):
    text = (
        f"🌟 <b>{BOT_NAME}!</b>\n\n"
        "Публикуй видео, копи валюту и прокачивайся!\n\n"
        "<b>Команды</b>:\n"
        "🎬 /addvideo <название>\n"
        "🏆 /leaderboard  /leaderboardpic\n"
        "👤 /myprofile\n"
        "🛍️ /shop\n"
        "🎁 /daily\n"
        "🏅 /achievements\n"
        "🔍 /checksub - проверить подписку на канал\n"
        "❓ /help\n\n"
        f"Механика: публикация раз в {COOLDOWN_HOURS:.1f} ч. Популярность зависит от заголовка, слов-ключей и удачи. Есть события и магазин.\n\n"
        "<b>Админ команды:</b>\n"
        "🔧 /disablesub - отключить проверку подписки\n"
        "🔧 /enablesub <канал> - включить проверку подписки\n"
        "🔧 /botstats - статистика бота"
    )
    await message.answer(text, parse_mode="HTML")

async def cmd_checksub(message: types.Message, bot: Bot, **kwargs):
    if not CHANNEL_ID:
        await message.answer("❌ CHANNEL_ID не настроен в .env файле")
        return
    
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    
    await message.answer(f"🔍 Проверяю подписку пользователя {username} (ID: {user_id}) на канал {CHANNEL_ID}...")
    
    try:
        chat_info = await bot.get_chat(CHANNEL_ID)
        await message.answer(f"📢 Информация о канале:\nНазвание: {chat_info.title}\nТип: {chat_info.type}\nID: {chat_info.id}")
        
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        status_text = str(member.status)
        
        if member.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR):
            await message.answer(f"✅ Вы подписаны на канал {CHANNEL_ID}!\nСтатус: {status_text}")
        else:
            await message.answer(f"❌ Вы НЕ подписаны на канал {CHANNEL_ID}\nСтатус: {status_text}")
            
    except Exception as e:
        if "OWNER" in str(e):
            await message.answer(f"✅ Вы подписаны на канал {CHANNEL_ID}!\nСтатус: CREATOR (владелец канала)")
        else:
            await message.answer(f"❌ Ошибка при проверке подписки: {e}")
        logger.error(f"Subscription check test failed: {e}")

async def cmd_disable_sub_check(message: types.Message, bot: Bot, **kwargs):
    if message.from_user.id != CREATOR_ID:
        await message.answer("⛔ Только создатель бота может отключить проверку подписки")
        return
    
    global CHANNEL_ID
    old_channel = CHANNEL_ID
    CHANNEL_ID = None
    
    await message.answer(f"✅ Проверка подписки отключена!\nБыло: {old_channel}\nТеперь: отключено")
    logger.info(f"Subscription check disabled by admin {message.from_user.id}. Was: {old_channel}")

async def cmd_enable_sub_check(message: types.Message, bot: Bot, **kwargs):
    if message.from_user.id != CREATOR_ID:
        await message.answer("⛔ Только создатель бота может включить проверку подписки")
        return
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Укажите ID канала: /enablesub @channel_name или -100xxxxxxxxxx")
        return
    
    new_channel = args[1].strip()
    global CHANNEL_ID
    old_channel = CHANNEL_ID
    CHANNEL_ID = new_channel
    
    await message.answer(f"✅ Проверка подписки включена!\nБыло: {old_channel}\nТеперь: {new_channel}")
    logger.info(f"Subscription check enabled by admin {message.from_user.id}. Channel: {new_channel}")

async def admin_check_and_get(message: types.Message) -> Optional[str]:
    if message.from_user.id != CREATOR_ID:
        await message.answer("⛔ Только для админа.")
        return None
    return "ok"

async def admin_add_currency(message: types.Message, bot: Bot, **kwargs):
    ok = await admin_check_and_get(message)
    if not ok: return
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("Исп: /CHEATaddcoins <id/@usr> <кол-во>")
        return
    target = parts[1]
    try:
        amount = int(parts[2])
    except:
        await message.answer("кол-во должно быть числом")
        return
    data = load_data()
    found = None
    if target.startswith('@'):
        uname = target[1:].lower()
        for uid, info in data.items():
            if (info.get('username') or '').lstrip('@').lower() == uname:
                found = uid
                break
    else:
        try:
            uid = int(target)
            if uid in data:
                found = uid
        except:
            pass
    if not found:
        await message.answer("Юзер не найден.")
        return
    data[found]['currency'] = max(0, data[found].get('currency', 0) + amount)
    await save_data_async(data)
    await message.answer(f"Баланс юзера обновлён: {data[found]['currency']} {DEFAULT_CURRENCY_NAME}")

async def admin_add_subs(message: types.Message, bot: Bot, **kwargs):
    ok = await admin_check_and_get(message)
    if not ok: return
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("Исп: /CHEATaddsub <id/@usr> <кол-во>")
        return
    target = parts[1]
    try:
        amount = int(parts[2])
    except:
        await message.answer("кол-во должно быть числом")
        return
    data = load_data()
    found = None
    if target.startswith('@'):
        uname = target[1:].lower()
        for uid, info in data.items():
            if (info.get('username') or '').lstrip('@').lower() == uname:
                found = uid
                break
    else:
        try:
            uid = int(target)
            if uid in data:
                found = uid
        except:
            pass
    if not found:
        await message.answer("Юзер не найден.")
        return
    data[found]['subscribers'] = max(0, data[found].get('subscribers', 0) + amount)
    await save_data_async(data)
    await message.answer(f"Пдп юзера обновлены: {data[found]['subscribers']}")

async def admin_delete_db(message: types.Message, bot: Bot, **kwargs):
    ok = await admin_check_and_get(message)
    if not ok: return
    if os.path.exists(DATABASE_FILE):
        try:
            os.remove(DATABASE_FILE)
            await message.answer(f"{DATABASE_FILE} удалён.")
        except Exception as e:
            await message.answer(f"Ошибка: {e}")
    else:
        await message.answer("Файл БД не найден.")

async def admin_stats(message: types.Message, bot: Bot, **kwargs):
    ok = await admin_check_and_get(message)
    if not ok: return
    data = load_data()
    tu = len(data)
    ts = sum(i.get('subscribers', 0) for i in data.values())
    tv = sum(i.get('video_count', 0) for i in data.values())
    tc = sum(i.get('currency', 0) for i in data.values())
    txt = (f"📊 <b>Стата {BOT_NAME}:</b>\n\n"
           f"👥 Юзеров: {tu}\n▶️ Видео: {tv}\n📈 Сумма пдп: {ts}\n💰 Сумма валюты: {tc} {DEFAULT_CURRENCY_NAME}")
    await message.answer(txt, parse_mode="HTML")

async def main():
    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN is missing. Set it in .env")
        return
    if not os.path.exists(DATABASE_FILE):
        with open(DATABASE_FILE, 'w', encoding='utf-8') as f:
            json.dump({}, f)
        logger.info("Created DB file.")
    if not os.path.exists(KEYWORDS_FILE):
        with open(KEYWORDS_FILE, 'w', encoding='utf-8') as f:
            f.write("популярное\nхайп\n")
        logger.info("Created keywords file.")

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    dp.message.register(cmd_start, Command(commands=["start"]))
    dp.message.register(cmd_help, Command(commands=["help", "info"]))
    dp.message.register(cmd_addvideo, Command(commands=["addvideo", "add", "video", "newvideo", "publishvideo", "publish"]))
    dp.message.register(cmd_leaderboard, Command(commands=["leaderboard", "lp"]))
    dp.message.register(cmd_leaderboardpic, Command(commands=["leaderboardpic", "lppic"]))
    dp.message.register(cmd_myprofile, Command(commands=["myprofile"]))
    dp.message.register(cmd_achievements, Command(commands=["achievements"]))
    dp.message.register(cmd_daily, Command(commands=["daily"]))
    dp.message.register(cmd_shop, Command(commands=["shop"]))
    dp.message.register(cmd_checksub, Command(commands=["checksub"]))
    dp.message.register(cmd_disable_sub_check, Command(commands=["disablesub"]))
    dp.message.register(cmd_enable_sub_check, Command(commands=["enablesub"]))

    dp.message.register(admin_add_currency, Command(commands=["CHEATaddcoins"]))
    dp.message.register(admin_add_subs, Command(commands=["CHEATaddsub"]))
    dp.message.register(admin_delete_db, Command(commands=["CHEATDeleteDatabase"]))
    dp.message.register(admin_stats, Command(commands=["botstats"]))

    dp.callback_query.register(cb_shop_buy, lambda c: c.data and c.data.startswith("shop_buy:"))

    logger.info("%s is starting...", BOT_NAME)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Stopped by user")
