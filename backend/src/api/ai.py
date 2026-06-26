from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from src.services.ai_service import suggest_reply, improve_text

router = APIRouter(prefix="/ai", tags=["ai"])


class SuggestRequest(BaseModel):
    conversation: list[dict]   # [{"sender": "Ivan", "text": "привет"}]
    hint: str = ""
    tone: str = "friendly"


class ImproveRequest(BaseModel):
    text: str
    instruction: str           # "shorter", "more formal", "add emoji", etc.


@router.post("/suggest")
async def get_suggestions(data: SuggestRequest):
    if not data.conversation:
        raise HTTPException(status_code=400, detail="conversation is empty")
    suggestions = await suggest_reply(data.conversation, data.hint, data.tone)
    return {"suggestions": suggestions}


@router.post("/improve")
async def improve_message(data: ImproveRequest):
    result = await improve_text(data.text, data.instruction)
    return {"result": result}
