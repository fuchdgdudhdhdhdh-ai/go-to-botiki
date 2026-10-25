import asyncio
import logging
import os
import re
from pathlib import Path

from aiohttp import web
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession, MemorySession
from telethon.errors import SessionPasswordNeededError

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ---------- ENV ----------
API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["TG_ADMIN_ID"])
PORT = int(os.environ.get("PORT", 8080))

SESSION_DIR = Path(os.environ.get("SESSION_DIR", "/data"))
SESSION_DIR.mkdir(parents=True, exist_ok=True)
SESSION_FILE = SESSION_DIR / "userbot_session.txt"

# ---------- Глобальное состояние ----------
bot_client: TelegramClient | None = None
user_client: TelegramClient | None = None

admin_state = "menu"
pending_phone = None
pending_code_hash = None
entered_code = ""

settings = {
    "chat_id_1": None, "thread_id_1": None,
    "chat_id_2": None, "thread_id_2": None,
    "message": None, "interval": 5, "pause": 30,
}
mailing_task: asyncio.Task | None = None


# ---------- Утилиты ----------
def extract_chat_and_thread(link: str):
    m = re.search(r"https?://t\.me/c/(\d+)/(?:\d+/)?(\d+)", link.strip())
    if not m:
        return None, None
    return int(f"-100{m.group(1)}"), int(m.group(2))


async def is_authorized() -> bool:
    if user_client is None or not user_client.is_connected():
        return False
    try:
        return await user_client.is_user_authorized()
    except Exception:
        return False


def main_menu():
    return [
        [Button.inline("📌 Тема 1", b"set_topic_1"), Button.inline("📌 Тема 2", b"set_topic_2")],
        [Button.inline("✏️ Сообщение", b"set_message")],
        [Button.inline("⏱ Интервал", b"set_interval"), Button.inline("⏸ Пауза", b"set_pause")],
        [Button.inline("▶️ Запустить", b"start_mailing"), Button.inline("⏹ Остановить", b"stop_mailing")],
        [Button.inline("📊 Настройки", b"show_settings")],
    ]


def code_keyboard():
    return [
        [Button.inline("1", b"code:1"), Button.inline("2", b"code:2"), Button.inline("3", b"code:3")],
        [Button.inline("4", b"code:4"), Button.inline("5", b"code:5"), Button.inline("6", b"code:6")],
        [Button.inline("7", b"code:7"), Button.inline("8", b"code:8"), Button.inline("9", b"code:9")],
        [Button.inline("⌫", b"code:del"), Button.inline("0", b"code:0"), Button.inline("✅", b"code:submit")],
        [Button.inline("❌ Отмена", b"code:cancel")],
    ]


async def settings_text():
    auth = "✅ авторизован" if await is_authorized() else "❌ не авторизован"
    running = mailing_task and not mailing_task.done()
    return (
        "📊 **Состояние**\n\n"
        f"Аккаунт: {auth}\n"
        f"Тема 1: `{settings['chat_id_1']}:{settings['thread_id_1']}`\n"
        f"Тема 2: `{settings['chat_id_2']}:{settings['thread_id_2']}`\n"
        f"Сообщение: _{settings['message'] or 'не задано'}_\n"
        f"Интервал: {settings['interval']} сек.\n"
        f"Пауза: {settings['pause']} сек.\n"
        f"Рассылка: {'▶️ запущена' if running else '⏹ остановлена'}"
    )


# ---------- Рассылка ----------
async def mailing_loop():
    while True:
        try:
            await user_client.send_message(
                settings["chat_id_1"], settings["message"], reply_to=settings["thread_id_1"]
            )
            logger.info("Sent to topic 1")
            await asyncio.sleep(settings["interval"])
            await user_client.send_message(
                settings["chat_id_2"], settings["message"], reply_to=settings["thread_id_2"]
            )
            logger.info("Sent to topic 2")
            await asyncio.sleep(settings["interval"])
            logger.info("Cycle pause %s", settings["pause"])
            await asyncio.sleep(settings["pause"])
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("mailing error: %s", e)
            await asyncio.sleep(10)


# ---------- Логин ----------
async def start_login(chat):
    global admin_state
    admin_state = "wait_phone"
    await chat.send_message(
        "🔐 **Авторизация аккаунта**\n\n"
        "Отправьте номер телефона в формате `+79991234567`:"
    )


