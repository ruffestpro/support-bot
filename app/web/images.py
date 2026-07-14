from pathlib import Path

WEB_CHAT_IMAGES_DIR = Path("data/web_chat_images")
MAX_IMAGE_BYTES = 10 * 1024 * 1024

ALLOWED_IMAGE_MIME: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def image_api_path(message_id: str) -> str:
    return f"/support/messages/{message_id}/image"


def _identity_dir(identity_id: str) -> Path:
    return WEB_CHAT_IMAGES_DIR / identity_id


def save_web_chat_image(
    identity_id: str,
    message_id: str,
    data: bytes,
    mime: str,
) -> None:
    ext = ALLOWED_IMAGE_MIME[mime]
    path = _identity_dir(identity_id) / f"{message_id}{ext}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def resolve_web_chat_image(identity_id: str, message_id: str) -> Path | None:
    folder = _identity_dir(identity_id)
    for ext in ALLOWED_IMAGE_MIME.values():
        candidate = folder / f"{message_id}{ext}"
        if candidate.is_file():
            return candidate
    return None
