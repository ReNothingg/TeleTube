import asyncio
import logging
import os
import random
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from telegram import (BotCommand, ChatMember, ReplyKeyboardMarkup, Update,
                      KeyboardButton)
from telegram.ext import (Application, ApplicationBuilder, CallbackContext,
                          CommandHandler, ContextTypes)
from telegram.constants import ParseMode

# --- КОНФИГУРАЦИЯ И КОНСТАНТЫ ---
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CREATOR_ID = int(os.getenv("CREATOR_ID", 0))
CHANNEL_ID = os.getenv("CHANNEL_ID")
BOT_NAME = os.getenv("BOT_NAME", "Мой Бот") # Имя бота по умолчанию

DATABASE_FILE = os.getenv("DATABASE_FILE", "database.txt")
KEYWORDS_FILE = os.getenv("KEYWORDS_FILE", "keywords.txt")
LEADERBOARD_IMAGE_FILE = "leaderboard_pic.png"

COOLDOWN_HOURS = 12
POPULARITY_THRESHOLD_BONUS = 7 # Порог для получения бонусных подписчиков
KEYWORD_BONUS_POINTS = 2
POPULARITY_RANDOM_MIN = -10
POPULARITY_RANDOM_MAX = 20
BONUS_SUBSCRIBERS_MIN = 1
BONUS_SUBSCRIBERS_MAX = 5
NEGATIVE_POPULARITY_THRESHOLD = -5 # Порог для срабатывания негативных событий

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Структура для хранения пользовательских данных
# user_id: {
#     'username': str,
#     'subscribers': int,
#     'last_used_timestamp': float,
#     'video_count': int,
#     'active_event': Optional[Dict[str, Any]] # {'type': 'bonus_next_video', 'modifier': 5, 'message': '...'}
# }

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

async def is_subscribed(user_id: int, bot) -> bool:
    """Проверяет, подписан ли пользователь на обязательный канал."""
    if not CHANNEL_ID:
        return True
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER]
    except Exception as e:
        logger.error(f"Ошибка проверки подписки для user_id {user_id} на {CHANNEL_ID}: {e}")
        return False

def load_data() -> Dict[int, Dict[str, Any]]:
    """Загружает данные пользователей из файла. Включает поля video_count и active_event."""
    data: Dict[int, Dict[str, Any]] = {}
    expected_headers = "user_id | username | subscribers | last_used_timestamp | video_count | active_event_type | active_event_modifier | active_event_message"
    
    if not os.path.exists(DATABASE_FILE):
        with open(DATABASE_FILE, 'w', encoding='utf-8') as file:
            file.write(expected_headers + "\n")
        return data

    try:
        with open(DATABASE_FILE, 'r', encoding='utf-8') as file:
            lines = file.readlines()
            if not lines or not lines[0].strip().startswith("user_id"):
                with open(DATABASE_FILE, 'w', encoding='utf-8') as f_write:
                    f_write.write(expected_headers + "\n")
                return data

            for line in lines[1:]:
                parts = line.strip().split(' | ')
                if len(parts) == 8: # Обновлено количество полей
                    user_id_str, username, subscribers_str, last_used_ts_str, video_count_str, event_type, event_modifier_str, event_message = parts
                    try:
                        user_data: Dict[str, Any] = {
                            'username': username.strip(),
                            'subscribers': int(subscribers_str.strip()),
                            'last_used_timestamp': float(last_used_ts_str.strip()),
                            'video_count': int(video_count_str.strip()),
                            'active_event': None
                        }
                        if event_type and event_type != 'None':
                             user_data['active_event'] = {
                                'type': event_type,
                                'modifier': int(event_modifier_str) if event_modifier_str.isdigit() else float(event_modifier_str), # может быть int или float
                                'message': event_message.replace("\\n", "\n") # Восстанавливаем переносы строк
                            }
                        data[int(user_id_str)] = user_data
                    except ValueError as e:
                        logger.warning(f"Некорректная строка в базе данных (ValueError: {e}): {line.strip()}")
                else:
                    logger.warning(f"Некорректный формат строки ({len(parts)} частей) в базе данных: {line.strip()}")
    except Exception as e:
        logger.error(f"Ошибка при загрузке данных из {DATABASE_FILE}: {e}")
        return {}
    return data