async def handle_phone(chat, phone):
    global admin_state, pending_phone, pending_code_hash, entered_code
    phone = phone.strip().replace(" ", "")
    try:
        if not user_client.is_connected():
            await user_client.connect()
        sent = await user_client.send_code_request(phone)
        pending_phone = phone
        pending_code_hash = sent.phone_code_hash
        entered_code = ""
        admin_state = "wait_code"
        await chat.send_message(
            "📲 Введите код из Telegram (нажимайте кнопки):\n\n**—**",
            buttons=code_keyboard(),
        )
    except Exception as e:
        logger.exception("send_code_request error")
        admin_state = "menu"
        await chat.send_message(f"❌ Ошибка отправки кода: `{e}`", buttons=main_menu())


async def handle_code_submit(event):
    global admin_state, entered_code
    code = entered_code
    entered_code = ""
    try:
        await user_client.sign_in(pending_phone, code=code, phone_code_hash=pending_code_hash)
        SESSION_FILE.write_text(user_client.session.save())
        me = await user_client.get_me()
        admin_state = "menu"
        await event.edit(
            f"✅ Вход выполнен: **{me.first_name}** (@{me.username or me.id})",
            buttons=main_menu(),
        )
    except SessionPasswordNeededError:
        admin_state = "wait_2fa"
        await event.edit("🔐 Введите пароль двухфакторной аутентификации (отправьте сообщением):")
    except Exception as e:
        logger.exception("sign_in error")
        admin_state = "wait_code"
        await event.edit(f"❌ Ошибка: `{e}`\n\nПопробуйте снова:", buttons=code_keyboard())


async def handle_2fa(event, password):
    global admin_state
    try:
        await user_client.sign_in(password=password)
        SESSION_FILE.write_text(user_client.session.save())
        me = await user_client.get_me()
        admin_state = "menu"
        try:
            await event.delete()
        except Exception:
            pass
        await event.respond(
            f"✅ Вход выполнен: **{me.first_name}** (@{me.username or me.id})",
            buttons=main_menu(),
        )
    except Exception as e:
        logger.exception("2fa error")
        try:
            await event.delete()
        except Exception:
            pass
        await event.respond(f"❌ Ошибка 2FA: `{e}`\n\nОтправьте пароль ещё раз:")


# ---------- Коллбэки (кнопки) ----------
async def cb_handler(event):
    global admin_state, entered_code, mailing_task
    try:
        data = event.data.decode() if isinstance(event.data, bytes) else event.data
    except Exception:
        data = str(event.data)

    await event.answer()

    if admin_state == "wait_code" and data.startswith("code:"):
        action = data.split(":", 1)[1]
        if action == "cancel":
            admin_state = "menu"
            entered_code = ""
            await event.edit("Логин отменён.", buttons=main_menu())
            return
        if action == "del":
            entered_code = entered_code[:-1]
        elif action == "submit":
            await handle_code_submit(event)
            return
        else:
            if len(entered_code) < 6:
                entered_code += action

        display = " ".join(entered_code) if entered_code else "—"
        await event.edit(
            f"📲 Введите код из Telegram (нажимайте кнопки):\n\n**{display}**",
            buttons=code_keyboard(),
        )
        return

    if data == "show_settings":
        await event.edit(await settings_text(), buttons=main_menu())
        return

    if data == "start_mailing":
        if not await is_authorized():
            await event.edit("❌ Сначала авторизуйтесь. Отправьте /start", buttons=main_menu())
            return
        if not all([settings["chat_id_1"], settings["chat_id_2"], settings["message"]]):
            await event.edit("❌ Сначала задайте обе темы и сообщение.", buttons=main_menu())
            return
        if mailing_task and not mailing_task.done():
            mailing_task.cancel()
        mailing_task = asyncio.create_task(mailing_loop())
        await event.edit("▶️ **Рассылка запущена.**", buttons=main_menu())
        return

    if data == "stop_mailing":
        if mailing_task and not mailing_task.done():
            mailing_task.cancel()
            mailing_task = None
            await event.edit("⏹ **Рассылка остановлена.**", buttons=main_menu())
        else:
            await event.edit("ℹ️ Рассылка не запущена.", buttons=main_menu())
        return

    prompts = {
        "set_topic_1": ("Отправьте ссылку на **первую тему**.\nПример: `https://t.me/c/123456789/45/67`", "set_topic_1"),
        "set_topic_2": ("Отправьте ссылку на **вторую тему**.", "set_topic_2"),
        "set_message": ("Введите текст сообщения:", "set_message"),
        "set_interval": ("Введите интервал между отправками (сек):", "set_interval"),
        "set_pause": ("Введите паузу между циклами (сек):", "set_pause"),
    }
    if data in prompts:
        text, state = prompts[data]
        admin_state = state
        await event.edit(text)


