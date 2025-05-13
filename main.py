import asyncio
import logging
import os
import random
from datetime import datetime, timedelta, date
from typing import Dict, Any, Tuple, Optional, List
import json

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from telegram import (BotCommand, ChatMember, ReplyKeyboardMarkup, Update,
                      KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup, BotCommandScopeChat)
from telegram.ext import (Application, ApplicationBuilder, CallbackContext,
                          CommandHandler, ContextTypes, JobQueue, CallbackQueryHandler, MessageHandler, filters)
from telegram.constants import ParseMode

load_dotenv()

# --- Загрузка Настроек из .env ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
CREATOR_ID = int(os.getenv("CREATOR_ID", 0)) # Важно: убедиться, что CREATOR_ID есть и он число
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
LOG_LEVEL = getattr(logging, LOG_LEVEL_STR, logging.INFO) # Преобразуем строку в уровень логирования

# --- Настройка Логирования ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=LOG_LEVEL
)
logger = logging.getLogger(__name__)

# --- Структуры Данных Игры (Оставляем в коде для удобства сложной структуры) ---
# Если бы они были в .env, их нужно было бы парсить из JSON строки
# achievements_json_str = os.getenv("ACHIEVEMENTS_JSON")
# shop_items_json_str = os.getenv("SHOP_ITEMS_JSON")
#
# try:
#     achievements_definition = json.loads(achievements_json_str) if achievements_json_str else {}
# except json.JSONDecodeError:
#     logger.error("Ошибка парсинга ACHIEVEMENTS_JSON из .env. Используются значения по умолчанию.")
#     achievements_definition = { ... значения по умолчанию ... }
#
# try:
#     shop_items = json.loads(shop_items_json_str) if shop_items_json_str else {}
# except json.JSONDecodeError:
#     logger.error("Ошибка парсинга SHOP_ITEMS_JSON из .env. Используются значения по умолчанию.")
#     shop_items = { ... значения по умолчанию ... }


achievements_definition: Dict[str, Dict[str, Any]] = {
    "newbie_blogger": {"name": "🌱 Новичок Блогер", "condition_videos": 1, "reward_coins": 5},
    "rising_star": {"name": "🌟 Восходящая Звезда", "condition_videos": 5, "reward_coins": 25},
    "serial_publisher": {"name": "🎬 Серийный Публицист", "condition_videos": 10, "reward_coins": 50},
    "first_hundred": {"name": "💯 Первая Сотня", "condition_subs": 100, "reward_coins": 100},
    "popular_choice": {"name": "🔥 Народный Любимец", "condition_subs": 500, "reward_coins": 250},
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

# --- Остальной код без изменений ---
# ... (весь предыдущий код main.py, начиная с функций работы с данными) ...
# (get_user_data, is_subscribed, load_keywords, evaluate_video_popularity, и т.д.)
# ... (все обработчики команд) ...
# ... (main, post_init) ...

# Важно убедиться, что все константы, которые раньше были жестко закодированы,
# теперь используются из переменных, загруженных из .env. Например:
# Вместо `COOLDOWN_HOURS = 12` в коде, он уже загружен вверху.

# В функциях, где использовались эти константы, ничего менять не нужно,
# так как они уже ссылаются на глобальные переменные, которые теперь
# инициализируются из .env.

# Пример использования LOG_LEVEL уже есть в logging.basicConfig.

# Убедитесь, что если CREATOR_ID не указан или некорректен в .env, 
# это не вызывает падения, а обрабатывается (например, int(os.getenv("CREATOR_ID", 0)))
# где 0 - это ID, который маловероятно будет реальным, и админские команды не сработают.

# Проверьте, что `float` и `int` используются для преобразования строковых значений из .env.
# Это уже сделано в блоке загрузки настроек.

# ... (Весь остальной код из предыдущего ответа, который был после этого блока)
# --- Функции Работы с Данными (JSON) ---
def load_data() -> Dict[int, Dict[str, Any]]:
    if not os.path.exists(DATABASE_FILE):
        return {}
    try:
        with open(DATABASE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return {int(k): v for k, v in data.items()}
    except (json.JSONDecodeError, FileNotFoundError) as e:
        logger.error(f"Ошибка загрузки данных из {DATABASE_FILE} (JSON): {e}")
        return {}

def save_data(data: Dict[int, Dict[str, Any]]):
    try:
        with open(DATABASE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Ошибка сохранения данных в {DATABASE_FILE} (JSON): {e}")

def get_user_data(user_id: int, data: Dict[int, Dict[str, Any]], username: str) -> Dict[str, Any]:
    if user_id not in data:
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
            'cooldown_notification_job_id': None,
        }
    if data[user_id].get('username') != username:
        data[user_id]['username'] = username
    return data[user_id]

async def is_subscribed(user_id: int, bot) -> bool:
    if not CHANNEL_ID: return True
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER]
    except Exception as e:
        logger.error(f"Ошибка проверки подписки для {user_id} на {CHANNEL_ID}: {e}")
        return False

def load_keywords(filename: str = KEYWORDS_FILE) -> list:
    if not os.path.exists(filename):
        with open(filename, 'w', encoding='utf-8') as f:
            f.write("популярное\nхайп\n")
        return ["популярное", "хайп"]
    try:
        with open(filename, 'r', encoding='utf-8') as file:
            return [line.strip().lower() for line in file if line.strip() and not line.startswith('#')]
    except Exception as e:
        logger.error(f"Ошибка загрузки ключевых слов {filename}: {e}")
        return []

def evaluate_video_popularity(video_title: str, base_popularity_modifier: int = 0) -> int:
    keywords = load_keywords()
    title_lower = video_title.lower()
    keyword_bonus = sum(KEYWORD_BONUS_POINTS for keyword in keywords if keyword in title_lower)
    random_score = random.randint(POPULARITY_RANDOM_MIN, POPULARITY_RANDOM_MAX)
    return keyword_bonus + random_score + base_popularity_modifier

async def subscription_check_middleware(update: Update, context: CallbackContext, command_handler_coro, require_subscription:bool = True):
    if not CHANNEL_ID or not require_subscription:
        await command_handler_coro(update, context)
        return

    user_id = update.effective_user.id
    if not await is_subscribed(user_id, context.bot):
        channel_link = CHANNEL_ID
        channel_name_display = CHANNEL_ID
        if not CHANNEL_ID.startswith('@'):
            channel_link = f"https://t.me/c/{CHANNEL_ID.replace('-100', '')}"
            try:
                chat = await context.bot.get_chat(CHANNEL_ID)
                channel_name_display = chat.title or CHANNEL_ID
            except Exception: pass
        
        await update.message.reply_text(
            f"Подпишитесь на {channel_name_display} ({channel_link}) для этой команды.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Перейти к каналу", url=channel_link)]])
        )
        return
    await command_handler_coro(update, context)

