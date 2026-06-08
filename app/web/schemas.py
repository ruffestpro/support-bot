from pydantic import BaseModel, Field


class PostMessageRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)


class ChatMessageOut(BaseModel):
    id: str
    role: str
    text: str
    created_at: str


class MessagesListResponse(BaseModel):
    messages: list[ChatMessageOut]


class PostMessageResponse(BaseModel):
    message: ChatMessageOut
    rate_limited: bool = False
    wait_sec: int = 0
