# Telegram Userbot (Web Service на Render)

## Переменные окружения
| Переменная | Что это |
|---|---|
| `TG_API_ID` | API ID с https://my.telegram.org |
| `TG_API_HASH` | API Hash с https://my.telegram.org |
| `BOT_TOKEN` | Токен бота-админки от @BotFather |
| `TG_ADMIN_ID` | Твой user_id (узнать у @userinfobot) |
| `SESSION_DIR` | Папка для сессии (например `/data`) |
| `PORT` | Render ставит сам |

## Деплой
1. Закинь файлы на GitHub.
2. Render → **New → Web Service** → подключи репо.
3. Render прочитает `render.yaml` — переменные задай в панели.
4. Деплой. Health-check: `https://<имя>.onrender.com/health`.

## Использование
1. Пиши боту-админке `/start`.
2. Введи номер → код кнопками → 2FA (если есть).
3. Настрой темы, сообщение, интервалы → ▶️ Запустить.

## Важно
- Web Service на free-плане засыпает через 15 мин без запросов — бот перестанет слать сообщения. Нужен план **Starter** (или выше).
- Без диска `/data` сессия не сохранится между деплоями — придётся логиниться заново. Диск стоит ~$1/мес.
