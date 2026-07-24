"""FastAPI app: lifespan (bot + jobs), CORS, router mounts, one error shape."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.bot.client import start_bot, stop_bot
from app.config import settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # APScheduler (hold-expiry, reminders) starts here once app/jobs/scheduler.py lands.
    # from app.jobs.scheduler import start_jobs; start_jobs()
    # One bot per token, only when enabled — prevents duplicate gateway sessions.
    bot_task = None
    if settings.enable_bot and settings.discord_bot_token:
        bot_task = await start_bot()
    yield
    if bot_task is not None:
        await stop_bot(bot_task)


app = FastAPI(title="SyncUp", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    # The btree_gist exclusion constraint surfaces here as a friendly conflict.
    return JSONResponse(status_code=409, content={"detail": "Resource conflict", "code": "conflict"})


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


from app.features.scheduling.router import router as scheduling_router  # noqa: E402

app.include_router(scheduling_router, prefix="/api/scheduling", tags=["scheduling"])
# resources + finance routers mount here as they land.