import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from src.config import settings
from src.database import init_db
from src.session_manager import disconnect_all
from src.api import accounts, messages, ai, automation, channels, warmup, proxies, group_chat
from src.services import bot_service, channel_service, warmup_service, group_chat_service, boost_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await bot_service.start_all_running()
    await channel_service.start_all_running()
    await warmup_service.start_all_running()
    await group_chat_service.start_all_running()
    await boost_service.start_all_running()
    yield
    await disconnect_all()


app = FastAPI(title="TG Manager", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)
    if settings.api_key:
        if request.headers.get("X-API-Key", "") != settings.api_key:
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})
    return await call_next(request)

app.include_router(accounts.router, prefix="/api")
app.include_router(messages.router, prefix="/api")
app.include_router(ai.router, prefix="/api")
app.include_router(automation.router, prefix="/api")
app.include_router(channels.router, prefix="/api")
app.include_router(warmup.router, prefix="/api")
app.include_router(proxies.router, prefix="/api")
app.include_router(group_chat.router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok"}
