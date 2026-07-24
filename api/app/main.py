"""FastAPI app: lifespan (bot + jobs), CORS, router mounts, one error shape."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ponytail: bot + APScheduler start here once implemented — kept out until they exist.
    # from app.bot.client import start_bot; from app.jobs.scheduler import start_jobs
    yield


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


# Feature routers mount here as they land:
# from app.features.scheduling.router import router as scheduling_router
# app.include_router(scheduling_router, prefix="/api/scheduling", tags=["scheduling"])