def get_random_event(user_subscribers: int) -> Optional[Dict[str, Any]]:
    roll = random.randint(1, 100)
    if user_subscribers < 10 and random.randint(1,3) != 1 : return None

    if 75 <= roll <= 80:
        bonus = random.randint(3, 7)
        return {"type": "event_modifier", "modifier": bonus, "target": "next_video_popularity",
                "message": f"🎉 Внезапный хайп! +{bonus} к популярности следующего видео!"}
    elif 81 <= roll <= 83 and user_subscribers > 20:
        malus = random.randint(2, 5)
        return {"type": "event_modifier", "modifier": -malus, "target": "next_video_popularity",
                "message": f"📉 Тех.неполадки на {BOT_NAME}! -{malus} к популярности следующего видео."}
    return None

async def check_and_grant_achievements(user_data: Dict[str, Any], update: Update) -> List[str]:
    newly_unlocked_messages = []
    for ach_id, ach_def in achievements_definition.items():
        if ach_id not in user_data['achievements_unlocked']:
            unlocked = False
            if "condition_videos" in ach_def and user_data.get('video_count', 0) >= ach_def["condition_videos"]:
                unlocked = True
            if "condition_subs" in ach_def and user_data.get('subscribers', 0) >= ach_def["condition_subs"]:
                unlocked = True
            
            if unlocked:
                user_data['achievements_unlocked'].append(ach_id)
                reward_coins = ach_def.get("reward_coins", 0)
                user_data['currency'] = user_data.get('currency', 0) + reward_coins
                message = f"🏆 Новое достижение: **{ach_def['name']}**! (+{reward_coins} {DEFAULT_CURRENCY_NAME})"
                newly_unlocked_messages.append(message)
                if update.message: 
                    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
                logger.info(f"Пользователь {user_data['username']} получил достижение {ach_id}")
    return newly_unlocked_messages


async def cooldown_notification_callback(context: CallbackContext):
    job = context.job
    user_id_from_job = job.user_id # Предполагается, что это user_id, а не chat_id
    chat_id_from_job = job.chat_id

    try:
        data = load_data()
        user_data = data.get(user_id_from_job) # Используем user_id
        
        if user_data and user_data.get('cooldown_notification_job_id') == job.name:
            last_used_dt = datetime.fromtimestamp(user_data.get('last_used_timestamp', 0.0))
            next_video_time = last_used_dt + timedelta(hours=COOLDOWN_HOURS)

            if datetime.now() >= next_video_time:
                await context.bot.send_message(chat_id=chat_id_from_job, 
                                               text=f"⏰ Ваш кулдаун в {BOT_NAME} завершен! /addvideo")
                user_data['cooldown_notification_job_id'] = None
                save_data(data)
            else:
                logger.info(f"Cooldown job {job.name} для {user_id_from_job} преждевременный/сброшен.")
        else:
            logger.info(f"Cooldown job {job.name} для {user_id_from_job} не найден/устарел.")
    except Exception as e:
        logger.error(f"Ошибка в cooldown_notification_callback для {user_id_from_job}: {e}")

