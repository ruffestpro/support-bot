# 🤖 Бот техподдержки

[![License](https://img.shields.io/github/license/ruffestpro/support-bot)](https://github.com/ruffestpro/support-bot/blob/main/LICENSE)
[![Telegram Bot](https://img.shields.io/badge/Bot-grey?logo=telegram)](https://core.telegram.org/bots)
[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/downloads/)
[![Redis](https://img.shields.io/badge/Redis-7-DC382D?logo=redis&logoColor=white)](https://redis.io/)
[![Docker](https://img.shields.io/badge/Docker-blue?logo=docker&logoColor=white)](https://www.docker.com/)

Telegram-бот для **тикетов поддержки** через **топики форума**: пользователь пишет в личку боту, сообщения попадают в отдельную ветку супергруппы. Оператор отвечает в топике — пользователь получает копии в ЛС.

**Этот форк** ([ruffestpro/support-bot](https://github.com/ruffestpro/support-bot)) расширяет исходный шаблон: опциональные автоответы **Groq**, **контекст чата в Redis** для операторов и ИИ, **deep link** `/information` на основной бот, доработки Docker/сборки и др. Upstream: [nessshon/support-bot](https://github.com/nessshon/support-bot) (MIT).

**Лимиты Telegram** (по отзывам сообщества, не официально):

- Создание топиков ~**20**/минуту  
- Всего топиков ~**1M**

<details>
<summary><b>Команды для админа (DEV_ID), личный чат</b></summary>

- `/newsletter` — меню рассылки (`aiogram-newsletter`). Только в личке с ботом.

</details>

<details>
<summary><b>Команды в топиках группы (группа поддержки)</b></summary>

- `/ban` — заблокировать или разблокировать пользователя, привязанного к этому топику.  
- `/silent` — отключить/включить доставку сообщений оператора пользователю.  
- `/information` — карточка пользователя (ID, имя, флаги) и опциональная ссылка **Открыть в боте**, если задан `BOT_USERNAME`.

</details>

## Подготовка

1. Создайте бота в [@BotFather](https://t.me/BotFather) → `BOT_TOKEN`.  
2. Создайте **супергруппу**, включите **топики**.  
3. Добавьте бота поддержки **админом** с правом **управлять топиками**.  
4. Узнайте id группы (например, [@my_id_bot](https://t.me/my_id_bot)) → `BOT_GROUP_ID`.  
5. Выберите **кастомный emoji** для новых топиков (опционально) → `BOT_EMOJI_ID` ([документация Telegram / примеры в .env.example](https://core.telegram.org/bots/api#forumtopic)).  
6. (Опционально) Отредактируйте тексты в [`app/bot/utils/texts.py`](https://github.com/ruffestpro/support-bot/blob/main/app/bot/utils/texts.py).  
7. (Опционально) **Groq**: ключ в [Groq Console](https://console.groq.com) → `GROQ_API_KEY`; настройте `GROQ_MODEL`, `GROQ_ENABLED`.  
8. (Опционально) **`BOT_USERNAME`**: username **основного** бота без `@`. Используется в `/information` как `t.me/<user>?start=user_<telegram_id>` — основной бот должен обрабатывать `/start user_<id>`.

## Установка (Docker)

```bash
git clone https://github.com/ruffestpro/support-bot.git
cd support-bot
cp .env.example .env
nano .env   # или ваш редактор
docker compose up --build -d
```

- `docker compose` подхватывает `.env` для сервиса **bot** (`env_file` в compose).  
- Данные Redis: bind mount `./redis/data` (см. `docker-compose.yml`).  
- Если PyPI медленный из вашей сети, в compose задано **зеркало** для сборки образа; при необходимости переопределите `PIP_INDEX_URL`.

**Прод** (не правьте `docker-compose.yml` на сервере — используйте overlay):

```bash
git pull
mkdir -p data/web_chat_images
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

`docker-compose.prod.yml`: PyPI official, порт `127.0.0.1:8081→8080`, volume для фото из ЛК.

## Web API чата (личный кабинет)

Опциональный HTTP API для чата поддержки из веб-ЛК без VPN. Авторизация — проксирование cookie/Bearer в существующий `GET /api/auth/me` SoloBot (код бэкенда не меняется).

| Endpoint | Описание |
|----------|----------|
| `GET /support/messages?since=` | Список сообщений (polling) |
| `POST /support/messages` | Текст JSON `{"text":"..."}` или multipart `image` + опционально `text` |
| `GET /support/messages/{id}/image` | Вложение из веб-чата |

В nginx ЛК: `location /support-api/` → `proxy_pass http://127.0.0.1:8081/;` (прод) или `:8080/` (dev).  
Для загрузки фото: `client_max_body_size 10m;` в этом location.

Для **локальной разработки** `CABINET_API_URL` должен указывать на тот же API, куда ходит фронт ЛК (тот же origin/прокси, что и cookie сессии).

## Переменные окружения

| Переменная | Тип | Описание | Пример |
|------------|-----|----------|--------|
| `BOT_TOKEN` | str | Токен от [@BotFather](https://t.me/BotFather) | `123456:ABC...` |
| `BOT_DEV_ID` | int | Telegram user id админа (команды, отчёты об ошибках) | `123456789` |
| `BOT_GROUP_ID` | int | Id супергруппы поддержки (топики включены) | `-1001234567890` |
| `BOT_EMOJI_ID` | str | Id кастомного emoji для **новых** топиков форума | `5417915203100613993` |
| `BOT_USERNAME` | str | Username основного бота **без** `@`; пусто = нет ссылки в `/information` | `MyShopBot` |
| `REDIS_HOST` | str | Хост Redis (имя сервиса в compose: `redis`) | `redis` |
| `REDIS_PORT` | int | Порт Redis | `6379` |
| `REDIS_DB` | int | Номер логической БД Redis | `0` |
| `GROQ_API_KEY` | str | API-ключ [Groq](https://console.groq.com); пусто = без ИИ | `gsk_...` |
| `GROQ_ENABLED` | bool | `false` отключает ИИ даже при наличии ключа | `true` |
| `GROQ_MODEL` | str | Id модели Groq | `llama-3.1-8b-instant` (или `llama-3.3-70b-versatile`) |
| `WEB_API_ENABLED` | bool | HTTP API для веб-ЛК | `true` |
| `WEB_API_HOST` | str | Хост Web API | `0.0.0.0` |
| `WEB_API_PORT` | int | Порт Web API | `8080` |
| `WEB_CORS_ORIGINS` | str | Origins ЛК через запятую | `https://cp.example.com` |
| `CABINET_API_URL` | str | URL ЛК для проверки сессии | `https://cp.example.com` |

Примечания:

- **`BOT_USERNAME`**: формат ссылки `https://t.me/<BOT_USERNAME>?start=user_<tg_id>`. Парсинг нужно реализовать в **основном** боте.  
- **Groq**: ответы первой линии в ЛС; операторы видят **зеркало** текста ИИ в топике; контекст может включать недавние сообщения **оператора** (Redis).  
- **Не коммитьте** реальный `.env` — только `.env.example`.

<details>
<summary><b>Id кастомных emoji для топиков форума (справка)</b></summary>

Примеры (как в upstream README): `5417915203100613993` — 💬; актуальные id смотрите в Telegram / BotFather.

</details>

## Лицензия

[MIT License](LICENSE). Исходный шаблон: [nessshon/support-bot](https://github.com/nessshon/support-bot).