def save_data(data: Dict[int, Dict[str, Any]]):
    """Сохраняет данные пользователей в файл, включая video_count и active_event."""
    try:
        with open(DATABASE_FILE, 'w', encoding='utf-8') as file:
            file.write("user_id | username | subscribers | last_used_timestamp | video_count | active_event_type | active_event_modifier | active_event_message\n")
            for user_id, info in data.items():
                event_type = info.get('active_event', {}).get('type', 'None') if info.get('active_event') else 'None'
                event_modifier = info.get('active_event', {}).get('modifier', '0') if info.get('active_event') else '0'
                # Экранируем переносы строк в сообщении события перед сохранением
                event_message = info.get('active_event', {}).get('message', 'None').replace("\n", "\\n") if info.get('active_event') else 'None'
                
                file.write(
                    f"{user_id} | {info['username']} | {info['subscribers']} | "
                    f"{info['last_used_timestamp']} | {info.get('video_count', 0)} | "
                    f"{event_type} | {event_modifier} | {event_message}\n"
                )
    except Exception as e:
        logger.error(f"Ошибка при сохранении данных в {DATABASE_FILE}: {e}")

def load_keywords(filename: str = KEYWORDS_FILE) -> list:
    if not os.path.exists(filename):
        logger.warning(f"Файл ключевых слов {filename} не найден. Создан пустой.")
        with open(filename, 'w', encoding='utf-8') as f:
            f.write("# Ключевые слова (каждое с новой строки)\nпопулярное\nхайп\n")
        return ["популярное", "хайп"]
    try:
        with open(filename, 'r', encoding='utf-8') as file:
            return [line.strip().lower() for line in file if line.strip() and not line.startswith('#')]
    except Exception as e:
        logger.error(f"Ошибка загрузки ключевых слов {filename}: {e}")
        return []

def evaluate_video_popularity(video_title: str, base_popularity_modifier: int = 0) -> int:
    """Оценивает популярность видео, учитывая базовый модификатор (например, от события)."""
    keywords = load_keywords()
    title_lower = video_title.lower()
    keyword_bonus = sum(KEYWORD_BONUS_POINTS for keyword in keywords if keyword in title_lower)
    random_score = random.randint(POPULARITY_RANDOM_MIN, POPULARITY_RANDOM_MAX)
    return keyword_bonus + random_score + base_popularity_modifier

async def subscription_check_middleware(update: Update, context: CallbackContext, command_handler_coro):
    if not CHANNEL_ID:
        await command_handler_coro(update, context)
        return

    user_id = update.effective_user.id
    if not await is_subscribed(user_id, context.bot):
        channel_link = CHANNEL_ID if CHANNEL_ID.startswith('@') else f"https://t.me/c/{CHANNEL_ID.replace('-100', '')}"
        try:
            chat = await context.bot.get_chat(CHANNEL_ID)
            channel_display_name = chat.title or CHANNEL_ID
        except Exception:
            channel_display_name = CHANNEL_ID
        await update.message.reply_text(
            f"Для использования этой команды, пожалуйста, подпишитесь на наш канал: {channel_display_name} ({channel_link}).\n"
            "После подписки попробуйте снова."
        )
        return
    await command_handler_coro(update, context)


def get_random_event(user_subscribers: int) -> Optional[Dict[str, Any]]:
    """Генерирует случайное событие для пользователя."""
    roll = random.randint(1, 100)
    
    # События сработают только если у пользователя есть хотя бы немного подписчиков
    # или после нескольких видео, чтобы не было слишком легко вначале или слишком сурово
    if user_subscribers < 10 and random.randint(1,3) != 1 : # Меньше шансов на событие для новичков
        return None

    if 75 <= roll <= 80: # Небольшой шанс на позитивное событие
        bonus = random.randint(3, 7)
        return {
            "type": "bonus_next_video",
            "modifier": bonus,
            "message": (f"🎉 Внезапный хайп! Ваше следующее видео получит бонус +{bonus} к популярности! "
                        "Тщательно выбирайте тему!")
        }
    elif 81 <= roll <= 83 and user_subscribers > 20: # Негативное событие, если есть что терять
        malus = random.randint(2, 5)
        return {
            "type": "malus_next_video",
            "modifier": -malus,
            "message": (f"📉 Технические неполадки на {BOT_NAME}... Следующее видео может пострадать "
                        f"(-{malus} к популярности). Постарайтесь сделать его максимально интересным!")
        }
    # Можно добавить больше типов событий
    return None