def schedule_cooldown_notification(user_id: int, chat_id: int, cooldown_end_time: datetime, context: CallbackContext, user_data: Dict[str, Any]):
    if not hasattr(context, 'job_queue') or not context.job_queue:
        logger.warning("JobQueue не доступен, уведомление не запланировано.")
        return

    if user_data.get('cooldown_notification_job_id'):
        current_jobs = context.job_queue.get_jobs_by_name(user_data['cooldown_notification_job_id'])
        for job in current_jobs: job.schedule_removal()
        user_data['cooldown_notification_job_id'] = None
    
    delay = (cooldown_end_time - datetime.now()).total_seconds()
    if delay > 0:
        job_name = f"cooldown_notify_{user_id}_{int(cooldown_end_time.timestamp())}"
        context.job_queue.run_once(cooldown_notification_callback, 
                                   when=delay, 
                                   chat_id=chat_id, 
                                   user_id=user_id,
                                   name=job_name)
        user_data['cooldown_notification_job_id'] = job_name
        logger.info(f"Запланировано уведомление для {user_id} на {cooldown_end_time} (job: {job_name})")

# --- ОБРАБОТЧИКИ КОМАНД --- (код без изменений, т.к. он уже использует глобальные константы)

async def start_command_internal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"User {user.name} (ID: {user.id}) /start")
    data = load_data()
    user_data = get_user_data(user.id, data, user.name)
    
    if user_data.get('video_count',0) == 0 : 
       await check_and_grant_achievements(user_data, update)
    save_data(data) 

    keyboard_layout = [
        [KeyboardButton(f"/addvideo Название Видео")],
        [KeyboardButton("/myprofile"), KeyboardButton("/shop")],
        [KeyboardButton("/leaderboard"), KeyboardButton("/achievements")],
        [KeyboardButton("/daily"), KeyboardButton("/help")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard_layout, resize_keyboard=True)
    await update.message.reply_text(
        f"🚀 Привет, {user.first_name}! Ты в игре {BOT_NAME}!\n"
        "Используй /help или кнопки ниже.",
        reply_markup=reply_markup
    )

async def start_command_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await subscription_check_middleware(update, context, start_command_internal, require_subscription=True)

async def add_video_command_internal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not context.args:
        await update.message.reply_text("Укажи название видео: `/addvideo Мое Супер Видео`", parse_mode=ParseMode.MARKDOWN)
        return

    video_title = ' '.join(context.args)
    data = load_data()
    user_data = get_user_data(user.id, data, user.name)

    last_used_dt = datetime.fromtimestamp(user_data.get('last_used_timestamp', 0.0))
    next_video_time = last_used_dt + timedelta(hours=COOLDOWN_HOURS)
    
    if datetime.now() < next_video_time:
        remaining_time = next_video_time - datetime.now()
        hours, rem_secs = divmod(remaining_time.seconds, 3600)
        minutes, _ = divmod(rem_secs, 60)
        await update.message.reply_text(f"⏳ Кулдаун! Следующее видео через {hours} ч {minutes} мин.")
        return

    event_modifier = 0
    event_applied_message_list = []
    active_event_data = user_data.get('active_event')
    if active_event_data:
        event_applied_message_list.append(f"✨ *Активное событие*: {active_event_data['message']}")
        if active_event_data.get('target') == 'next_video_popularity' and 'modifier' in active_event_data:
            event_modifier = active_event_data['modifier']
        user_data['active_event'] = None

    popularity_score = evaluate_video_popularity(video_title, base_popularity_modifier=event_modifier)
    subscribers_change = popularity_score
    bonus_subscribers = 0
    
    message_parts = [f"🎬 {user_data['username']}, видео \"{video_title}\" опубликовано!"]
    if event_applied_message_list: message_parts.extend(event_applied_message_list)

    if popularity_score > POPULARITY_THRESHOLD_BONUS:
        bonus_subscribers = random.randint(BONUS_SUBSCRIBERS_MIN, BONUS_SUBSCRIBERS_MAX)
        subscribers_change += bonus_subscribers
        message_parts.append(f"🌟 Супер! +{bonus_subscribers} бонусных пдп.")
    elif popularity_score < NEGATIVE_POPULARITY_THRESHOLD: message_parts.append(f"📉 Ох, не зашло...")
    elif popularity_score < 0: message_parts.append(f"😕 Упс, тема не особо популярна.")
    else: message_parts.append(f"👍 Неплохо!")
    
    user_data['subscribers'] = max(0, user_data.get('subscribers',0) + subscribers_change)
    user_data['last_used_timestamp'] = datetime.now().timestamp()
    user_data['video_count'] = user_data.get('video_count', 0) + 1
    user_data['total_subs_from_videos'] = user_data.get('total_subs_from_videos', 0) + subscribers_change
    
    if subscribers_change > 0: message_parts.append(f"📈 +{subscribers_change} подписчиков.")
    elif subscribers_change < 0: message_parts.append(f"📉 {subscribers_change} подписчиков.")
    else: message_parts.append(f"🤷 Подписчики не изменились.")
    message_parts.append(f"Итого: {user_data['subscribers']} пдп. (Видео: {user_data['video_count']})")

    if update.effective_chat:
        cooldown_end_time_calc = datetime.fromtimestamp(user_data['last_used_timestamp']) + timedelta(hours=COOLDOWN_HOURS)
        schedule_cooldown_notification(user.id, update.effective_chat.id, cooldown_end_time_calc, context, user_data)

    new_event_data = get_random_event(user_data.get('subscribers',0))
    if new_event_data:
        user_data['active_event'] = new_event_data
        message_parts.append(f"\n🔔 *Событие!* {new_event_data['message']}")

    achievement_msgs_list = await check_and_grant_achievements(user_data, update)
    if achievement_msgs_list : message_parts.extend(achievement_msgs_list)

    save_data(data)
    await update.message.reply_text("\n".join(message_parts), parse_mode=ParseMode.MARKDOWN)
    logger.info(f"Видео '{video_title}' от {user.name}. Изм: {subscribers_change}. ПДП: {user_data['subscribers']}")

async def add_video_command_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await subscription_check_middleware(update, context, add_video_command_internal)

async def leaderboard_command_internal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    if not data:
        await update.message.reply_text(f"🏆 В {BOT_NAME} пока пусто... Будь первым!")
        return

    sorted_users = sorted(data.values(), key=lambda u: u.get('subscribers', 0), reverse=True)
    leaderboard_message = f"🏆 <b>Топ {BOT_NAME}еров:</b>\n\n"
    max_display = 15
    
    displayed_count = 0
    for info in sorted_users: # Итерация по значениям (словарям пользователей)
        if info.get('subscribers',0) <=0 and displayed_count >= 5 : continue 
        leaderboard_message += (f"{displayed_count + 1}. {info.get('username','N/A')} - {info.get('subscribers', 0)} пдп. "
                                f"(видео: {info.get('video_count',0)})\n")
        displayed_count += 1
        if displayed_count >= max_display: break

    if displayed_count == 0:
         await update.message.reply_text("🏆 Пока нет пользователей с подписчиками в топе.")
         return
         
    await update.message.reply_text(leaderboard_message, parse_mode=ParseMode.HTML)

async def leaderboard_command_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await subscription_check_middleware(update, context, leaderboard_command_internal, require_subscription=False)

async def leaderboard_pic_command_internal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data_dict = load_data()
    if not data_dict:
        if update.message: await update.message.reply_text("📊 Данных для графика пока нет.")
        return

    filtered_data_for_df = {
        uid: uinfo for uid, uinfo in data_dict.items() 
        if 'username' in uinfo and 'subscribers' in uinfo
    }
    if not filtered_data_for_df:
        if update.message: await update.message.reply_text("📊 Недостаточно полных данных для графика.")
        return

    df = pd.DataFrame.from_dict(filtered_data_for_df, orient='index')
    
    if 'subscribers' not in df.columns or df['subscribers'].isnull().all() or not pd.api.types.is_numeric_dtype(df['subscribers']):
        if update.message: await update.message.reply_text("📊 Недостаточно данных о подписчиках для графика.")
        return

    valid_data = df[df['subscribers'] > 0].sort_values(by='subscribers', ascending=False)
    if valid_data.empty:
        if update.message: await update.message.reply_text("📊 Нет пользователей с подписчиками для графика.")
        return

    top_data = valid_data.head(15)
    usernames = top_data['username'].values
    subscribers_counts = top_data['subscribers'].values

    fig, ax = plt.subplots(figsize=(10, 7), facecolor='white')
    wedges, texts, autotexts = ax.pie(
        subscribers_counts, autopct=lambda p: f'{p:.1f}%' if p > 3 else '',
        startangle=140, colors=plt.cm.Paired(np.linspace(0, 1, len(subscribers_counts)))
    )
    plt.setp(autotexts, size=8, weight="bold", color="white")
    ax.set_title(f"🏆 Топ {BOT_NAME}еров (Диаграмма)", fontsize=16, pad=20)
    ax.legend(wedges, [f"{name} ({count})" for name, count in zip(usernames, subscribers_counts)],
              title="Топ пользователей:", loc="center left", bbox_to_anchor=(1, 0, 0.5, 1), fontsize=9)
    plt.tight_layout(rect=[0, 0, 0.75, 1])

    try:
        plt.savefig(LEADERBOARD_IMAGE_FILE, format='png', dpi=150) # Используем переменную из .env
        with open(LEADERBOARD_IMAGE_FILE, 'rb') as photo_file:
            if update.effective_chat:
                 await context.bot.send_photo(chat_id=update.effective_chat.id, photo=photo_file)
    except Exception as e:
        logger.error(f"Ошибка отправки изображения топа: {e}")
        if update.message: await update.message.reply_text("Не удалось сгенерировать изображение топа.")
    finally:
        if os.path.exists(LEADERBOARD_IMAGE_FILE): os.remove(LEADERBOARD_IMAGE_FILE)
        plt.close(fig)

async def leaderboard_pic_command_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await subscription_check_middleware(update, context, leaderboard_pic_command_internal, require_subscription=False)

async def my_profile_command_internal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = load_data()
    user_data = get_user_data(user.id, data, user.name)

    username_display = user_data.get('username', user.first_name)
    subscribers = user_data.get('subscribers', 0)
    video_count = user_data.get('video_count', 0)
    currency = user_data.get('currency', 0)
    last_used_ts = user_data.get('last_used_timestamp', 0)
    total_subs_videos = user_data.get('total_subs_from_videos',0)
    avg_subs_per_video = (total_subs_videos / video_count) if video_count > 0 else 0
    
    profile_message = [f"👤 <b>Твой профиль, {username_display}:</b>\n"]
    profile_message.append(f"👥 Подписчики: {subscribers}")
    profile_message.append(f"💰 {DEFAULT_CURRENCY_NAME}: {currency}")
    profile_message.append(f"📹 Опубликовано видео: {video_count}")
    if video_count > 0 :
        profile_message.append(f"📈 Сред. подписчиков за видео: {avg_subs_per_video:.2f}")

    if last_used_ts == 0:
        can_post_str = f"Публикуй первое видео: /addvideo <название>!"
    else:
        last_used_dt = datetime.fromtimestamp(last_used_ts)
        profile_message.append(f"🕓 Посл. видео: {last_used_dt.strftime('%Y-%m-%d %H:%M')}")
        next_video_time = last_used_dt + timedelta(hours=COOLDOWN_HOURS)
        if datetime.now() < next_video_time:
            remaining_time = next_video_time - datetime.now()
            hours, rem_secs = divmod(remaining_time.seconds, 3600)
            minutes, _ = divmod(rem_secs, 60)
            can_post_str = f"Сл. видео через: {hours} ч {minutes} мин."
        else:
            can_post_str = "Можешь публиковать новое видео!"
    profile_message.append(f"⏳ {can_post_str}")

    active_event_data = user_data.get('active_event')
    if active_event_data:
        profile_message.append(f"\n✨ <b>Активное событие:</b> {active_event_data['message']}")
    
    save_data(data) 
    await update.message.reply_text("\n".join(profile_message), parse_mode=ParseMode.HTML)

async def my_profile_command_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await subscription_check_middleware(update, context, my_profile_command_internal, require_subscription=False)

async def achievements_command_internal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = load_data()
    user_data = get_user_data(user.id, data, user.name)

    unlocked_ids = user_data.get('achievements_unlocked', [])
    if not unlocked_ids:
        await update.message.reply_text("Вы пока не открыли ни одного достижения.")
        save_data(data) # Сохраняем на случай создания нового пользователя
        return

    message = "🏆 <b>Ваши достижения:</b>\n\n"
    for ach_id in unlocked_ids:
        if ach_id in achievements_definition:
            message += f"- {achievements_definition[ach_id]['name']}\n"
    
    message += "\n🔍 <i>Неразблокированные (некоторые):</i>\n"
    shown_pending = 0
    for ach_id, ach_def in achievements_definition.items():
        if ach_id not in unlocked_ids:
            message += f"- ❓ {ach_def['name']} (Скрыто)\n"
            shown_pending += 1
            if shown_pending >= 3: break
    
    save_data(data)
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)

