# 🤖 Support Bot

[![License](https://img.shields.io/github/license/ruffestpro/support-bot)](https://github.com/ruffestpro/support-bot/blob/main/LICENSE)
[![Telegram Bot](https://img.shields.io/badge/Bot-grey?logo=telegram)](https://core.telegram.org/bots)
[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/downloads/)
[![Redis](https://img.shields.io/badge/Redis-7-DC382D?logo=redis&logoColor=white)](https://redis.io/)
[![Docker](https://img.shields.io/badge/Docker-blue?logo=docker&logoColor=white)](https://www.docker.com/)

Telegram bot for **support tickets** via **forum topics**: user writes in private chat, messages land in a dedicated thread in your supergroup. Operators reply in the thread; the user receives copies in DM.

**This fork** ([ruffestpro/support-bot](https://github.com/ruffestpro/support-bot)) extends the original template with optional **Groq** auto-replies, **Redis-backed chat context** for operators + AI, **`/information` deep link** to a main bot, Docker/build tweaks, and more. Upstream: [nessshon/support-bot](https://github.com/nessshon/support-bot) (MIT).

**About Telegram limits** (community reports, not official):

- Topic creation ~**20**/minute  
- Total topics ~**1M**

<details>
<summary><b>Commands for admin (DEV_ID), private chat</b></summary>

- `/newsletter` — newsletter menu (`aiogram-newsletter`). Only in private chat with the bot.

</details>

<details>
<summary><b>Commands in group topics (support group)</b></summary>

- `/ban` — block or unblock the user tied to this thread.  
- `/silent` — stop/restore delivering operator messages to the user.  
- `/information` — user card (ID, name, flags) and optional link **Open in bot** if `BOT_USERNAME` is set.

</details>

## Preparation

1. Create a bot in [@BotFather](https://t.me/BotFather) → `BOT_TOKEN`.  
2. Create a **supergroup**, enable **topics**.  
3. Add the support bot as **admin** with rights to **manage topics**.  
4. Get the group id (e.g. [@my_id_bot](https://t.me/my_id_bot)) → `BOT_GROUP_ID`.  
5. Pick a **custom emoji** for new topics (optional) → `BOT_EMOJI_ID` ([Telegram docs / lists in env example](https://core.telegram.org/bots/api#forumtopic)).  
6. (Optional) Edit copy in [`app/bot/utils/texts.py`](https://github.com/ruffestpro/support-bot/blob/main/app/bot/utils/texts.py).  
7. (Optional) **Groq**: key in [Groq Console](https://console.groq.com) → `GROQ_API_KEY`; tune `GROQ_MODEL`, `GROQ_ENABLED`.  
8. (Optional) **`BOT_USERNAME`**: username of your **main** bot (no `@`). Used in `/information` as `t.me/<user>?start=user_<telegram_id>` — your main bot must handle `/start user_<id>`.

## Installation (Docker)

```bash
git clone https://github.com/ruffestpro/support-bot.git
cd support-bot
cp .env.example .env
nano .env   # or your editor
docker compose up --build -d
```

- `docker compose` loads `.env` for the **bot** service (`env_file` in compose).  
- Redis data: bind mount `./redis/data` (see `docker-compose.yml`).  
- If PyPI is slow from your network, the compose file sets a **mirror** for the image build; override `PIP_INDEX_URL` if needed.

## Environment variables

| Variable | Type | Description | Example |
|----------|------|-------------|---------|
| `BOT_TOKEN` | str | Token from [@BotFather](https://t.me/BotFather) | `123456:ABC...` |
| `BOT_DEV_ID` | int | Telegram user id of the admin (commands, error reports) | `123456789` |
| `BOT_GROUP_ID` | int | Support supergroup id (topics enabled) | `-1001234567890` |
| `BOT_EMOJI_ID` | str | Custom emoji id for **new** forum topics | `5417915203100613993` |
| `BOT_USERNAME` | str | Main bot username **without** `@`; empty = no link in `/information` | `MyShopBot` |
| `REDIS_HOST` | str | Redis hostname (service name in compose: `redis`) | `redis` |
| `REDIS_PORT` | int | Redis port | `6379` |
| `REDIS_DB` | int | Redis logical database index | `0` |
| `GROQ_API_KEY` | str | [Groq](https://console.groq.com) API key; empty = no AI | `gsk_...` |
| `GROQ_ENABLED` | bool | `false` disables AI even if the key is set | `true` |
| `GROQ_MODEL` | str | Groq chat model id | `llama-3.1-8b-instant` (или `llama-3.3-70b-versatile`) |

Notes:

- **`BOT_USERNAME`**: link format `https://t.me/<BOT_USERNAME>?start=user_<tg_id>`. Implement parsing in the **main** bot.  
- **Groq**: first-line replies in DM; operators see a **mirror** of the AI text in the topic; context can include recent **operator** messages (Redis).  
- Do **not** commit real `.env`; only `.env.example`.

<details>
<summary><b>Custom emoji IDs for forum topics (reference)</b></summary>

Examples (same idea as upstream README): `5417915203100613993` — 💬; see Telegram / BotFather for current ids.

</details>

## License

[MIT License](LICENSE). Upstream template: [nessshon/support-bot](https://github.com/nessshon/support-bot).
