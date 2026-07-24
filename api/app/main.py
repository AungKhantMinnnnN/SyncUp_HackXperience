"""FastAPI app: lifespan (bot + jobs), CORS, router mounts, one error shape."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.bot.client import start_bot, stop_bot
from app.config import settings
from app.features.finance.router import router as finance_router
from app.features.resources.router import router as resources_router
from app.features.scheduling.router import router as scheduling_router
from app.jobs.scheduler import start_jobs, stop_jobs

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # One bot per token, only when enabled — prevents duplicate gateway sessions
    # (the cause of 10062 Unknown interaction) during the --reload API dev loop.
    bot_task = None
    if settings.enable_bot and settings.discord_bot_token:
        bot_task = await start_bot()
    start_jobs()
    yield
    stop_jobs()
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


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    # FastAPI's default handler wraps exc.detail as {"detail": exc.detail}. Routes here
    # raise HTTPException(detail={"detail": str, "code": str}) to match the one error
    # shape everywhere — without this override that becomes a double-nested
    # {"detail": {"detail": ..., "code": ...}} and the frontend renders "[object Object]".
    if isinstance(exc.detail, dict) and "detail" in exc.detail and "code" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc.detail), "code": "error"})


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(scheduling_router, prefix="/api/scheduling", tags=["scheduling"])
app.include_router(resources_router, prefix="/api/resources", tags=["resources"])
app.include_router(finance_router, prefix="/api/finance", tags=["finance"])
# finance router mounts here as it lands.
