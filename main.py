import asyncio
import logging
import os
import random
from datetime import datetime, timedelta

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
load_dotenv()  # Загружает переменные из .env файла

BOT_TOKEN = os.getenv("BOT_TOKEN")
CREATOR_ID = int(os.getenv("CREATOR_ID", 0)) # Преобразуем в int, 0 если не найдено
CHANNEL_ID = os.getenv("CHANNEL_ID") # Например, "@TeleTubeNews" или "-1001234567890" для приватных

DATABASE_FILE = os.getenv("DATABASE_FILE", "database.txt")
KEYWORDS_FILE = os.getenv("KEYWORDS_FILE", "keywords.txt")
LEADERBOARD_IMAGE_FILE = "leaderboard_pic.png"

COOLDOWN_HOURS = 12
POPULARITY_THRESHOLD = 7
KEYWORD_BONUS_POINTS = 2
POPULARITY_RANDOM_MIN = -10
POPULARITY_RANDOM_MAX = 20
BONUS_SUBSCRIBERS_MIN = 1
BONUS_SUBSCRIBERS_MAX = 5

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

async def is_subscribed(user_id: int, bot) -> bool:
    """Проверяет, подписан ли пользователь на обязательный канал."""
    if not CHANNEL_ID:
        logger.warning("CHANNEL_ID не указан, проверка подписки отключена.")
        return True # Если канал не указан, считаем, что проверка не нужна
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER]
    except Exception as e:
        logger.error(f"Ошибка при проверке подписки для user_id {user_id} на канал {CHANNEL_ID}: {e}")
        return False # В случае ошибки (например, бот не админ в канале) считаем, что не подписан

def load_data() -> dict:
    """Загружает данные пользователей из файла."""
    data = {}
    if not os.path.exists(DATABASE_FILE):
        # Если файла нет, создаем его с заголовком
        with open(DATABASE_FILE, 'w', encoding='utf-8') as file:
            file.write("user_id | username | subscribers | last_used_timestamp\n")
        return data

    try:
        with open(DATABASE_FILE, 'r', encoding='utf-8') as file:
            lines = file.readlines()
            if not lines or not lines[0].strip().startswith("user_id"): # Проверка на пустой файл или отсутствие заголовка
                # Если заголовок отсутствует или файл пустой, перезаписываем с заголовком
                with open(DATABASE_FILE, 'w', encoding='utf-8') as f_write:
                    f_write.write("user_id | username | subscribers | last_used_timestamp\n")
                return data

            for line in lines[1:]: # Пропускаем заголовок
                parts = line.strip().split(' | ')
                if len(parts) == 4:
                    user_id, username, subscribers, last_used_ts = parts
                    try:
                        data[int(user_id)] = {
                            'username': username.strip(),
                            'subscribers': int(subscribers.strip()),
                            'last_used_timestamp': float(last_used_ts.strip()) # Храним как timestamp
                        }
                    except ValueError:
                        logger.warning(f"Некорректная строка в базе данных: {line.strip()}")
                else:
                    logger.warning(f"Некорректный формат строки в базе данных: {line.strip()}")
    except Exception as e:
        logger.error(f"Ошибка при загрузке данных из {DATABASE_FILE}: {e}")
        # В случае критической ошибки можно попробовать создать бэкап и пересоздать файл
        # Для простоты, просто вернем пустой словарь, чтобы бот мог продолжить работу с новыми данными
        return {}
    return data

def save_data(data: dict):
    """Сохраняет данные пользователей в файл."""
    try:
        with open(DATABASE_FILE, 'w', encoding='utf-8') as file:
            file.write("user_id | username | subscribers | last_used_timestamp\n")
            for user_id, info in data.items():
                file.write(
                    f"{user_id} | {info['username']} | {info['subscribers']} | {info['last_used_timestamp']}\n"
                )
    except Exception as e:
        logger.error(f"Ошибка при сохранении данных в {DATABASE_FILE}: {e}")


