from abc import abstractmethod, ABCMeta

from aiogram.utils.markdown import hbold

# Add other languages and their corresponding codes as needed.
# You can also keep only one language by removing the line with the unwanted language.
SUPPORTED_LANGUAGES = {
    "ru": "🇷🇺 Русский",
    "en": "🇬🇧 English",
}


class Text(metaclass=ABCMeta):
    """
    Abstract base class for handling text data in different languages.
    """

    def __init__(self, language_code: str) -> None:
        """
        Initializes the Text instance with the specified language code.

        :param language_code: The language code (e.g., "ru" or "en").
        """
        self.language_code = language_code if language_code in SUPPORTED_LANGUAGES.keys() else "en"

    @property
    @abstractmethod
    def data(self) -> dict:
        """
        Abstract property to be implemented by subclasses. Represents the language-specific text data.

        :return: Dictionary containing language-specific text data.
        """
        raise NotImplementedError

    def get(self, code: str) -> str:
        """
        Retrieves the text corresponding to the provided code in the current language.

        :param code: The code associated with the desired text.
        :return: The text in the current language.
        """
        return self.data[self.language_code][code]


class TextMessage(Text):
    """
    Subclass of Text for managing text messages in different languages.
    """

    @property
    def data(self) -> dict:
        """
        Provides language-specific text data for text messages.

        :return: Dictionary containing language-specific text data for text messages.
        """
        return {
            "en": {
                "select_language": f"👋 <b>Hello</b>, {hbold('{full_name}')}!\n\nSelect language:",
                "change_language": "<b>Select language:</b>",
                "main_menu": "<b>Write your question</b>, and we will answer you as soon as possible:",
                "message_sent": "<b>Message sent!</b> Expect a response.",
                "message_edited": (
                    "<b>The message was edited only in your chat.</b> "
                    "To send an edited message, send it as a new message."
                ),
                "source": (
                    "Source code available at "
                    "<a href=\"https://github.com/nessshon/support-bot\">GitHub</a>"
                ),
                "user_started_bot": (
                    f"User {hbold('{name}')} started the bot!\n\n"
                    "List of available commands:\n\n"
                    "• /ban\n"
                    "Block/Unblock user"
                    "<blockquote>Block the user if you do not want to receive messages from him.</blockquote>\n\n"
                    "• /silent\n"
                    "Activate/Deactivate silent mode"
                    "<blockquote>When silent mode is enabled, messages are not sent to the user.</blockquote>\n\n"
                    "• /information\n"
                    "User information"
                    "<blockquote>Receive a message with basic information about the user.</blockquote>"
                ),
                "user_restarted_bot": f"User {hbold('{name}')} restarted the bot!",
                "user_stopped_bot": f"User {hbold('{name}')} stopped the bot!",
                "user_blocked": "<b>User blocked!</b> Messages from the user are not accepted.",
                "user_unblocked": "<b>User unblocked!</b> Messages from the user are being accepted again.",
                "blocked_by_user": "<b>Message not sent!</b> The bot has been blocked by the user.",
                "user_information": (
                    "<b>ID:</b>\n"
                    "- <code>{id}</code>\n"
                    "<b>Name:</b>\n"
                    "- {full_name}\n"
                    "<b>Status:</b>\n"
                    "- {state}\n"
                    "<b>Username:</b>\n"
                    "- {username}\n"
                    "<b>Blocked:</b>\n"
                    "- {is_banned}\n"
                    "<b>Registration date:</b>\n"
                    "- {created_at}"
                ),
                "user_information_open_link": (
                    "🔍 <a href=\"https://t.me/{bot_username}?start=user_{tg_id}\">Open in bot</a>"
                ),
                "message_not_sent": "<b>Message not sent!</b> An unexpected error occurred.",
                "message_sent_to_user": "<b>Message sent to user!</b>",
                "silent_mode_enabled": (
                    "<b>Silent mode activated!</b> Messages will not be delivered to the user."
                ),
                "silent_mode_disabled": (
                    "<b>Silent mode deactivated!</b> The user will receive all messages."
                ),
                "groq_staff_header": (
                    "🤖 <b>AI reply (Groq) sent to the user in private chat:</b>"
                ),
            },
            "ru": {
                "select_language": f"👋 <b>Добро пожаловать, отважный герой</b>, {hbold('{full_name}')}!\n\n🔹 Выберите язык для своей миссии:",
                "change_language": "<b>Выберите язык:</b>",
                "main_menu": "⚔️ <b>Оставьте свой запрос, храбрый джедай</b>, и Орден ответит вам в ближайшее время:",
                "message_sent": "📡 <b>Сообщение успешно отправлено!</b> Ваш сигнал достиг Совета — ожидайте ответа.",
                "message_edited": (
                    "⚠️ <b>Сообщение изменено только в вашем чате.</b> "
                    "Чтобы передать Совету изменённый сигнал, отправьте его заново."
                ),
                "source": (
                    "Исходный код доступен на "
                    "<a href=\"https://github.com/nessshon/support-bot\">GitHub</a>"
                ),
                "user_started_bot": (
                    f"✨ <b>Дроид активирован пользователем {hbold('{name}')}!</b>\n\n"
                    "Список доступных команд:\n\n"
                    "• /ban\n"
                    "⚔️ Заблокировать или разблокировать пользователя\n"
                    "<blockquote>Используйте силу, чтобы запретить доступ тем, кто нарушает баланс.</blockquote>\n\n"
                    "• /silent\n"
                    "🔕 Активировать/деактивировать режим тишины\n"
                    "<blockquote>Станьте незаметным — сообщения не будут доставляться.</blockquote>\n\n"
                    "• /information\n"
                    "🛰️ Информация о пользователе\n"
                    "<blockquote>Раздобудьте все данные о союзнике или потенциальной угрозе.</blockquote>"
                ),
                "user_restarted_bot": f"⚡ Пользователь {hbold('{name}')} перезапустил(а) дроида!",
                "user_stopped_bot": f"⛔ Пользователь {hbold('{name}')} остановил(а) дроида!",
                "user_blocked": "🔒 <b>Пользователь заблокирован!</b> Его сообщения больше не доставляются.",
                "user_unblocked": "🔓 <b>Пользователь разблокирован!</b> Его сообщения вновь доступны.",
                "blocked_by_user": "🛑 <b>Сообщение не отправлено!</b> Дроид был заблокирован пользователем.",
                "user_information": (
                    "<b>ID:</b>\n"
                    "- <code>{id}</code>\n"
                    "<b>Имя:</b>\n"
                    "- {full_name}\n"
                    "<b>Статус:</b>\n"
                    "- {state}\n"
                    "<b>Username:</b>\n"
                    "- {username}\n"
                    "<b>Заблокирован:</b>\n"
                    "- {is_banned}\n"
                    "<b>Дата регистрации:</b>\n"
                    "- {created_at}"
                ),
                "user_information_open_link": (
                    "🔍 <a href=\"https://t.me/{bot_username}?start=user_{tg_id}\">Открыть в боте</a>"
                ),
                "message_not_sent": "⚠️ <b>Передача прервана!</b> Возникла ошибка в канале связи.",
                "message_sent_to_user": "✅ <b>Сообщение успешно доставлено союзнику!</b>",
                "silent_mode_enabled": (
                    "🔕 <b>Режим тишины активирован!</b> Сигналы теперь невидимы для пользователя."
                ),
                "silent_mode_disabled": (
                    "🔔 <b>Режим тишины отключён!</b> Все сообщения теперь видимы для пользователя."
                ),
                "groq_staff_header": (
                    "🤖 <b>Ответ ИИ (Groq), отправленный пользователю в ЛС:</b>"
                ),
            },
        }