# ---------- Текстовые сообщения ----------
async def text_handler(event):
    global admin_state, mailing_task
    text = event.text.strip()

    if text == "/start":
        if await is_authorized():
            admin_state = "menu"
            me = await user_client.get_me()
            await event.respond(
                f"👋 Юзербот готов. Аккаунт: **{me.first_name}**",
                buttons=main_menu(),
            )
        else:
            await start_login(event.chat)
        return

    if text == "/cancel":
        admin_state = "menu"
        await event.respond("Отменено.", buttons=main_menu())
        return

    if admin_state == "wait_phone":
        await handle_phone(event.chat, text)
        return

    if admin_state == "wait_2fa":
        await handle_2fa(event, text)
        return

    if admin_state == "set_topic_1":
        chat_id, thread_id = extract_chat_and_thread(text)
        if chat_id is None:
            await event.respond("❌ Не разобрал ссылку. Пример: `https://t.me/c/123456789/45/67`")
            return
        settings["chat_id_1"], settings["thread_id_1"] = chat_id, thread_id
        admin_state = "menu"
        await event.respond(f"✅ Тема 1: `{chat_id}:{thread_id}`", buttons=main_menu())
        return

    if admin_state == "set_topic_2":
        chat_id, thread_id = extract_chat_and_thread(text)
        if chat_id is None:
            await event.respond("❌ Не разобрал ссылку.")
            return
        settings["chat_id_2"], settings["thread_id_2"] = chat_id, thread_id
        admin_state = "menu"
        await event.respond(f"✅ Тема 2: `{chat_id}:{thread_id}`", buttons=main_menu())
        return

    if admin_state == "set_message":
        if len(text) > 4096:
            await event.respond("❌ Слишком длинное сообщение (макс. 4096).")
            return
        settings["message"] = text
        admin_state = "menu"
        await event.respond("✅ Сообщение сохранено.", buttons=main_menu())
        return

    if admin_state in ("set_interval", "set_pause"):
        try:
            v = int(text)
            if v < 1:
                raise ValueError
        except ValueError:
            await event.respond("❌ Введите целое число > 0.")
            return
        key = "interval" if admin_state == "set_interval" else "pause"
        settings[key] = v
        admin_state = "menu"
        await event.respond(f"✅ {key.capitalize()}: {v} сек.", buttons=main_menu())
        return

    await event.respond("Не понимаю. Отправьте /start", buttons=main_menu())


# ---------- HTTP-сервер (для Render Web Service) ----------
async def http_root(request):
    return web.Response(
        text="✅ Telegram userbot is running.\n",
        content_type="text/plain",
    )


async def http_health(request):
    auth = await is_authorized()
    running = bool(mailing_task and not mailing_task.done())
    return web.json_response(
        {
            "status": "ok",
            "userbot_authorized": auth,
            "mailing_running": running,
            "settings": {
                "chat_id_1": settings["chat_id_1"],
                "thread_id_1": settings["thread_id_1"],
                "chat_id_2": settings["chat_id_2"],
                "thread_id_2": settings["thread_id_2"],
                "interval": settings["interval"],
                "pause": settings["pause"],
            },
        }
    )


async def run_http_server():
    app = web.Application()
    app.router.add_get("/", http_root)
    app.router.add_get("/health", http_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info("HTTP server listening on 0.0.0.0:%s", PORT)
    # Висим вечно
    await asyncio.Event().wait()


# ---------- Main ----------
async def main():
    global user_client, bot_client

    session_str = SESSION_FILE.read_text().strip() if SESSION_FILE.exists() else ""

    user_client = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    await user_client.connect()

    if session_str and await user_client.is_user_authorized():
        me = await user_client.get_me()
        logger.info("Authorized as %s (@%s)", me.first_name, me.username or me.id)
    else:
        if session_str:
            logger.warning("Session invalid, recreating client")
            await user_client.disconnect()
            user_client = TelegramClient(StringSession(), API_ID, API_HASH)
            await user_client.connect()
        logger.info("Not authorized, waiting for admin login")

    bot_client = TelegramClient(MemorySession(), API_ID, API_HASH)
    await bot_client.start(bot_token=BOT_TOKEN)
    logger.info("Admin bot started")

    bot_client.add_event_handler(
        text_handler,
        events.NewMessage(from_users=ADMIN_ID, incoming=True, func=lambda e: e.is_private),
    )
    bot_client.add_event_handler(cb_handler, events.CallbackQuery(from_users=ADMIN_ID))

    # Поднимаем HTTP-сервер и бот одновременно
    http_task = asyncio.create_task(run_http_server())
    try:
        await bot_client.run_until_disconnected()
    finally:
        http_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
