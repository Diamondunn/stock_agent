from fastapi import APIRouter
from pydantic import BaseModel
from app.chatbot import StockChatBot

router = APIRouter()
bot = StockChatBot()


class ChatRequest(BaseModel):
    message: str


@router.post("/chat")
async def chat(req: ChatRequest):
    response = bot.ask(req.message)
    return {"response": response}