# --- ОБРАБОТЧИКИ КОМАНД ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"Пользователь {user.name} (ID: {user.id}) вызвал /start")

    if CHANNEL_ID and not await is_subscribed(user.id, context.bot):
        channel_link = CHANNEL_ID if CHANNEL_ID.startswith('@') else f"https://t.me/c/{CHANNEL_ID.lstrip('-100')}"
        channel_display_name = CHANNEL_ID
        if not CHANNEL_ID.startswith('@'):
            try:
                chat = await context.bot.get_chat(CHANNEL_ID)
                channel_display_name = chat.title or CHANNEL_ID
            except Exception:
                pass # Оставляем ID если не удалось получить имя

        await update.message.reply_text(
            f"👋 Привет, {user.first_name}!\n"
            f"Я {BOT_NAME}, симулятор TeleTube-звезды!\n\n"
            f"Для начала, пожалуйста, подпишись на наш канал: {channel_display_name} ({channel_link}).\n"
            "После подписки нажми /start еще раз или используй /help для списка команд."
        )
        return

    data = load_data()
    if user.id not in data:
        data[user.id] = {
            'username': user.name, # Используем user.name для лучшего отображения (включает @username если есть)
            'subscribers': 0,
            'last_used_timestamp': 0.0,
            'video_count': 0,
            'active_event': None
        }
        save_data(data)
        logger.info(f"Новый пользователь {user.name} (ID: {user.id}) добавлен.")

    keyboard = [
        [KeyboardButton(f"/addvideo Новое Видео")],
        [KeyboardButton("/leaderboard"), KeyboardButton("/leaderboardpic")],
        [KeyboardButton("/myprofile"), KeyboardButton("/help")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

    await update.message.reply_text(
        f"🚀 Привет, {user.first_name}! Ты в игре {BOT_NAME}!\n\n"
        "Снимай 'видео', набирай подписчиков и стань самым популярным!\n"
        "Используй /help или кнопки ниже.",
        reply_markup=reply_markup
    )

async def add_video_command_internal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not context.args:
        await update.message.reply_text(
            "Укажи название видео: `/addvideo Мое Супер Видео`", parse_mode=ParseMode.MARKDOWN
        )
        return

    video_title = ' '.join(context.args)
    current_timestamp = datetime.now().timestamp()
    data = load_data()

    if user.id not in data: # На случай, если пользователь пропустил /start или данные были удалены
        data[user.id] = {
            'username': user.name, 'subscribers': 0, 'last_used_timestamp': 0.0, 
            'video_count': 0, 'active_event': None
        }
    
    user_data = data[user.id]
    # Обновляем имя пользователя, если оно изменилось с момента последней записи
    if user_data['username'] != user.name:
        user_data['username'] = user.name
        
    last_used_dt = datetime.fromtimestamp(user_data.get('last_used_timestamp', 0.0))
    
    if datetime.now() - last_used_dt < timedelta(hours=COOLDOWN_HOURS):
        remaining_time = timedelta(hours=COOLDOWN_HOURS) - (datetime.now() - last_used_dt)
        hours, rem_secs = divmod(remaining_time.seconds, 3600)
        minutes, _ = divmod(rem_secs, 60)
        await update.message.reply_text(
            f"⏳ {user.first_name}, кулдаун! Следующее видео через {hours} ч {minutes} мин."
        )
        return

    # --- Обработка активного события ---
    event_modifier = 0
    event_applied_message = ""
    if user_data.get('active_event'):
        event = user_data['active_event']
        event_applied_message = f"\n✨ *Активное событие*: {event['message']}"
        if event['type'] in ['bonus_next_video', 'malus_next_video']:
            event_modifier = event['modifier']
        user_data['active_event'] = None # Событие применяется один раз

    popularity_score = evaluate_video_popularity(video_title, base_popularity_modifier=event_modifier)
    subscribers_change = popularity_score # Базовое изменение = популярности
    bonus_subscribers = 0
    
    message_parts = [f"🎬 {user_data['username']}, видео \"{video_title}\" опубликовано!{event_applied_message}"]

    if popularity_score > POPULARITY_THRESHOLD_BONUS:
        bonus_subscribers = random.randint(BONUS_SUBSCRIBERS_MIN, BONUS_SUBSCRIBERS_MAX)
        subscribers_change += bonus_subscribers
        message_parts.append(f"🌟 Супер! Тема популярна! Бонус: +{bonus_subscribers} пдп.")
    elif popularity_score < NEGATIVE_POPULARITY_THRESHOLD: # Сильно негативная популярность
        message_parts.append(f"📉 Ох, видео не зашло... это был риск.")
        # Можно добавить шанс на потерю *большего* кол-ва подписчиков
    elif popularity_score < 0:
         message_parts.append(f"😕 Упс, тема не особо популярна. Не сдавайся!")
    else:
        message_parts.append(f"👍 Неплохое начало!")
    
    user_data['subscribers'] = max(0, user_data['subscribers'] + subscribers_change)
    user_data['last_used_timestamp'] = current_timestamp
    user_data['video_count'] = user_data.get('video_count', 0) + 1
    
    if subscribers_change > 0:
        message_parts.append(f"📈 +{subscribers_change} подписчиков.")
    elif subscribers_change < 0:
        message_parts.append(f"📉 {subscribers_change} подписчиков.") # subscribers_change уже отрицательное
    else:
        message_parts.append(f"🤷 Количество подписчиков не изменилось.")
    
    message_parts.append(f"Итого у тебя: {user_data['subscribers']} пдп. Видео опубликовано: {user_data['video_count']}.")

    # --- Генерация нового случайного события ---
    # Событие генерируется ПОСЛЕ публикации, чтобы повлиять на СЛЕДУЮЩЕЕ видео
    if random.randint(1,4) == 1: # 25% шанс на попытку генерации события
        new_event = get_random_event(user_data['subscribers'])
        if new_event:
            user_data['active_event'] = new_event
            message_parts.append(f"\n🔔 *Новое событие!* {new_event['message']}")
            logger.info(f"Для {user.name} сгенерировано событие: {new_event['type']}")

    save_data(data)
    await update.message.reply_text("\n".join(message_parts), parse_mode=ParseMode.MARKDOWN)
    logger.info(f"Видео '{video_title}' от {user.name}. Изм: {subscribers_change}. Всего: {user_data['subscribers']}. Видео: {user_data['video_count']}")

async def add_video_command_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await subscription_check_middleware(update, context, add_video_command_internal)

async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    if not data:
        await update.message.reply_text(f"🏆 В {BOT_NAME} пока пусто... Будь первым!")
        return

    sorted_users = sorted(data.items(), key=lambda item: item[1]['subscribers'], reverse=True)
    leaderboard_message = f"🏆 <b>Топ {BOT_NAME}еров:</b>\n\n"
    max_display = 15
    
    displayed_count = 0
    for i, (user_id, info) in enumerate(sorted_users):
        if info['subscribers'] <=0 and i >= max_display : # Не показываем нулевых подписчиков за пределами топа
             continue
        leaderboard_message += f"{displayed_count + 1}. {info['username']} - {info['subscribers']} пдп. (видео: {info.get('video_count',0)})\n"
        displayed_count += 1
        if displayed_count >= max_display:
            break

    if displayed_count == 0:
         await update.message.reply_text("🏆 Пока нет пользователей с подписчиками в топе.")
         return
         
    await update.message.reply_text(leaderboard_message, parse_mode=ParseMode.HTML)

async def leaderboard_pic_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data_dict = load_data()
    if not data_dict:
        await update.message.reply_text("📊 Данных для графика пока нет.")
        return

    df = pd.DataFrame.from_dict(data_dict, orient='index')
    if 'subscribers' not in df.columns or df['subscribers'].isnull().all() or not pd.api.types.is_numeric_dtype(df['subscribers']):
        await update.message.reply_text("📊 Недостаточно данных о подписчиках для графика.")
        return

    valid_data = df[df['subscribers'] > 0].sort_values(by='subscribers', ascending=False)
    if valid_data.empty:
        await update.message.reply_text("📊 Нет пользователей с подписчиками для графика.")
        return

    top_data = valid_data.head(15)
    usernames = top_data['username'].values
    subscribers_counts = top_data['subscribers'].values

    fig, ax = plt.subplots(figsize=(10, 7), facecolor='white')
    wedges, texts, autotexts = ax.pie(
        subscribers_counts,
        autopct=lambda p: f'{p:.1f}%' if p > 3 else '',
        startangle=140,
        colors=plt.cm.Paired(np.linspace(0, 1, len(subscribers_counts)))
    )
    plt.setp(autotexts, size=8, weight="bold", color="white")
    ax.set_title(f"🏆 Топ {BOT_NAME}еров (Диаграмма)", fontsize=16, pad=20)
    ax.legend(wedges, [f"{name} ({count})" for name, count in zip(usernames, subscribers_counts)],
              title="Топ пользователей:", loc="center left", bbox_to_anchor=(1, 0, 0.5, 1), fontsize=9)
    plt.tight_layout(rect=[0, 0, 0.75, 1])

    try:
        plt.savefig(LEADERBOARD_IMAGE_FILE, format='png', dpi=150)
        with open(LEADERBOARD_IMAGE_FILE, 'rb') as photo_file:
            await context.bot.send_photo(chat_id=update.effective_chat.id, photo=photo_file)
    except Exception as e:
        logger.error(f"Ошибка отправки изображения топа: {e}")
        await update.message.reply_text("Не удалось сгенерировать изображение топа.")
    finally:
        if os.path.exists(LEADERBOARD_IMAGE_FILE): os.remove(LEADERBOARD_IMAGE_FILE)
        plt.close(fig)

async def my_profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = load_data()

    if user.id not in data or not data[user.id]: # Добавлена проверка на пустой data[user.id]
        await update.message.reply_text(
            f"👤 Твой профиль в {BOT_NAME} пока пуст. Начни с /addvideo <название>!"
        )
        return

    user_info = data[user.id]
    username_display = user_info.get('username', user.first_name) # Используем сохраненное имя, или имя из ТГ
    subscribers = user_info.get('subscribers', 0)
    video_count = user_info.get('video_count', 0)
    last_used_ts = user_info.get('last_used_timestamp', 0)
    
    profile_message = [f"👤 <b>Твой профиль, {username_display}:</b>\n"]
    profile_message.append(f"👥 Подписчики: {subscribers}")
    profile_message.append(f"📹 Опубликовано видео: {video_count}")

    if last_used_ts == 0:
        profile_message.append("Вы еще не публиковали видео.")
        can_post_str = "Публикуй первое видео: /addvideo <название>!"
    else:
        last_used_dt = datetime.fromtimestamp(last_used_ts)
        profile_message.append(f"🕓 Последнее видео: {last_used_dt.strftime('%Y-%m-%d %H:%M')}")
        next_video_time = last_used_dt + timedelta(hours=COOLDOWN_HOURS)
        if datetime.now() < next_video_time:
            remaining_time = next_video_time - datetime.now()
            hours, rem_secs = divmod(remaining_time.seconds, 3600)
            minutes, _ = divmod(rem_secs, 60)
            can_post_str = f"Следующее видео через: {hours} ч {minutes} мин."
        else:
            can_post_str = "Можешь публиковать новое видео!"
    
    profile_message.append(f"⏳ {can_post_str}")

    active_event = user_info.get('active_event')
    if active_event:
        profile_message.append(f"\n✨ <b>Активное событие:</b> {active_event['message']}")

    await update.message.reply_text("\n".join(profile_message), parse_mode=ParseMode.HTML)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        f"🌟 <b>Добро пожаловать в {BOT_NAME}!</b> 🌟\n\n"
        "Здесь ты можешь 'публиковать видео' и соревноваться за звание самого популярного!\n\n"
        "<b>Основные команды:</b>\n"
        "🎬 `/addvideo <название>` - Опубликовать видео.\n"
        "🏆 `/leaderboard` - Текстовый топ.\n"
        "📊 `/leaderboardpic` - Графический топ.\n"
        "👤 `/myprofile` - Твой профиль.\n"
        "🆘 `/help` - Это сообщение.\n\n"
        "<b>Механика:</b>\n"
        "Популярность видео зависит от названия (ищи ключевые слова в `keywords.txt`!) и удачи. "
        "Публикация раз в {cooldown} часов. Иногда случаются случайные события!\n"
        "Удачи!"
    ).format(cooldown=COOLDOWN_HOURS, bot_name=BOT_NAME)
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)