async def achievements_command_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await subscription_check_middleware(update, context, achievements_command_internal, require_subscription=False)

async def daily_bonus_command_internal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = load_data()
    user_data = get_user_data(user.id, data, user.name)
    today_str = date.today().isoformat()
    last_bonus_date_str = user_data.get('last_daily_bonus_date')
    
    if last_bonus_date_str == today_str:
        await update.message.reply_text(f"Вы уже получили бонус сегодня. Возвращайтесь завтра!")
        save_data(data) # Сохраняем на случай нового пользователя
        return

    current_streak = user_data.get('daily_bonus_streak', 0)
    if last_bonus_date_str:
        last_bonus_date = date.fromisoformat(last_bonus_date_str)
        if (date.today() - last_bonus_date).days == 1: current_streak += 1
        else: current_streak = 1 
    else: current_streak = 1
    
    bonus_calc = int(DAILY_BONUS_AMOUNT * (DAILY_BONUS_STREAK_MULTIPLIER ** (current_streak -1)))

    user_data['currency'] = user_data.get('currency', 0) + bonus_calc
    user_data['last_daily_bonus_date'] = today_str
    user_data['daily_bonus_streak'] = current_streak
    
    achievement_msgs_list = await check_and_grant_achievements(user_data, update)
    save_data(data)

    message_text = (f"🎁 Ежедневный бонус: +{bonus_calc} {DEFAULT_CURRENCY_NAME}!\n"
                    f"🔥 Ваш стрик: {current_streak} дней.")
    if achievement_msgs_list:
        message_text += "\n" + "\n".join(achievement_msgs_list).replace("<b>","*").replace("</b>","*")
    
    await update.message.reply_text(message_text, parse_mode=ParseMode.MARKDOWN)

