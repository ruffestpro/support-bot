from dataclasses import dataclass

import aiohttp
from fastapi import HTTPException, Request, status

from app.config import Config


@dataclass(frozen=True)
class CabinetIdentity:
    id: str
    email: str | None
    tg_id: int | None


def _normalize_me_payload(data: dict) -> CabinetIdentity:
    identity_id = data.get("id")
    if not identity_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid cabinet session")
    email = data.get("email")
    tg_raw = data.get("tg_id", data.get("tgId"))
    tg_id = int(tg_raw) if tg_raw is not None else None
    return CabinetIdentity(
        id=str(identity_id),
        email=str(email).strip() if email else None,
        tg_id=tg_id,
    )


async def verify_cabinet_request(request: Request, config: Config) -> CabinetIdentity:
    """
    Проверяет сессию ЛК через существующий GET /api/auth/me (cookie или Bearer).
    Код SoloBot не меняется — только read-only прокси-запрос.
    """
    cabinet_url = config.web.CABINET_API_URL
    if not cabinet_url:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CABINET_API_URL is not configured",
        )

    headers: dict[str, str] = {"Accept": "application/json"}
    cookie = request.headers.get("cookie")
    authorization = request.headers.get("authorization")
    if cookie:
        headers["Cookie"] = cookie
    if authorization:
        headers["Authorization"] = authorization
    if not cookie and not authorization:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    url = f"{cabinet_url}/api/auth/me"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 401:
                    raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid cabinet session")
                if resp.status != 200:
                    text = await resp.text()
                    raise HTTPException(
                        status.HTTP_502_BAD_GATEWAY,
                        detail=f"Cabinet API error ({resp.status}): {text[:200]}",
                    )
                data = await resp.json()
    except aiohttp.ClientError as ex:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"Cannot reach cabinet API: {ex}",
        ) from ex

    if not isinstance(data, dict):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail="Invalid cabinet API response")
    return _normalize_me_payload(data)