# --- АДМИНСКИЕ КОМАНДЫ ---

async def admin_check(update: Update) -> bool:
    """Проверяет, является ли пользователь администратором."""
    if update.effective_user.id != CREATOR_ID:
        await update.message.reply_text("⛔ Эта команда доступна только администратору бота.")
        return False
    return True

async def admin_cheat_add_subscribers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await admin_check(update): return

    if len(context.args) < 2:
        await update.message.reply_text("Использование: `/CHEATaddsub <user_id или @username> <количество>`")
        return

    target_identifier = context.args[0]
    try: amount = int(context.args[1])
    except ValueError:
        await update.message.reply_text("Количество должно быть числом.")
        return

    data = load_data()
    target_user_id = None
    target_username_display = target_identifier

    if target_identifier.startswith('@'):
        username_to_find = target_identifier[1:].lower()
        found = False
        for uid, uinfo in data.items():
            if uinfo.get('username','').lower() == username_to_find or \
               (uinfo.get('username','').startswith('@') and uinfo.get('username','')[1:].lower() == username_to_find) :
                target_user_id = uid
                target_username_display = uinfo['username']
                found = True
                break
        if not found:
            await update.message.reply_text(f"Пользователь {target_identifier} не найден в базе.")
            return
    else:
        try:
            target_user_id = int(target_identifier)
            if target_user_id not in data:
                await update.message.reply_text(f"Пользователь с ID {target_user_id} не найден.")
                return
            target_username_display = data[target_user_id]['username']
        except ValueError:
            await update.message.reply_text("Некорректный ID. Укажите число или @username.")
            return

    if target_user_id is not None: # Явная проверка
        data[target_user_id]['subscribers'] = data[target_user_id].get('subscribers', 0) + amount
        data[target_user_id]['subscribers'] = max(0, data[target_user_id]['subscribers'])
        save_data(data)
        await update.message.reply_text(
            f"Пользователю {target_username_display} (ID: {target_user_id}) "
            f"{'добавлено' if amount >= 0 else 'уменьшено на'} {abs(amount)} пдп. "
            f"Новый баланс: {data[target_user_id]['subscribers']}."
        )
        logger.info(f"Admin {update.effective_user.name} set subs for {target_username_display} by {amount}. New: {data[target_user_id]['subscribers']}")