async def daily_bonus_command_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await subscription_check_middleware(update, context, daily_bonus_command_internal)

async def shop_command_internal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = load_data()
    user_data = get_user_data(user.id, data, user.name)
    save_data(data) 

    currency_balance = user_data.get('currency', 0)
    message = f"🛍️ <b>Магазин {BOT_NAME}</b>\nВаш баланс: {currency_balance} {DEFAULT_CURRENCY_NAME}\n\n"
    
    buttons_list = []
    if not shop_items:
        message += "В магазине пока пусто."
    else:
        for item_id, item_def in shop_items.items():
            message += f"🔹 <b>{item_def['name']}</b> - {item_def['price']} {DEFAULT_CURRENCY_NAME}\n"
            message += f"   <i>{item_def['description']}</i>\n\n"
            buttons_list.append([InlineKeyboardButton(f"Купить \"{item_def['name'][:20]}...\" ({item_def['price']})", callback_data=f"shop_buy_{item_id}")])
    
    reply_markup = InlineKeyboardMarkup(buttons_list) if buttons_list else None
    await update.message.reply_text(message, parse_mode=ParseMode.HTML, reply_markup=reply_markup)

async def shop_command_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await subscription_check_middleware(update, context, shop_command_internal)

async def shop_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() 
    
    # query.data должен быть вида "shop_buy_itemid"
    parts = query.data.split('_')
    if len(parts) < 3 or parts[0] != "shop" or parts[1] != "buy":
        await query.edit_message_text("Ошибка: неверный формат callback_data.")
        return
    
    item_id = parts[2]

    user = query.effective_user
    data = load_data()
    user_data = get_user_data(user.id, data, user.name)

    if item_id not in shop_items:
        await query.edit_message_text("Ошибка: товар не найден.")
        save_data(data)
        return

    item_definition = shop_items[item_id]
    item_price = item_definition['price']
    user_currency_balance = user_data.get('currency', 0)

    if user_currency_balance < item_price:
        await query.edit_message_text(f"Недостаточно средств! Нужно {item_price} {DEFAULT_CURRENCY_NAME}, у вас {user_currency_balance}.")
        save_data(data)
        return
    
    user_data['currency'] -= item_price
    item_effect = item_definition['effect']
    applied_message = f"✅ Куплено \"{item_definition['name']}\" за {item_price} {DEFAULT_CURRENCY_NAME}.\n"

    if item_effect['type'] == 'event_modifier' and item_effect['target'] == 'next_video_popularity':
        user_data['active_event'] = {
            "type": "event_modifier",
            "modifier": item_effect['modifier'],
            "target": "next_video_popularity",
            "message": f"Использован \"{item_definition['name']}\" ({item_effect['modifier']:+})"
        }
        applied_message += f"Эффект будет применен к следующему видео."
    elif item_effect['type'] == 'cooldown_reset':
        user_data['last_used_timestamp'] = 0.0
        applied_message += f"Кулдаун сброшен!"
        if user_data.get('cooldown_notification_job_id') and context.job_queue:
            current_jobs = context.job_queue.get_jobs_by_name(user_data['cooldown_notification_job_id'])
            for job in current_jobs: job.schedule_removal()
            user_data['cooldown_notification_job_id'] = None

    await query.edit_message_text(applied_message)
    logger.info(f"User {user.name} bought {item_id}. Currency: {user_data['currency']}")
    await check_and_grant_achievements(user_data, update)
    save_data(data)

