import logging
import random
from typing import Dict, Any
from datetime import datetime, timedelta, date
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from aiogram import Bot, types
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile
)
# Note: Command filter isn't needed inside handlers, it's used in `main.py` to register handlers

from .config import BOT_NAME, COOLDOWN_HOURS, POPULARITY_THRESHOLD_BONUS, NEGATIVE_POPULARITY_THRESHOLD, DEFAULT_CURRENCY_NAME, LEADERBOARD_IMAGE_FILE, CREATOR_ID, shop_items, DAILY_BONUS_AMOUNT, DAILY_BONUS_STREAK_MULTIPLIER, DATABASE_FILE
from .db import load_data, save_data_async, get_user_data, schedule_cooldown_notification, _inmemory_tasks
from .utils import evaluate_video_popularity, get_random_event, escape_html
from .achievements import check_and_grant_achievements
from .config import BOT_TOKEN

logger = logging.getLogger(__name__)


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
    await message.answer(f"🚀 Привет, {escape_html(message.from_user.first_name or '')}! Ты в игре <b>{escape_html(BOT_NAME)}</b>!\nИспользуй /help или кнопки.", reply_markup=kb, parse_mode="HTML")


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
    msg_parts = [f"🎬 <b>{escape_html(ud.get('username',''))}</b>, «<b>{escape_html(video_title)}</b>» опубликовано!"]
    if msgs:
        msg_parts.extend(msgs)

    if pop_score > POPULARITY_THRESHOLD_BONUS:
        bonus_subs = random.randint(1, 3)
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
        if new_ev['type'] == 'currency_bonus':
            bonus_amount = new_ev['amount']
            ud['currency'] = ud.get('currency', 0) + bonus_amount
            msg_parts.append(f"\n🔔 Событие: {escape_html(new_ev['message'])}")
        elif new_ev['type'] == 'cooldown_reduction':
            reduction_hours = new_ev['hours']
            current_cooldown = ud.get('last_used_timestamp', 0.0)
            if current_cooldown > 0:
                new_cooldown = current_cooldown - (reduction_hours * 3600)
                ud['last_used_timestamp'] = max(0, new_cooldown)
            msg_parts.append(f"\n🔔 Событие: {new_ev['message']}")
        else:
            ud['active_event'] = new_ev
            msg_parts.append(f"\n🔔 Событие: {new_ev['message']}")

    ach_msgs = await check_and_grant_achievements(ud, bot, message.chat.id)
    if ach_msgs:
        # achievements messages already may contain HTML formatting, extend as-is
        msg_parts.extend(ach_msgs)

    await save_data_async(data)
    await message.answer("\n".join(msg_parts), parse_mode="HTML")


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
        msg += f"{shown+1}. {escape_html(u.get('username','N/A'))} - {escape_html(u.get('subscribers',0))} пдп. (видео: {escape_html(u.get('video_count',0))})\n"
        shown += 1
    await message.answer(msg, parse_mode="HTML")


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
    ax.set_title(f"Топ {BOT_NAME}еров")
    plt.tight_layout(rect=[0, 0, 0.75, 1])
    try:
        plt.savefig(LEADERBOARD_IMAGE_FILE, dpi=150, bbox_inches='tight')
        plt.close(fig)
        await message.answer_photo(photo=FSInputFile(LEADERBOARD_IMAGE_FILE))
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
    out = [f"👤 <b>Твой профиль, {escape_html(uname)}:</b>",
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
        out.append(f"\n✨ <b>Активное событие:</b> {escape_html(ud['active_event']['message'])}")
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
    from .achievements import achievements_definition
    for aid in unlocked:
        if aid in achievements_definition:
            txt += f"- {escape_html(achievements_definition[aid]['name'])}\n"
    txt += "\n🔍 <i>Неразблокированные (первые 3):</i>\n"
    cnt = 0
    # find first 3 locked
    from .achievements import achievements_definition
    for aid, ad in achievements_definition.items():
        if aid not in unlocked:
            txt += f"- ❓ {escape_html(ad['name'])}\n"
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
    await message.answer(res, parse_mode="HTML")


async def cmd_shop(message: types.Message, bot: Bot, **kwargs):
    data = load_data()
    ud = get_user_data(message.from_user.id, data, message.from_user.username or message.from_user.first_name)
    bal = ud.get('currency', 0)
    txt = f"🛍️ <b>Магазин {escape_html(BOT_NAME)}</b>\nБаланс: {escape_html(bal)} {escape_html(DEFAULT_CURRENCY_NAME)}\n\n"
    kb_rows = []
    from .config import shop_items
    for item_id, item in shop_items.items():
        txt += f"🔹 <b>{escape_html(item['name'])}</b> - {escape_html(item['price'])} {escape_html(DEFAULT_CURRENCY_NAME)}\n   <i>{escape_html(item['description'])}</i>\n\n"
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
    from .config import shop_items
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
    app_msg = f"✅ Куплено «{escape_html(item['name'])}» за {escape_html(price)} {escape_html(DEFAULT_CURRENCY_NAME)}.\n"
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
    await query.message.edit_text(app_msg, parse_mode="HTML")


async def cmd_help(message: types.Message, bot: Bot, **kwargs):
    text = (
        f"🌟 <b>{escape_html(BOT_NAME)}!</b>\n\n"
        "Публикуй видео, копи валюту и прокачивайся!\n\n"
        "<b>Команды:</b>\n"
        f"🎬 <code>/addvideo {escape_html('<название>')}</code>\n"
        f"🏆 <code>/leaderboard</code>  <code>/leaderboardpic</code>\n"
        f"👤 <code>/myprofile</code>\n"
        f"🛍️ <code>/shop</code>\n"
        f"🎁 <code>/daily</code>\n"
        f"🏅 <code>/achievements</code>\n"
        f"❓ <code>/help</code>\n\n"
        f"Механика: публикация раз в {COOLDOWN_HOURS:.1f} ч. Популярность зависит от заголовка, слов-ключей и удачи. Есть события и магазин.\n\n"
    )
    await message.answer(text, parse_mode="HTML")


# Admin commands
async def admin_check_and_get(message: types.Message) -> bool:
    if message.from_user.id != CREATOR_ID:
        await message.answer("⛔ Только для админа.")
        return False
    return True

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
    txt = (f"📊 <b>Стата {escape_html(BOT_NAME)}:</b>\n\n"
           f"👥 Юзеров: {tu}\n▶️ Видео: {tv}\n📈 Сумма пдп: {ts}\n💰 Сумма валюты: {tc} {DEFAULT_CURRENCY_NAME}")
    await message.answer(txt, parse_mode="HTML")
