from typing import Dict, Any, List
from .config import DEFAULT_CURRENCY_NAME
from .utils import escape_html
import logging
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


async def check_and_grant_achievements(user_data: Dict[str, Any], bot, chat_id: int) -> List[str]:
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
            text = f"🏆 Новое достижение: <b>{escape_html(adef['name'])}</b>! (+{rc} {escape_html(DEFAULT_CURRENCY_NAME)})"
            newly.append(text)
            try:
                await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
            except Exception as e:
                logger.error("notify achievement error: %s", e)
    return newly