async def admin_delete_database(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_check(update): return
    if os.path.exists(DATABASE_FILE):
        try:
            os.remove(DATABASE_FILE)
            await update.message.reply_text(f"Файл '{DATABASE_FILE}' удален. Будет создан заново.")
            logger.info(f"Admin {update.effective_user.name} deleted {DATABASE_FILE}")
        except Exception as e:
            await update.message.reply_text(f"Ошибка удаления файла: {e}")
    else:
        await update.message.reply_text(f"Файл '{DATABASE_FILE}' уже удален или не существует.")

async def admin_bot_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_check(update): return
    
    data = load_data()
    total_users = len(data)
    total_subscribers = sum(info.get('subscribers', 0) for info in data.values())
    total_videos = sum(info.get('video_count', 0) for info in data.values())
    
    active_users_last_24h = 0
    cutoff_timestamp = (datetime.now() - timedelta(days=1)).timestamp()
    for user_info in data.values():
        if user_info.get('last_used_timestamp', 0) >= cutoff_timestamp:
            active_users_last_24h +=1
            
    stats_message = (
        f"📊 <b>Статистика бота {BOT_NAME}:</b>\n\n"
        f"👥 Всего пользователей: {total_users}\n"
        f"▶️ Всего опубликовано видео: {total_videos}\n"
        f"📈 Общее количество подписчиков у всех: {total_subscribers}\n"
        f" активных за последние 24 часа: {active_users_last_24h}\n"
        f"🔧 База данных: {DATABASE_FILE}\n"
        f"🔑 Ключевые слова: {KEYWORDS_FILE}"
    )
    await update.message.reply_text(stats_message, parse_mode=ParseMode.HTML)


async def post_init(application: Application) -> None:
    bot_commands = [
        BotCommand("start", "🚀 Запустить/Перезапустить бота"),
        BotCommand("addvideo", "🎬 Опубликовать видео"),
        BotCommand("leaderboard", "🏆 Глобальный топ (текст)"),
        BotCommand("leaderboardpic", "📊 Глобальный топ (картинка)"),
        BotCommand("myprofile", "👤 Мой профиль"),
        BotCommand("help", "❓ Помощь"),
    ]
    admin_commands_for_creator = [
        BotCommand("CHEATaddsub", "💰 Админ: Изменить подписчиков"),
        BotCommand("CHEATDeleteDatabase", "🗑️ Админ: Стереть базу данных"),
        BotCommand("botstats", "📈 Админ: Статистика бота"),
    ]

    await application.bot.set_my_commands(bot_commands) # Общие команды для всех
    if CREATOR_ID:
        try:
            # Установка отдельных команд для создателя
            await application.bot.set_my_commands(bot_commands + admin_commands_for_creator, scope=BotCommandScopeChat(chat_id=CREATOR_ID))
            logger.info(f"Установлены общие и админские команды (для ID {CREATOR_ID}).")
        except Exception as e:
            logger.error(f"Не удалось установить админские команды для создателя: {e}. Установлены только общие.")
    else:
        logger.info("Установлены общие команды (CREATOR_ID не указан).")


    # Проверки конфигурации
    if not BOT_TOKEN: logger.critical("BOT_TOKEN не найден в .env!")
    if not CREATOR_ID: logger.warning("CREATOR_ID не найден в .env! Админ-команды не будут работать корректно.")
    if CHANNEL_ID: logger.info(f"Проверка подписки на канал {CHANNEL_ID} активна.")
    else: logger.info("CHANNEL_ID не указан, проверка подписки отключена.")


def main() -> None:
    if not BOT_TOKEN:
        print("Ошибка: BOT_TOKEN не указан. Проверьте .env файл.")
        return

    application = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    handlers = [
        CommandHandler("start", start_command),
        CommandHandler("help", help_command),
        CommandHandler("myprofile", my_profile_command),
        CommandHandler("leaderboard", leaderboard_command),
        CommandHandler("top", leaderboard_command),
        CommandHandler("stats", leaderboard_command),
        CommandHandler("leaderboardpic", leaderboard_pic_command),
        CommandHandler("toppic", leaderboard_pic_command),
        CommandHandler("statspic", leaderboard_pic_command),
        CommandHandler("CHEATaddsub", admin_cheat_add_subscribers),
        CommandHandler("CHEATDeleteDatabase", admin_delete_database),
        CommandHandler("botstats", admin_bot_stats),
    ]
    add_video_aliases = ["addvideo", "video", "add", "newvideo", "publishvideo", "new", "publish"]
    for alias in add_video_aliases:
        handlers.append(CommandHandler(alias, add_video_command_wrapper))
    
    application.add_handlers(handlers)

    logger.info(f"Бот {BOT_NAME} запускается...")
    application.run_polling()


if __name__ == '__main__':
    # Инициализация файлов, если их нет
    if not os.path.exists(DATABASE_FILE):
        with open(DATABASE_FILE, 'w', encoding='utf-8') as f:
            f.write("user_id | username | subscribers | last_used_timestamp | video_count | active_event_type | active_event_modifier | active_event_message\n")
        logger.info(f"Создан файл базы данных: {DATABASE_FILE}")

    if not os.path.exists(KEYWORDS_FILE):
        with open(KEYWORDS_FILE, 'w', encoding='utf-8') as f:
            f.write("# Ключевые слова (каждое с новой строки)\nпопулярное\nхайп\nтоп\nэксклюзив\nсенсация\nшок\n")
        logger.info(f"Создан файл ключевых слов: {KEYWORDS_FILE}")
    
    main()