async def help_command_internal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        f"🌟 <b>Добро пожаловать в {BOT_NAME}!</b> 🌟\n\n"
        "Публикуй видео, набирай подписчиков, собирай {currency} и стань звездой!\n\n"
        "<b>Основные команды:</b>\n"
        "🎬 `/addvideo <название>`\n"
        "🏆 `/leaderboard`, `/leaderboardpic`\n"
        "👤 `/myprofile`\n"
        "🛍️ `/shop`\n"
        "🎁 `/daily`\n"
        "🏅 `/achievements`\n"
        "🆘 `/help`\n\n"
        "<b>Механика:</b>\n"
        "Публикация раз в {cooldown:.1f} ч. Популярность зависит от слов и удачи. " # :.1f для вывода одного знака после запятой
        "Иногда бывают события! Копи {currency}."
    ).format(cooldown=COOLDOWN_HOURS, bot_name=BOT_NAME, currency=DEFAULT_CURRENCY_NAME)
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)

async def help_command_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await subscription_check_middleware(update, context, help_command_internal, require_subscription=False)

async def admin_check(update: Update) -> bool:
    if update.effective_user.id != CREATOR_ID:
        if update.message: await update.message.reply_text("⛔ Команда только для администратора.")
        return False
    return True

async def admin_add_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_check(update): return
    if len(context.args) < 2:
        await update.message.reply_text(f"Исп: `/CHEATaddcoins <user_id/@username> <количество>`")
        return
    target_identifier = context.args[0]
    try: amount_to_add = int(context.args[1])
    except ValueError: await update.message.reply_text("Количество должно быть числом."); return

    data = load_data()
    target_user_id_found: Optional[int] = None
    if target_identifier.startswith('@'):
        username_to_find_admin = target_identifier[1:].lower()
        for uid_admin, uinfo_admin in data.items():
            user_name_in_db = uinfo_admin.get('username','').lower()
            if user_name_in_db == username_to_find_admin or \
               (user_name_in_db.startswith('@') and user_name_in_db[1:] == username_to_find_admin):
                target_user_id_found = uid_admin
                break
    else:
        try: target_user_id_found = int(target_identifier)
        except ValueError: pass

    if target_user_id_found is None or target_user_id_found not in data:
        await update.message.reply_text(f"Пользователь {target_identifier} не найден."); return
    
    user_data_admin = data[target_user_id_found]
    user_data_admin['currency'] = user_data_admin.get('currency', 0) + amount_to_add
    user_data_admin['currency'] = max(0, user_data_admin['currency'])
    save_data(data)
    await update.message.reply_text(f"Пользователю {user_data_admin['username']} изменены {DEFAULT_CURRENCY_NAME} на {amount_to_add}. "
                                    f"Новый баланс: {user_data_admin['currency']}.")

