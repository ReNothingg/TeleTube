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

BOT_TOKEN = os.getenv("BOT_TOKEN")
CREATOR_ID = int(os.getenv("CREATOR_ID", 0))
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
LOG_LEVEL = getattr(logging, LOG_LEVEL_STR, logging.INFO)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=LOG_LEVEL
)
logger = logging.getLogger(__name__)

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

def load_data() -> Dict[int, Dict[str, Any]]:
    if not os.path.exists(DATABASE_FILE):
        return {}
    try:
        with open(DATABASE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return {int(k): v for k, v in data.items()}
    except (json.JSONDecodeError, FileNotFoundError) as e:
        logger.error(f"Error loading data from {DATABASE_FILE}: {e}")
        return {}

def save_data(data: Dict[int, Dict[str, Any]]):
    try:
        with open(DATABASE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Error saving data to {DATABASE_FILE}: {e}")

def get_user_data(user_id: int, data: Dict[int, Dict[str, Any]], username: str) -> Dict[str, Any]:
    if user_id not in data:
        data[user_id] = {
            'username': username, 'subscribers': 0, 'last_used_timestamp': 0.0,
            'video_count': 0, 'active_event': None, 'currency': 0,
            'achievements_unlocked': [], 'last_daily_bonus_date': None,
            'daily_bonus_streak': 0, 'total_subs_from_videos': 0,
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
        logger.error(f"Subscription check error for {user_id} on {CHANNEL_ID}: {e}")
        return False

def load_keywords(filename: str = KEYWORDS_FILE) -> list:
    if not os.path.exists(filename):
        with open(filename, 'w', encoding='utf-8') as f: f.write("популярное\nхайп\n")
        return ["популярное", "хайп"]
    try:
        with open(filename, 'r', encoding='utf-8') as file:
            return [line.strip().lower() for line in file if line.strip() and not line.startswith('#')]
    except Exception as e:
        logger.error(f"Error loading keywords {filename}: {e}")
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

async def check_and_grant_achievements(user_data: Dict[str, Any], update: Update, context: CallbackContext) -> List[str]:
    newly_unlocked_messages = []
    for ach_id, ach_def in achievements_definition.items():
        if ach_id not in user_data.get('achievements_unlocked', []):
            unlocked = False
            if "condition_videos" in ach_def and user_data.get('video_count', 0) >= ach_def["condition_videos"]:
                unlocked = True
            if "condition_subs" in ach_def and user_data.get('subscribers', 0) >= ach_def["condition_subs"]:
                unlocked = True
            
            if unlocked:
                user_data.setdefault('achievements_unlocked', []).append(ach_id)
                reward_coins = ach_def.get("reward_coins", 0)
                user_data['currency'] = user_data.get('currency', 0) + reward_coins
                message = f"🏆 Новое достижение: **{ach_def['name']}**! (+{reward_coins} {DEFAULT_CURRENCY_NAME})"
                newly_unlocked_messages.append(message)
                
                # Отправка уведомления о достижении
                # Нужно убедиться, что update.effective_chat.id доступен
                # Для callback_query это query.message.chat_id
                chat_id_to_send = None
                if update.message:
                    chat_id_to_send = update.message.chat_id
                elif update.callback_query and update.callback_query.message:
                     chat_id_to_send = update.callback_query.message.chat_id
                
                if chat_id_to_send:
                    try:
                        await context.bot.send_message(chat_id=chat_id_to_send, text=message, parse_mode=ParseMode.MARKDOWN)
                    except Exception as e:
                        logger.error(f"Failed to send achievement notification to {chat_id_to_send}: {e}")
                else:
                     logger.warning(f"Could not determine chat_id to send achievement for user {user_data.get('username')}")
                logger.info(f"User {user_data.get('username')} got achievement {ach_id}")
    return newly_unlocked_messages


async def cooldown_notification_callback(context: CallbackContext):
    job = context.job
    user_id_from_job = job.user_id 
    chat_id_from_job = job.chat_id
    try:
        data = load_data()
        user_data = data.get(user_id_from_job)
        if user_data and user_data.get('cooldown_notification_job_id') == job.name:
            last_used_dt = datetime.fromtimestamp(user_data.get('last_used_timestamp', 0.0))
            next_video_time = last_used_dt + timedelta(hours=COOLDOWN_HOURS)
            if datetime.now() >= next_video_time:
                await context.bot.send_message(chat_id=chat_id_from_job, text=f"⏰ Ваш кулдаун в {BOT_NAME} завершен! /addvideo")
                user_data['cooldown_notification_job_id'] = None
                save_data(data)
    except Exception as e:
        logger.error(f"Error in cooldown_notification_callback for {user_id_from_job}: {e}")

def schedule_cooldown_notification(user_id: int, chat_id: int, cooldown_end_time: datetime, context: CallbackContext, user_data: Dict[str, Any]):
    if not hasattr(context, 'job_queue') or not context.job_queue:
        logger.warning("JobQueue not available, notification not scheduled.")
        return
    if user_data.get('cooldown_notification_job_id'):
        current_jobs = context.job_queue.get_jobs_by_name(user_data['cooldown_notification_job_id'])
        for job in current_jobs: job.schedule_removal()
        user_data['cooldown_notification_job_id'] = None
    delay = (cooldown_end_time - datetime.now()).total_seconds()
    if delay > 0:
        job_name = f"cooldown_notify_{user_id}_{int(cooldown_end_time.timestamp())}"
        context.job_queue.run_once(cooldown_notification_callback, when=delay, 
                                   chat_id=chat_id, user_id=user_id, name=job_name)
        user_data['cooldown_notification_job_id'] = job_name

async def start_command_internal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = load_data()
    user_data = get_user_data(user.id, data, user.name)
    if user_data.get('video_count',0) == 0: await check_and_grant_achievements(user_data, update, context)
    save_data(data)
    keyboard_layout = [
        [KeyboardButton(f"/addvideo Название Видео")],
        [KeyboardButton("/myprofile"), KeyboardButton("/shop")],
        [KeyboardButton("/leaderboard"), KeyboardButton("/achievements")],
        [KeyboardButton("/daily"), KeyboardButton("/help")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard_layout, resize_keyboard=True)
    await update.message.reply_text(
        f"🚀 Привет, {user.first_name}! Ты в игре {BOT_NAME}!\nИспользуй /help или кнопки.",
        reply_markup=reply_markup
    )

async def start_command_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await subscription_check_middleware(update, context, start_command_internal)

async def add_video_command_internal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not context.args:
        await update.message.reply_text("Укажи название: `/addvideo Название`", parse_mode=ParseMode.MARKDOWN); return
    video_title = ' '.join(context.args)
    data = load_data()
    user_data = get_user_data(user.id, data, user.name)
    last_used_dt = datetime.fromtimestamp(user_data.get('last_used_timestamp', 0.0))
    next_video_time = last_used_dt + timedelta(hours=COOLDOWN_HOURS)
    if datetime.now() < next_video_time:
        r = next_video_time - datetime.now(); h,s=divmod(r.seconds,3600);m,_=divmod(s,60)
        await update.message.reply_text(f"⏳ Кулдаун! Через {h} ч {m} мин."); return
    
    event_mod = 0; event_msgs = []
    ae = user_data.get('active_event')
    if ae:
        event_msgs.append(f"✨ *Активное событие*: {ae['message']}")
        if ae.get('target')=='next_video_popularity' and 'modifier' in ae: event_mod=ae['modifier']
        user_data['active_event'] = None
    
    pop_score = evaluate_video_popularity(video_title, base_popularity_modifier=event_mod)
    subs_chg = pop_score; bonus_subs = 0
    msg_parts = [f"🎬 {user_data['username']}, \"{video_title}\" опубликовано!"]
    if event_msgs: msg_parts.extend(event_msgs)

    if pop_score > POPULARITY_THRESHOLD_BONUS:
        bonus_subs = random.randint(BONUS_SUBSCRIBERS_MIN, BONUS_SUBSCRIBERS_MAX)
        subs_chg += bonus_subs; msg_parts.append(f"🌟 Супер! +{bonus_subs} бонус пдп.")
    elif pop_score < NEGATIVE_POPULARITY_THRESHOLD: msg_parts.append(f"📉 Не зашло...")
    elif pop_score < 0: msg_parts.append(f"😕 Не очень популярно.")
    else: msg_parts.append(f"👍 Неплохо!")
    
    user_data['subscribers'] = max(0, user_data.get('subscribers',0) + subs_chg)
    user_data['last_used_timestamp'] = datetime.now().timestamp()
    user_data['video_count'] = user_data.get('video_count', 0) + 1
    user_data['total_subs_from_videos'] = user_data.get('total_subs_from_videos',0)+subs_chg
    
    if subs_chg > 0: msg_parts.append(f"📈 +{subs_chg} пдп.")
    elif subs_chg < 0: msg_parts.append(f"📉 {subs_chg} пдп.")
    else: msg_parts.append(f"🤷 Пдп не изменились.")
    msg_parts.append(f"Итого: {user_data['subscribers']} пдп. (Видео: {user_data['video_count']})")

    if update.effective_chat:
        ce_time = datetime.fromtimestamp(user_data['last_used_timestamp']) + timedelta(hours=COOLDOWN_HOURS)
        schedule_cooldown_notification(user.id, update.effective_chat.id, ce_time, context, user_data)
    
    ne = get_random_event(user_data.get('subscribers',0))
    if ne: user_data['active_event'] = ne; msg_parts.append(f"\n🔔 *Событие!* {ne['message']}")
    
    ach_msgs = await check_and_grant_achievements(user_data, update, context)
    if ach_msgs: msg_parts.extend(ach_msgs)
    
    save_data(data)
    await update.message.reply_text("\n".join(msg_parts), parse_mode=ParseMode.MARKDOWN)

async def add_video_command_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await subscription_check_middleware(update, context, add_video_command_internal)

async def leaderboard_command_internal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    if not data: await update.message.reply_text(f"🏆 В {BOT_NAME} пусто..."); return
    sorted_users = sorted(data.values(), key=lambda u: u.get('subscribers', 0), reverse=True)
    msg = f"🏆 <b>Топ {BOT_NAME}еров:</b>\n\n"; disp_cnt = 0; max_disp = 15
    for info in sorted_users:
        if info.get('subscribers',0)<=0 and disp_cnt>=5: continue
        msg += f"{disp_cnt+1}. {info.get('username','N/A')} - {info.get('subscribers',0)} пдп. (в: {info.get('video_count',0)})\n"
        disp_cnt+=1
        if disp_cnt>=max_disp: break
    if disp_cnt == 0: await update.message.reply_text("🏆 Нет пользователей с пдп."); return
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def leaderboard_command_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await subscription_check_middleware(update, context, leaderboard_command_internal, False)

async def leaderboard_pic_command_internal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data_dict = load_data()
    if not data_dict: 
        if update.message: await update.message.reply_text("📊 Данных нет."); return
    
    fdata = {uid: u for uid, u in data_dict.items() if 'username' in u and 'subscribers' in u}
    if not fdata:
        if update.message: await update.message.reply_text("📊 Мало данных."); return

    df = pd.DataFrame.from_dict(fdata, orient='index')
    if 'subscribers' not in df.columns or df['subscribers'].isnull().all() or not pd.api.types.is_numeric_dtype(df['subscribers']):
        if update.message: await update.message.reply_text("📊 Проблема с данными пдп."); return
    
    valid_data = df[df['subscribers'] > 0].sort_values(by='subscribers', ascending=False)
    if valid_data.empty:
        if update.message: await update.message.reply_text("📊 Нет юзеров с пдп > 0."); return
    
    top_data = valid_data.head(15)
    unames = top_data['username'].values; scounts = top_data['subscribers'].values
    fig, ax = plt.subplots(figsize=(10,7),facecolor='white')
    w,t,at = ax.pie(scounts, autopct=lambda p:f'{p:.1f}%' if p>3 else '', startangle=140, colors=plt.cm.Paired(np.linspace(0,1,len(scounts))))
    plt.setp(at,size=8,weight="bold",color="white")
    ax.set_title(f"🏆 Топ {BOT_NAME}еров",fontsize=16,pad=20)
    ax.legend(w,[f"{n} ({c})" for n,c in zip(unames,scounts)],title="Топ:",loc="center left",bbox_to_anchor=(1,0,0.5,1),fontsize=9)
    plt.tight_layout(rect=[0,0,0.75,1])
    try:
        plt.savefig(LEADERBOARD_IMAGE_FILE,format='png',dpi=150)
        with open(LEADERBOARD_IMAGE_FILE,'rb') as pf:
            if update.effective_chat: await context.bot.send_photo(chat_id=update.effective_chat.id,photo=pf)
    except Exception as e:
        logger.error(f"Pic error: {e}")
        if update.message: await update.message.reply_text("Ошибка генерации картинки.")
    finally:
        if os.path.exists(LEADERBOARD_IMAGE_FILE):os.remove(LEADERBOARD_IMAGE_FILE)
        plt.close(fig)

async def leaderboard_pic_command_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await subscription_check_middleware(update, context, leaderboard_pic_command_internal, False)

async def my_profile_command_internal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; data = load_data(); ud = get_user_data(user.id, data, user.name)
    uname=ud.get('username',user.first_name); subs=ud.get('subscribers',0); vids=ud.get('video_count',0)
    curr=ud.get('currency',0); luts=ud.get('last_used_timestamp',0); tot_subs_v=ud.get('total_subs_from_videos',0)
    avg_subs = (tot_subs_v/vids) if vids>0 else 0
    
    pmsg = [f"👤 <b>Твой профиль, {uname}:</b>\n", f"👥 Пдп: {subs}", f"💰 {DEFAULT_CURRENCY_NAME}: {curr}", f"📹 Видео: {vids}"]
    if vids>0: pmsg.append(f"📈 Сред. пдп/видео: {avg_subs:.2f}")

    if luts==0: post_str="Публикуй первое: /addvideo <название>!"
    else:
        ludt=datetime.fromtimestamp(luts);pmsg.append(f"🕓 Посл. видео: {ludt.strftime('%y-%m-%d %H:%M')}")
        nvt=ludt+timedelta(hours=COOLDOWN_HOURS)
        if datetime.now()<nvt:rt=nvt-datetime.now();h,s=divmod(rt.seconds,3600);m,_=divmod(s,60);post_str=f"Сл. видео через: {h}ч {m}м."
        else:post_str="Можно публиковать новое!"
    pmsg.append(f"⏳ {post_str}")
    if ud.get('active_event'):pmsg.append(f"\n✨ <b>Активное событие:</b> {ud['active_event']['message']}")
    save_data(data)
    await update.message.reply_text("\n".join(pmsg), parse_mode=ParseMode.HTML)

async def my_profile_command_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await subscription_check_middleware(update, context, my_profile_command_internal, False)

async def achievements_command_internal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user=update.effective_user;data=load_data();ud=get_user_data(user.id,data,user.name)
    ulids=ud.get('achievements_unlocked',[])
    if not ulids: await update.message.reply_text("Пока нет достижений.");save_data(data);return
    msg="🏆 <b>Ваши достижения:</b>\n\n"
    for ach_id in ulids:
        if ach_id in achievements_definition:msg+=f"- {achievements_definition[ach_id]['name']}\n"
    msg+="\n🔍 <i>Неразблокированные:</i>\n";sp=0
    for ach_id,ach_def in achievements_definition.items():
        if ach_id not in ulids:msg+=f"- ❓ {ach_def['name']} (Скрыто)\n";sp+=1;
        if sp>=3:break
    save_data(data);await update.message.reply_text(msg,parse_mode=ParseMode.HTML)

async def achievements_command_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await subscription_check_middleware(update, context, achievements_command_internal, False)

async def daily_bonus_command_internal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user=update.effective_user;data=load_data();ud=get_user_data(user.id,data,user.name)
    today_s=date.today().isoformat();lbds=ud.get('last_daily_bonus_date')
    if lbds==today_s:await update.message.reply_text("Уже получили бонус. Завтра!");save_data(data);return
    cs=ud.get('daily_bonus_streak',0)
    if lbds:lbd=date.fromisoformat(lbds);cs=(cs+1) if (date.today()-lbd).days==1 else 1
    else:cs=1
    bonus=int(DAILY_BONUS_AMOUNT*(DAILY_BONUS_STREAK_MULTIPLIER**(cs-1)))
    ud['currency']=ud.get('currency',0)+bonus;ud['last_daily_bonus_date']=today_s;ud['daily_bonus_streak']=cs
    ach_msgs=await check_and_grant_achievements(ud,update,context);save_data(data)
    msg_txt=(f"🎁 Ежедневный бонус: +{bonus} {DEFAULT_CURRENCY_NAME}!\n🔥 Ваш стрик: {cs} дн.")
    if ach_msgs:msg_txt+="\n"+"\n".join(ach_msgs).replace("<b>","*").replace("</b>","*")
    await update.message.reply_text(msg_txt,parse_mode=ParseMode.MARKDOWN)

async def daily_bonus_command_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await subscription_check_middleware(update, context, daily_bonus_command_internal)

async def shop_command_internal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user=update.effective_user;data=load_data();ud=get_user_data(user.id,data,user.name);save_data(data)
    bal=ud.get('currency',0);msg=f"🛍️ <b>Магазин {BOT_NAME}</b>\nБаланс: {bal} {DEFAULT_CURRENCY_NAME}\n\n"
    btns=[]
    if not shop_items:msg+="В магазине пусто."
    else:
        for item_id,item_def in shop_items.items():
            msg+=f"🔹 <b>{item_def['name']}</b> - {item_def['price']} {DEFAULT_CURRENCY_NAME}\n   <i>{item_def['description']}</i>\n\n"
            btns.append([InlineKeyboardButton(f"Купить \"{item_def['name'][:20]}...\" ({item_def['price']})",callback_data=f"shop_buy_{item_id}")])
    reply_markup=InlineKeyboardMarkup(btns) if btns else None
    await update.message.reply_text(msg,parse_mode=ParseMode.HTML,reply_markup=reply_markup)

async def shop_command_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await subscription_check_middleware(update, context, shop_command_internal)

async def shop_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query;await query.answer()
    parts=query.data.split('_');
    if len(parts)<3 or parts[0]!="shop" or parts[1]!="buy":await query.edit_message_text("Ошибка формата.");return
    item_id=parts[2];user=query.effective_user;data=load_data();ud=get_user_data(user.id,data,user.name)
    if item_id not in shop_items:await query.edit_message_text("Товар не найден.");save_data(data);return
    item_def=shop_items[item_id];price=item_def['price'];user_curr=ud.get('currency',0)
    if user_curr<price:await query.edit_message_text(f"Мало средств! Нужно {price}, у вас {user_curr}.");save_data(data);return
    ud['currency']-=price;effect=item_def['effect'];app_msg=f"✅ Куплено \"{item_def['name']}\" за {price} {DEFAULT_CURRENCY_NAME}.\n"
    if effect['type']=='event_modifier' and effect['target']=='next_video_popularity':
        ud['active_event']={"type":"event_modifier","modifier":effect['modifier'],"target":"next_video_popularity","message":f"Использован \"{item_def['name']}\" ({effect['modifier']:+})"}
        app_msg+=f"Эффект к следующему видео."
    elif effect['type']=='cooldown_reset':
        ud['last_used_timestamp']=0.0;app_msg+=f"Кулдаун сброшен!"
        if ud.get('cooldown_notification_job_id') and context.job_queue:
            cj=context.job_queue.get_jobs_by_name(ud['cooldown_notification_job_id'])
            for job in cj:job.schedule_removal()
            ud['cooldown_notification_job_id']=None
    await query.edit_message_text(app_msg)
    await check_and_grant_achievements(ud,update,context);save_data(data)

async def help_command_internal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ht=(f"🌟 <b>{BOT_NAME}!</b> 🌟\n\n"
        "Публикуй видео, копи {currency}!\n\n"
        "<b>Команды:</b>\n🎬 `/addvideo`\n🏆 `/leaderboard`, `/lp`\n👤 `/myprofile`\n"
        "🛍️ `/shop`\n🎁 `/daily`\n🏅 `/achievements`\n🆘 `/help`\n\n"
        "<b>Механика:</b> Публикация раз в {cooldown:.1f} ч. Популярность от слов/удачи. "
        "Есть события!").format(cooldown=COOLDOWN_HOURS,bot_name=BOT_NAME,currency=DEFAULT_CURRENCY_NAME)
    await update.message.reply_text(ht,parse_mode=ParseMode.HTML)

async def help_command_wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await subscription_check_middleware(update, context, help_command_internal, False)

async def admin_check(update: Update) -> bool:
    if update.effective_user.id != CREATOR_ID:
        if update.message: await update.message.reply_text("⛔ Только для админа."); return False
    return True

async def admin_find_user(target_identifier: str, data: Dict[int, Any]) -> Optional[int]:
    if target_identifier.startswith('@'):
        username_to_find = target_identifier[1:].lower()
        for uid, uinfo in data.items():
            uname_db = uinfo.get('username','').lower()
            if uname_db == username_to_find or (uname_db.startswith('@') and uname_db[1:] == username_to_find):
                return uid
    else:
        try: return int(target_identifier)
        except ValueError: pass
    return None

async def admin_add_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_check(update): return
    if len(context.args)<2:await update.message.reply_text(f"Исп: /CHEATaddcoins <id/@usr> <кол-во>");return
    target_id=context.args[0];
    try:amount=int(context.args[1])
    except ValueError:await update.message.reply_text("Кол-во - число.");return
    data=load_data();found_uid=await admin_find_user(target_id,data)
    if found_uid is None or found_uid not in data:await update.message.reply_text(f"Юзер {target_id} не найден.");return
    ud=data[found_uid];ud['currency']=ud.get('currency',0)+amount;ud['currency']=max(0,ud['currency']);save_data(data)
    await update.message.reply_text(f"Юзеру {ud['username']} изменены {DEFAULT_CURRENCY_NAME} на {amount}. Баланс: {ud['currency']}.")

async def admin_give_achievement(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_check(update):return
    if len(context.args)<2:await update.message.reply_text("Исп: /CHEATgiveach <id/@usr> <ach_id>");return
    target_id=context.args[0];ach_id=context.args[1]
    if ach_id not in achievements_definition:await update.message.reply_text(f"Ачивка '{ach_id}' не найдена.");return
    data=load_data();found_uid=await admin_find_user(target_id,data)
    if found_uid is None or found_uid not in data:await update.message.reply_text(f"Юзер {target_id} не найден.");return
    ud=data[found_uid]
    if ach_id not in ud.get('achievements_unlocked',[]):
        ud.setdefault('achievements_unlocked',[]).append(ach_id)
        rc=achievements_definition[ach_id].get("reward_coins",0);ud['currency']=ud.get('currency',0)+rc;save_data(data)
        await update.message.reply_text(f"Юзеру {ud['username']} выдана {achievements_definition[ach_id]['name']} (+{rc} {DEFAULT_CURRENCY_NAME}).")
    else:await update.message.reply_text(f"У {ud['username']} уже есть эта ачивка.")

async def admin_cheat_add_subscribers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_check(update):return
    if len(context.args)<2:await update.message.reply_text("Исп: /CHEATaddsub <id/@usr> <кол-во>");return
    target_id=context.args[0];
    try:amount=int(context.args[1])
    except ValueError:await update.message.reply_text("Кол-во - число.");return
    data=load_data();found_uid=await admin_find_user(target_id,data)
    if found_uid is None or found_uid not in data:await update.message.reply_text(f"Юзер {target_id} не найден.");return
    ud=data[found_uid];ud['subscribers']=ud.get('subscribers',0)+amount;ud['subscribers']=max(0,ud['subscribers']);save_data(data)
    await update.message.reply_text(f"Юзеру {ud['username']} изменены пдп на {amount}. Баланс: {ud['subscribers']}.")

async def admin_delete_database(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_check(update):return
    if os.path.exists(DATABASE_FILE):
        try:os.remove(DATABASE_FILE);await update.message.reply_text(f"'{DATABASE_FILE}' удален.")
        except Exception as e:await update.message.reply_text(f"Ошибка удаления: {e}")
    else:await update.message.reply_text(f"'{DATABASE_FILE}' уже удален/нет.")

async def admin_bot_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_check(update):return
    data=load_data();tu=len(data);ts=sum(i.get('subscribers',0) for i in data.values())
    tv=sum(i.get('video_count',0) for i in data.values());tc=sum(i.get('currency',0) for i in data.values())
    stxt=(f"📊 <b>Стата {BOT_NAME}:</b>\n\n👥 Юзеров: {tu}\n▶️ Видео: {tv}\n"
          f"📈 Сумма пдп: {ts}\n💰 Сумма валюты: {tc} {DEFAULT_CURRENCY_NAME}\n")
    await update.message.reply_text(stxt,parse_mode=ParseMode.HTML)

async def post_init(application: Application) -> None:
    com_cmds = [
        BotCommand("start","🚀"), BotCommand("addvideo","🎬"), BotCommand("myprofile","👤"),
        BotCommand("shop","🛍️"), BotCommand("daily","🎁"), BotCommand("achievements","🏅"),
        BotCommand("leaderboard","🏆"), BotCommand("leaderboardpic","📊"), BotCommand("help","❓")
    ]
    adm_cmds = [
        BotCommand("CHEATaddsub","💰+/-пдп"), BotCommand("CHEATaddcoins",f"🪙+/-{DEFAULT_CURRENCY_NAME[:4]}."),
        BotCommand("CHEATgiveach","🎖️ДатьАчив"), BotCommand("CHEATDeleteDatabase","🗑️СтеретьБД"),
        BotCommand("botstats","📈Стата")
    ]
    await application.bot.set_my_commands(com_cmds)
    if CREATOR_ID:
        try: await application.bot.set_my_commands(com_cmds+adm_cmds,scope=BotCommandScopeChat(chat_id=CREATOR_ID))
        except Exception as e: logger.error(f"Set admin cmds error: {e}")
    if not BOT_TOKEN: logger.critical("BOT_TOKEN MISSING!")

def main() -> None:
    if not BOT_TOKEN: print("Error: BOT_TOKEN not found."); return
    application = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    if not application.job_queue: logger.warning("JobQueue not found in application.")
    
    cmd_handlers = [
        CommandHandler("start",start_command_wrapper),CommandHandler("help",help_command_wrapper),
        CommandHandler("myprofile",my_profile_command_wrapper),CommandHandler("leaderboard",leaderboard_command_wrapper),
        CommandHandler("lp",leaderboard_command_wrapper), # Alias for leaderboard
        CommandHandler("leaderboardpic",leaderboard_pic_command_wrapper),
        CommandHandler("lppic",leaderboard_pic_command_wrapper), # Alias for leaderboardpic
        CommandHandler("achievements",achievements_command_wrapper),CommandHandler("daily",daily_bonus_command_wrapper),
        CommandHandler("shop",shop_command_wrapper),CommandHandler("CHEATaddsub",admin_cheat_add_subscribers),
        CommandHandler("CHEATaddcoins",admin_add_currency),CommandHandler("CHEATgiveach",admin_give_achievement),
        CommandHandler("CHEATDeleteDatabase",admin_delete_database),CommandHandler("botstats",admin_bot_stats),
    ]
    application.add_handlers(cmd_handlers)
    application.add_handler(CallbackQueryHandler(shop_callback_handler,pattern=r"^shop_buy_"))
    video_aliases = ["addvideo","video","add","newvideo","publishvideo","new","publish"]
    for alias in video_aliases: application.add_handler(CommandHandler(alias,add_video_command_wrapper))
    
    logger.info(f"Bot {BOT_NAME} (log: {LOG_LEVEL_STR}) starting...")
    application.run_polling()

if __name__ == '__main__':
    if not os.path.exists(DATABASE_FILE):
        with open(DATABASE_FILE,'w',encoding='utf-8') as f:json.dump({},f)
        logger.info(f"Created DB file: {DATABASE_FILE}")
    if not os.path.exists(KEYWORDS_FILE):
        with open(KEYWORDS_FILE,'w',encoding='utf-8') as f:f.write("популярное\nхайп\n")
        logger.info(f"Created keywords file: {KEYWORDS_FILE}")
    main()