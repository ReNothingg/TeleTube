import os
from dotenv import load_dotenv
from datetime import datetime

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

shop_items = {
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

# Basic logger config left to main entrypoint if needed
