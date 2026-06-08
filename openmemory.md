# support-bot

## Overview
Telegram support bot: пользователь → forum topic в супергруппе; оператор отвечает в топике. Fork ruffestpro/support-bot (Groq, Redis, Docker).

## User Defined Namespaces
- backend

## Components
- **Web API (FastAPI)** — `app/web/`: чат из веб-ЛК без изменений SoloBot. `POST/GET /support/messages`, auth через `GET CABINET_API_URL/api/auth/me` (cookie/Bearer). Порт `WEB_API_PORT` (8080).
- **WebSession (Redis)** — `web_users` hash: `identity_id → thread_id`, история в `web_msgs:{identity_id}`.
- **Telegram handlers** — `group/message.py`, `group/command.py`: web-сессии доставляют ответы оператора в Redis (polling ЛК), не в TG ЛС.

## Patterns
- ЛК проксирует `/support-api/` → helpbot (nginx или Vite dev). CORS: `WEB_CORS_ORIGINS`.
- Операторы работают в тех же forum topics; пин «🌐 Веб-ЛК» для web-топиков.
