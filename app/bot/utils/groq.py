"""Клиент Groq (OpenAI-совместимый chat completions)."""
from __future__ import annotations

import logging
from html import escape

import aiohttp

from app.config import GroqConfig

logger = logging.getLogger(__name__)

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
# Сколько последних реплик (user+assistant) передавать в API
GROQ_MAX_HISTORY_MESSAGES = 24


DEFAULT_SYSTEM_PROMPT = (
    "You are a concise first-line support assistant for a Telegram help bot. "
    "Reply in the same language as the user (Russian or English). "
    "Give short, practical steps when possible. "
    "Messages in the conversation prefixed with [Поддержка (оператор)] are real replies from human staff "
    "in the support group; stay consistent with them and do not contradict them. "
    "If the question needs account access, payments, or policies you do not know, "
    "say that a human operator will review the ticket and the user should wait. "
    "Do not invent company policies, prices, or guarantees."
)


async def groq_chat_completion(
    groq: GroqConfig,
    user_message: str,
    *,
    history: list[dict] | None = None,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    timeout: float = 45.0,
) -> str | None:
    """
    Возвращает текст ответа модели или None при ошибке/пустом ответе.
    history — прошлые реплики из Redis (ответы оператора из топика + прошлые реплики ИИ).
    """
    if not groq.enabled:
        return None

    past = (history or [])[-GROQ_MAX_HISTORY_MESSAGES:]
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    messages.extend(past)
    messages.append({"role": "user", "content": user_message})

    payload = {
        "model": groq.MODEL,
        "messages": messages,
        "max_tokens": 700,
        "temperature": 0.35,
    }
    headers = {
        "Authorization": f"Bearer {groq.API_KEY}",
        "Content-Type": "application/json",
    }

    client_timeout = aiohttp.ClientTimeout(total=timeout)
    try:
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            async with session.post(
                GROQ_CHAT_URL,
                json=payload,
                headers=headers,
            ) as response:
                if response.status >= 400:
                    body = (await response.text())[:500]
                    if response.status == 403:
                        logger.warning(
                            "Groq 403 Forbidden: неверный/отозванный ключ, лишние символы в GROQ_API_KEY, "
                            "или ограничение доступа (см. console.groq.com). Ответ: %s",
                            body,
                        )
                    else:
                        logger.warning("Groq HTTP error: %s %s", response.status, body)
                    return None
                data = await response.json()
    except aiohttp.ClientError as e:
        logger.warning("Groq request error: %s", e)
        return None
    except (KeyError, IndexError, TypeError, ValueError) as e:
        logger.warning("Groq unexpected response: %s", e)
        return None

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None

    text = (content or "").strip()
    return text or None


def groq_reply_for_telegram_html(text: str) -> str:
    """Безопасная разметка для ParseMode.HTML (экранирование)."""
    return escape(text)
