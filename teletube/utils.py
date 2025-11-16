import os
import random
from typing import Dict, Any, Optional, List
from .config import (
    KEYWORDS_FILE, KEYWORD_BONUS_POINTS,
    POPULARITY_RANDOM_MIN, POPULARITY_RANDOM_MAX,
    BONUS_SUBSCRIBERS_MIN, BONUS_SUBSCRIBERS_MAX,
    POPULARITY_THRESHOLD_BONUS, NEGATIVE_POPULARITY_THRESHOLD
    , DEFAULT_CURRENCY_NAME
)


def load_keywords(filename: str = KEYWORDS_FILE) -> List[str]:
    if not os.path.exists(filename):
        with open(filename, 'w', encoding='utf-8') as f:
            f.write("популярное\nхайп\n")
        return ["популярное", "хайп"]
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return [ln.strip().lower() for ln in f if ln.strip() and not ln.startswith('#')]
    except Exception:
        return []


def evaluate_video_popularity(video_title: str, base_popularity_modifier: int = 0, user_subs: int = 0) -> int:
    title = video_title.strip().lower()
    keywords = load_keywords()

    keyword_bonus = sum(KEYWORD_BONUS_POINTS for k in keywords if k in title)

    words = len(title.split())
    length_bonus = min(5, words // 2)

    title_quality = 0
    if any(word in title for word in ['новый', 'лучший', 'топ', 'обзор', 'туториал', 'гайд']):
        title_quality += 3
    if any(word in title for word in ['2024', '2025', 'новинка', 'эксклюзив']):
        title_quality += 2
    if len(title) > 20:
        title_quality += 1

    volatility = 1.0 + max(0, 20 - min(user_subs, 200)) / 40.0

    base_score = keyword_bonus + length_bonus + title_quality + base_popularity_modifier

    rand_factor = random.randint(POPULARITY_RANDOM_MIN, POPULARITY_RANDOM_MAX)

    raw_score = base_score + rand_factor

    adjusted_score = int(round(raw_score * volatility))

    final_score = max(-30, min(100, adjusted_score))

    return final_score


def get_random_event(user_subscribers: int) -> Optional[Dict[str, Any]]:
    r = random.random()

    if r < 0.05 and user_subscribers >= 10:
        bonus = random.randint(25, 75)
        return {"type": "event_modifier", "modifier": bonus, "target": "next_video_popularity",
                "message": f"🎉 Вирусный взрыв! +{bonus} к популярности следующего видео!"}

    if 0.05 <= r < 0.15:
        bonus = random.randint(5, 15)
        return {"type": "event_modifier", "modifier": bonus, "target": "next_video_popularity",
                "message": f"✨ Местный хайп: +{bonus} к следующему видео."}

    if 0.15 <= r < 0.20 and user_subscribers > 30:
        malus = random.randint(3, 8)
        return {"type": "event_modifier", "modifier": -malus, "target": "next_video_popularity",
                "message": f"📉 Технические проблемы: -{malus} к следующему видео."}

    if 0.20 <= r < 0.25 and user_subscribers >= 50:
        return {"type": "currency_bonus", "amount": random.randint(10, 30),
                "message": f"💰 Бонус за активность: +{random.randint(10, 30)} {DEFAULT_CURRENCY_NAME}!"}

    if 0.25 <= r < 0.30 and user_subscribers >= 100:
        return {"type": "cooldown_reduction", "hours": random.randint(1, 3),
                "message": f"⚡ Ускорение: кулдаун уменьшен на {random.randint(1, 3)} часа!"}

    return None