async def admin_give_achievement(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_check(update): return
    if len(context.args) < 2:
        await update.message.reply_text("Исп: `/CHEATgiveach <user_id/@username> <achievement_id>`")
        return
    
    target_identifier = context.args[0]
    ach_id_to_give = context.args[1]

    if ach_id_to_give not in achievements_definition:
        await update.message.reply_text(f"Достижение '{ach_id_to_give}' не найдено."); return

    data = load_data()
    target_user_id_found_ach: Optional[int] = None
    # ... (Аналогичный поиск пользователя как в admin_add_currency)
    if target_identifier.startswith('@'):
        username_to_find_ach = target_identifier[1:].lower()
        for uid_ach, uinfo_ach in data.items():
            # ... (условие поиска)
            pass # Замените pass на реальную логику поиска как в admin_add_currency
    else:
        try: target_user_id_found_ach = int(target_identifier)
        except ValueError: pass
    
    if target_user_id_found_ach is None or target_user_id_found_ach not in data:
        await update.message.reply_text(f"Пользователь {target_identifier} не найден."); return
        
    user_data_ach = data[target_user_id_found_ach]
    if ach_id_to_give not in user_data_ach.get('achievements_unlocked', []):
        user_data_ach.setdefault('achievements_unlocked', []).append(ach_id_to_give)
        reward_coins_ach = achievements_definition[ach_id_to_give].get("reward_coins", 0)
        user_data_ach['currency'] = user_data_ach.get('currency', 0) + reward_coins_ach
        save_data(data)
        await update.message.reply_text(f"Пользователю {user_data_ach['username']} выдано {achievements_definition[ach_id_to_give]['name']} (+{reward_coins_ach} {DEFAULT_CURRENCY_NAME}).")
    else:
        await update.message.reply_text(f"У {user_data_ach['username']} уже есть это достижение.")

async def admin_cheat_add_subscribers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Этот код должен быть обновлен аналогично admin_add_currency для поиска пользователя
    if not await admin_check(update): return
    if len(context.args) < 2:
        await update.message.reply_text("Исп: `/CHEATaddsub <user_id/@username> <количество>`"); return
    # ... (обновленная логика) ...
    pass # Placeholder - реализуйте поиск пользователя как в admin_add_currency

async def admin_delete_database(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_check(update): return
    if os.path.exists(DATABASE_FILE):
        try:
            os.remove(DATABASE_FILE)
            await update.message.reply_text(f"Файл '{DATABASE_FILE}' удален. Будет создан заново.");
            logger.info(f"Admin {update.effective_user.name} deleted {DATABASE_FILE}")
        except Exception as e: await update.message.reply_text(f"Ошибка удаления: {e}")
    else: await update.message.reply_text(f"Файл '{DATABASE_FILE}' уже удален/не существует.")

async def admin_bot_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_check(update): return
    data = load_data()
    total_users = len(data)
    total_subscribers_sum = sum(info.get('subscribers', 0) for info in data.values())
    total_videos_sum = sum(info.get('video_count', 0) for info in data.values())
    total_currency_sum = sum(info.get('currency',0) for info in data.values())
            
    stats_text = (
        f"📊 <b>Статистика бота {BOT_NAME}:</b>\n\n"
        f"👥 Пользователей: {total_users}\n"
        f"▶️ Видео: {total_videos_sum}\n"
        f"📈 Сумма подписчиков: {total_subscribers_sum}\n"
        f"💰 Сумма валюты: {total_currency_sum} {DEFAULT_CURRENCY_NAME}\n"
    )
    await update.message.reply_text(stats_text, parse_mode=ParseMode.HTML)


async def post_init(application: Application) -> None:
    common_commands = [
        BotCommand("start", "🚀 Запуск"), BotCommand("addvideo", "🎬 Видео"),
        BotCommand("myprofile", "👤 Профиль"), BotCommand("shop", "🛍️ Магазин"),
        BotCommand("daily", "🎁 Бонус"), BotCommand("achievements", "🏅 Достижения"),
        BotCommand("leaderboard", "🏆 Топ"), BotCommand("leaderboardpic", "📊 Топ (пик)"),
        BotCommand("help", "❓ Помощь"),
    ]
    admin_commands_list = [
        BotCommand("CHEATaddsub", "💰 Адм: +/- подп."),
        BotCommand("CHEATaddcoins", f"🪙 Адм: +/- {DEFAULT_CURRENCY_NAME[:5]}."), # Сокращаем для отображения
        BotCommand("CHEATgiveach", "🎖️ Адм: Выдать ачивку"),
        BotCommand("CHEATDeleteDatabase", "🗑️ Адм: Стереть базу"),
        BotCommand("botstats", "📈 Адм: Статистика"),
    ]
    
    await application.bot.set_my_commands(common_commands)
    if CREATOR_ID:
        try:
            await application.bot.set_my_commands(common_commands + admin_commands_list, scope=BotCommandScopeChat(chat_id=CREATOR_ID))
            logger.info(f"Установлены общие и админские команды для ID {CREATOR_ID}.")
        except Exception as e:
            logger.error(f"Не удалось установить админ. команды: {e}. Установлены только общие.")
    else: logger.info("Установлены общие команды (CREATOR_ID не указан).")

    if not BOT_TOKEN: logger.critical("BOT_TOKEN не найден!")
    if CHANNEL_ID: logger.info(f"Проверка подписки на {CHANNEL_ID} активна.")
    else: logger.info("CHANNEL_ID не указан, проверка подписки отключена.")


def main() -> None:
    if not BOT_TOKEN:
        print("Ошибка: BOT_TOKEN не указан. Проверьте .env файл.")
        return

    application = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    
    if not application.job_queue: # Для v20+ job_queue должен быть по умолчанию. Для <v20 нужно его создать и передать.
        logger.warning("JobQueue не найден в application. Уведомления о кулдауне могут не работать корректно.")
        # Если используете старую версию PTB, то:
        # from telegram.ext import JobQueue
        # jq = JobQueue()
        # application = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).job_queue(jq).build()
        # jq.set_application(application) # Нужно для job.run_*(...) в новых версиях ptb-jobqueue
        # jq.start() # И запустить его


    command_handlers_list = [
        CommandHandler("start", start_command_wrapper), CommandHandler("help", help_command_wrapper),
        CommandHandler("myprofile", my_profile_command_wrapper),
        CommandHandler("leaderboard", leaderboard_command_wrapper),
        CommandHandler("leaderboardpic", leaderboard_pic_command_wrapper),
        CommandHandler("achievements", achievements_command_wrapper),
        CommandHandler("daily", daily_bonus_command_wrapper),
        CommandHandler("shop", shop_command_wrapper),
        CommandHandler("CHEATaddsub", admin_cheat_add_subscribers), # Нужно доработать поиск
        CommandHandler("CHEATaddcoins", admin_add_currency),
        CommandHandler("CHEATgiveach", admin_give_achievement), # Нужно доработать поиск
        CommandHandler("CHEATDeleteDatabase", admin_delete_database),
        CommandHandler("botstats", admin_bot_stats),
    ]
    application.add_handlers(command_handlers_list)
    application.add_handler(CallbackQueryHandler(shop_callback_handler, pattern=r"^shop_buy_"))
    
    add_video_aliases = ["addvideo", "video", "add", "newvideo", "publishvideo", "new", "publish"]
    for alias in add_video_aliases:
        application.add_handler(CommandHandler(alias, add_video_command_wrapper))
    
    logger.info(f"Бот {BOT_NAME} с LOG_LEVEL={LOG_LEVEL_STR} запускается...")
    application.run_polling()

if __name__ == '__main__':
    if not os.path.exists(DATABASE_FILE):
        with open(DATABASE_FILE, 'w', encoding='utf-8') as f: json.dump({}, f)
        logger.info(f"Создан файл базы данных: {DATABASE_FILE}")
    
    if not os.path.exists(KEYWORDS_FILE):
        with open(KEYWORDS_FILE, 'w', encoding='utf-8') as f: f.write("популярное\nхайп\n")
        logger.info(f"Создан файл ключевых слов: {KEYWORDS_FILE}")
    
    main()