def load_keywords(filename: str = KEYWORDS_FILE) -> list:
    """Загружает ключевые слова из файла."""
    if not os.path.exists(filename):
        logger.warning(f"Файл ключевых слов {filename} не найден. Создан пустой.")
        with open(filename, 'w', encoding='utf-8') as f:
            f.write("# Добавьте сюда ключевые слова, каждое с новой строки\n")
            f.write("популярное\n")
            f.write("хайп\n")
        return ["популярное", "хайп"] # Возвращаем дефолтные, если файла нет

    try:
        with open(filename, 'r', encoding='utf-8') as file:
            return [line.strip().lower() for line in file if line.strip() and not line.startswith('#')]
    except FileNotFoundError:
        logger.error(f"Файл {filename} не найден, хотя должен был быть создан. Возвращены пустые ключевые слова.")
        return []

def evaluate_video_popularity(video_title: str) -> int:
    """Оценивает популярность видео на основе ключевых слов и случайности."""
    keywords = load_keywords()
    title_lower = video_title.lower()
    keyword_bonus = sum(KEYWORD_BONUS_POINTS for keyword in keywords if keyword in title_lower)
    random_score = random.randint(POPULARITY_RANDOM_MIN, POPULARITY_RANDOM_MAX)
    return keyword_bonus + random_score

async def subscription_check_middleware(update: Update, context: CallbackContext, command_handler_coro):
    """Middleware для проверки подписки перед выполнением команды."""
    if not CHANNEL_ID: # Если канал не задан, пропускаем проверку
        await command_handler_coro(update, context)
        return

    user_id = update.effective_user.id
    if not await is_subscribed(user_id, context.bot):
        channel_link = CHANNEL_ID if CHANNEL_ID.startswith('@') else f"https://t.me/c/{CHANNEL_ID.replace('-100', '')}" # Примерная ссылка для приватных
        if CHANNEL_ID.startswith('@'):
            channel_display_name = CHANNEL_ID
        else:
            try:
                chat = await context.bot.get_chat(CHANNEL_ID)
                channel_display_name = chat.title or f"канал (ID: {CHANNEL_ID})"
            except Exception:
                channel_display_name = f"канал ({CHANNEL_ID})"

        await update.message.reply_text(
            f"Для использования этой команды, пожалуйста, подпишитесь на наш канал: {channel_display_name} ({channel_link}).\n"
            "После подписки попробуйте снова."
        )
        return
    await command_handler_coro(update, context)

# --- ОБРАБОТЧИКИ КОМАНД ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start."""
    user = update.effective_user
    logger.info(f"Пользователь {user.username or user.first_name} (ID: {user.id}) вызвал /start")

    if CHANNEL_ID and not await is_subscribed(user.id, context.bot):
        channel_link = CHANNEL_ID if CHANNEL_ID.startswith('@') else f"https://t.me/c/{CHANNEL_ID.replace('-100', '')}"
        channel_display_name = CHANNEL_ID if CHANNEL_ID.startswith('@') else f"канал ({CHANNEL_ID})"
        await update.message.reply_text(
            f"👋 Привет, {user.first_name}!\n"
            f"Я TeleTubeSim бот, который поможет тебе стать звездой!\n\n"
            f"Для начала, пожалуйста, подпишись на наш канал: {channel_display_name} ({channel_link}).\n"
            "После подписки нажми /start еще раз или используй /help для списка команд."
        )
        return

    data = load_data()
    if user.id not in data:
        data[user.id] = {
            'username': user.username or user.first_name,
            'subscribers': 0,
            'last_used_timestamp': 0.0 # Никогда не использовал
        }
        save_data(data)
        logger.info(f"Новый пользователь {user.username or user.first_name} (ID: {user.id}) добавлен в базу.")

    keyboard = [
        [KeyboardButton("/addvideo Новое Видео")],
        [KeyboardButton("/leaderboard"), KeyboardButton("/leaderboardpic")],
        [KeyboardButton("/myprofile"), KeyboardButton("/help")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

    await update.message.reply_text(
        f"🚀 Привет, {user.first_name}! Ты в игре TeleTubeSim!\n\n"
        "Снимай 'видео', набирай подписчиков и стань самым популярным!\n\n"
        "Используй /help для получения списка команд или кнопки ниже.",
        reply_markup=reply_markup
    )

async def add_video_command_internal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Внутренняя логика добавления видео (после проверки подписки)."""
    user = update.effective_user
    user_id = user.id
    username = user.username or user.first_name

    if not context.args:
        await update.message.reply_text(
            "Нужно название для твоего видео! ✨\n"
            "Используй команду так: `/addvideo Мое Супер Видео`\n\n"
            "Также доступны псевдонимы: `/video`, `/add`, `/newvideo`, `/publishvideo`, `/new`, `/publish`.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    video_title = ' '.join(context.args)
    current_timestamp = datetime.now().timestamp()
    data = load_data()

    if user_id not in data: # На случай, если пользователь пропустил /start
        data[user_id] = {
            'username': username,
            'subscribers': 0,
            'last_used_timestamp': 0.0
        }

    user_data = data[user_id]
    last_used_dt = datetime.fromtimestamp(user_data.get('last_used_timestamp', 0.0))
    
    if datetime.now() - last_used_dt < timedelta(hours=COOLDOWN_HOURS):
        remaining_time = timedelta(hours=COOLDOWN_HOURS) - (datetime.now() - last_used_dt)
        hours, remainder = divmod(remaining_time.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        await update.message.reply_text(
            f"⏳ {username}, ты уже недавно публиковал видео. "
            f"Следующее можно будет опубликовать через {hours} ч {minutes} мин."
        )
        return

    popularity_score = evaluate_video_popularity(video_title)
    subscribers_change = popularity_score
    bonus_subscribers = 0

    message = f"🎬 {username}, твое видео \"{video_title}\" опубликовано!\n"

    if popularity_score > POPULARITY_THRESHOLD:
        bonus_subscribers = random.randint(BONUS_SUBSCRIBERS_MIN, BONUS_SUBSCRIBERS_MAX)
        subscribers_change += bonus_subscribers
        message += f"🌟 Вау! Тема оказалась супер популярной! Ты получил бонус: +{bonus_subscribers} подписчиков.\n"
    elif popularity_score < 0:
         message += f"😕 Упс, тема не зашла. Но не сдавайся!\n"
    else:
        message += f"👍 Неплохое начало!\n"


    user_data['subscribers'] = max(0, user_data['subscribers'] + subscribers_change) # Подписчики не могут быть < 0
    user_data['last_used_timestamp'] = current_timestamp
    user_data['username'] = username # Обновляем имя пользователя, если изменилось
    save_data(data)

    if subscribers_change > 0:
        message += f"📈 На тебя подписалось: {subscribers_change} человек.\n"
    elif subscribers_change < 0:
        message += f"📉 От тебя отписалось: {abs(subscribers_change)} человек.\n"
    else:
        message += f"🤷 Количество подписчиков не изменилось.\n"
    
    message += f"Теперь у тебя {user_data['subscribers']} подписчиков."
    await update.message.reply_text(message)
    logger.info(f"Пользователь {username} (ID: {user_id}) добавил видео '{video_title}', подписчиков: {subscribers_change}, всего: {user_data['subscribers']}")


async def add_video_command_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обертка для add_video_command_internal с проверкой подписки."""
    await subscription_check_middleware(update, context, add_video_command_internal)


async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отображает текстовый топ пользователей."""
    data = load_data()
    if not data:
        await update.message.reply_text("🏆 Пока пустовато... Стань первым в топе!")
        return

    # Преобразуем словарь в список для сортировки
    # Фильтруем пользователей с 0 подписчиков, если это нужно (здесь оставим всех)
    sorted_users = sorted(data.items(), key=lambda item: item[1]['subscribers'], reverse=True)

    leaderboard_message = "🏆 <b>Топ TeleTubeров по подписчикам:</b>\n\n"
    max_display = 15 # Сколько пользователей показывать
    for i, (user_id, info) in enumerate(sorted_users[:max_display], start=1):
        leaderboard_message += f"{i}. {info['username']} - {info['subscribers']} подписчиков\n"

    if not sorted_users: # Если после фильтрации (если она будет) никого не осталось
         await update.message.reply_text("🏆 Пока нет пользователей с подписчиками в топе.")
         return
         
    await update.message.reply_text(leaderboard_message, parse_mode=ParseMode.HTML)

async def leaderboard_pic_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отображает топ пользователей в виде круговой диаграммы."""
    data_dict = load_data()
    if not data_dict:
        await update.message.reply_text("📊 Данных для построения графика пока нет.")
        return

    # Преобразуем словарь в DataFrame
    df = pd.DataFrame.from_dict(data_dict, orient='index')
    
    # Проверяем, есть ли столбец 'subscribers' и содержит ли он числовые значения
    if 'subscribers' not in df.columns or df['subscribers'].isnull().all() or not pd.api.types.is_numeric_dtype(df['subscribers']):
        await update.message.reply_text("📊 Недостаточно данных о подписчиках для графика.")
        logger.warning(f"Проблема с данными для leaderboard_pic: {df.head()}")
        return

    # Отфильтруем тех, у кого подписчики <= 0, и отсортируем
    valid_data = df[df['subscribers'] > 0].sort_values(by='subscribers', ascending=False)

    if valid_data.empty:
        await update.message.reply_text("📊 Пока нет пользователей с положительным числом подписчиков для графика.")
        return

    top_data = valid_data.head(15) # Топ-15 для диаграммы

    usernames = top_data['username'].values
    subscribers_counts = top_data['subscribers'].values

    fig, ax = plt.subplots(figsize=(10, 7), facecolor='white')
    wedges, texts, autotexts = ax.pie(
        subscribers_counts,
        autopct=lambda p: f'{p:.1f}%' if p > 3 else '', # Показываем % если больше 3%
        startangle=140,
        colors=plt.cm.Paired(np.linspace(0, 1, len(subscribers_counts)))
    )
    
    plt.setp(autotexts, size=8, weight="bold", color="white")
    ax.set_title("🏆 Топ TeleTubeров (Диаграмма)", fontsize=16, pad=20)

    # Легенда
    ax.legend(wedges, [f"{name} ({count})" for name, count in zip(usernames, subscribers_counts)],
              title="Топ пользователей:",
              loc="center left",
              bbox_to_anchor=(1, 0, 0.5, 1),
              fontsize=9)

    plt.tight_layout(rect=[0, 0, 0.75, 1]) # Оставляем место для легенды

    try:
        plt.savefig(LEADERBOARD_IMAGE_FILE, format='png', dpi=150)
        with open(LEADERBOARD_IMAGE_FILE, 'rb') as photo_file:
            await context.bot.send_photo(chat_id=update.effective_chat.id, photo=photo_file)
    except Exception as e:
        logger.error(f"Ошибка при отправке изображения с топом: {e}")
        await update.message.reply_text("Не удалось сгенерировать изображение с топом. Попробуйте позже.")
    finally:
        if os.path.exists(LEADERBOARD_IMAGE_FILE):
            os.remove(LEADERBOARD_IMAGE_FILE)
        plt.close(fig) # Закрываем фигуру, чтобы освободить память

async def my_profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отображает профиль пользователя."""
    user = update.effective_user
    data = load_data()

    if user.id not in data:
        await update.message.reply_text(
            "👤 Я пока не нашел твой профиль. Похоже, ты еще не публиковал видео.\n"
            "Начни с команды /addvideo <название видео>!"
        )
        return

    user_info = data[user.id]
    subscribers = user_info.get('subscribers', 0)
    last_used_ts = user_info.get('last_used_timestamp', 0)
    
    if last_used_ts == 0:
        last_video_time_str = "еще не публиковал видео"
    else:
        last_used_dt = datetime.fromtimestamp(last_used_ts)
        last_video_time_str = last_used_dt.strftime('%Y-%m-%d %H:%M:%S')

        # Проверка времени до следующего видео
        next_video_time = last_used_dt + timedelta(hours=COOLDOWN_HOURS)
        if datetime.now() < next_video_time:
            remaining_time = next_video_time - datetime.now()
            hours, remainder = divmod(remaining_time.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            can_post_str = f"Сможешь опубликовать следующее через: {hours} ч {minutes} мин."
        else:
            can_post_str = "Можешь публиковать новое видео прямо сейчас!"


    profile_message = (
        f"👤 <b>Твой профиль, {user_info.get('username', user.first_name)}:</b>\n\n"
        f"👥 Подписчики: {subscribers}\n"
        f"🕓 Последнее видео: {last_video_time_str}\n"
        f"⏳ {can_post_str if last_used_ts != 0 else 'Публикуй первое видео командой /addvideo <название>!'}"
    )
    await update.message.reply_text(profile_message, parse_mode=ParseMode.HTML)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отображает справочное сообщение."""
    help_text = (
        "🌟 <b>Добро пожаловать в TeleTube Simulator!</b> 🌟\n\n"
        "Здесь ты можешь 'публиковать видео' и соревноваться за звание самого популярного TeleTubeра!\n\n"
        "<b>Основные команды:</b>\n"
        "🎬 `/addvideo <название видео>` - Опубликовать новое видео (или `/new`, `/publish` и др. псевдонимы).\n"
        "<em>Пример: `/addvideo Самое смешное видео 2077`</em>\n\n"
        "🏆 `/leaderboard` - Показать текстовый топ пользователей (или `/top`, `/stats`).\n"
        "📊 `/leaderboardpic` - Показать графический топ пользователей (или `/toppic`, `/statspic`).\n"
        "👤 `/myprofile` - Посмотреть свой текущий статус и количество подписчиков.\n"
        "🆘 `/help` - Показать это сообщение.\n\n"
        "<b>Как это работает?</b>\n"
        "Каждое 'видео' получает очки популярности в зависимости от названия (ищи ключевые слова!) и немного удачи. "
        "Чем популярнее видео, тем больше подписчиков ты получишь (или потеряешь 😥).\n"
        "Публиковать видео можно раз в {} часов.\n\n"
        "Удачи в покорении вершин TeleTube!"
    ).format(COOLDOWN_HOURS)
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)

# --- АДМИНСКИЕ КОМАНДЫ (только для CREATOR_ID) ---

async def admin_cheat_add_subscribers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Чит-команда для добавления подписчиков (только для создателя)."""
    user = update.effective_user
    if user.id != CREATOR_ID:
        await update.message.reply_text("⛔ Эта команда доступна только администратору бота.")
        return

    if len(context.args) < 2:
        await update.message.reply_text("Использование: `/CHEATaddsub <user_id или @username> <количество>`")
        return

    target_identifier = context.args[0]
    try:
        amount = int(context.args[1])
    except ValueError:
        await update.message.reply_text("Количество должно быть числом.")
        return

    data = load_data()
    target_user_id = None
    target_username_display = target_identifier

    # Попытка найти пользователя
    if target_identifier.startswith('@'):
        username_to_find = target_identifier[1:]
        for uid, uinfo in data.items():
            if uinfo['username'].lower() == username_to_find.lower():
                target_user_id = uid
                target_username_display = uinfo['username'] # Используем сохраненное имя
                break
        if not target_user_id:
            await update.message.reply_text(f"Пользователь с именем {target_identifier} не найден в базе.")
            return
    else:
        try:
            target_user_id = int(target_identifier)
            if target_user_id not in data:
                await update.message.reply_text(f"Пользователь с ID {target_user_id} не найден в базе.")
                return
            target_username_display = data[target_user_id]['username']
        except ValueError:
            await update.message.reply_text("Некорректный ID пользователя. Укажите число или @username.")
            return

    if target_user_id:
        data[target_user_id]['subscribers'] += amount
        data[target_user_id]['subscribers'] = max(0, data[target_user_id]['subscribers']) # Не ниже нуля
        save_data(data)
        await update.message.reply_text(
            f"Пользователю {target_username_display} (ID: {target_user_id}) "
            f"{'добавлено' if amount >= 0 else 'уменьшено на'} {abs(amount)} подписчиков. "
            f"Новый баланс: {data[target_user_id]['subscribers']}."
        )
        logger.info(f"Администратор {user.username or user.id} изменил подписчиков для {target_username_display} (ID: {target_user_id}) на {amount}. Новый баланс: {data[target_user_id]['subscribers']}")
    # (случай, когда target_user_id не найден, уже обработан выше)


async def admin_delete_database(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Чит-команда для удаления файла базы данных (только для создателя)."""
    user_id = update.effective_user.id
    if user_id != CREATOR_ID:
        await update.message.reply_text("⛔ Эта команда доступна только администратору бота.")
        return

    if os.path.exists(DATABASE_FILE):
        try:
            os.remove(DATABASE_FILE)
            await update.message.reply_text(f"Файл базы данных '{DATABASE_FILE}' успешно удален! "
                                            "Он будет создан заново при следующей операции с данными.")
            logger.info(f"Администратор {update.effective_user.username or user_id} удалил базу данных {DATABASE_FILE}")
        except Exception as e:
            await update.message.reply_text(f"Произошла ошибка при удалении файла: {e}")
            logger.error(f"Ошибка при удалении {DATABASE_FILE} администратором: {e}")
    else:
        await update.message.reply_text(f"Файл '{DATABASE_FILE}' уже был удален или не существует.")


async def post_init(application: Application) -> None:
    """Действия после инициализации приложения (например, установка команд)."""
    bot_commands = [
        BotCommand("start", "🚀 Запустить/Перезапустить бота"),
        BotCommand("addvideo", "🎬 Опубликовать видео (напр. /addvideo Мое видео)"),
        BotCommand("leaderboard", "🏆 Глобальный топ (текст)"),
        BotCommand("leaderboardpic", "📊 Глобальный топ (картинка)"),
        BotCommand("myprofile", "👤 Мой профиль и статистика"),
        BotCommand("help", "❓ Помощь по командам"),
    ]
    # Если бот запущен создателем, добавить админские команды в список
    # (не будет видно другим пользователям, если scope не Chat)
    # Для простоты, пока не будем добавлять их в видимый список
    await application.bot.set_my_commands(bot_commands)
    logger.info("Команды бота установлены.")

    if not BOT_TOKEN:
        logger.critical("Переменная BOT_TOKEN не найдена! Укажите ее в .env файле.")
        # Можно добавить sys.exit(1) если критично
    if not CREATOR_ID:
        logger.warning("Переменная CREATOR_ID не найдена! Админские команды не будут работать корректно.")
    if not CHANNEL_ID:
        logger.warning("Переменная CHANNEL_ID не найдена! Проверка подписки будет отключена.")
    else:
        logger.info(f"Проверка подписки настроена для канала: {CHANNEL_ID}")


# --- ГЛАВНАЯ ФУНКЦИЯ ---
def main() -> None:
    """Запуск бота."""
    if not BOT_TOKEN:
        print("Ошибка: BOT_TOKEN не указан в .env файле. Пожалуйста, создайте .env файл или укажите токен.")
        return

    application = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    # Основные команды
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("myprofile", my_profile_command))


    # Команды для добавления видео (с разными псевдонимами)
    add_video_aliases = ["addvideo", "video", "add", "newvideo", "publishvideo", "new", "publish"]
    for alias in add_video_aliases:
        application.add_handler(CommandHandler(alias, add_video_command_wrapper)) # Используем обертку

    # Команды для лидерборда (с разными псевдонимами)
    leaderboard_aliases = ["leaderboard", "top", "stats"]
    for alias in leaderboard_aliases:
        application.add_handler(CommandHandler(alias, leaderboard_command))

    leaderboard_pic_aliases = ["leaderboardpic", "toppic", "statspic"]
    for alias in leaderboard_pic_aliases:
        application.add_handler(CommandHandler(alias, leaderboard_pic_command))

    # Админские команды
    application.add_handler(CommandHandler("CHEATaddsub", admin_cheat_add_subscribers))
    application.add_handler(CommandHandler("CHEATDeleteDatabase", admin_delete_database))

    logger.info("Бот запускается...")
    application.run_polling()


if __name__ == '__main__':
    # Проверка и создание необходимых файлов, если их нет
    if not os.path.exists(DATABASE_FILE):
        with open(DATABASE_FILE, 'w', encoding='utf-8') as f:
            f.write("user_id | username | subscribers | last_used_timestamp\n")
        logger.info(f"Создан пустой файл базы данных: {DATABASE_FILE}")

    if not os.path.exists(KEYWORDS_FILE):
        with open(KEYWORDS_FILE, 'w', encoding='utf-8') as f:
            f.write("# Добавьте сюда ключевые слова, каждое с новой строки\n")
            f.write("популярное\n")
            f.write("хайп\n")
            f.write("топ\n")
            f.write("новое\n")
        logger.info(f"Создан файл с примерами ключевых слов: {KEYWORDS_FILE}")
    
    main()