import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.api.routes import router
from app.services.storage import cleanup_old_files

logging.basicConfig(level=logging.INFO)

TMP_DIR = os.environ.get("TMP_DIR", os.path.join(os.path.dirname(__file__), "../tmp"))
scheduler = AsyncIOScheduler()


async def periodic_cleanup():
    await cleanup_old_files(TMP_DIR, max_age_minutes=15)


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(TMP_DIR, exist_ok=True)
    scheduler.add_job(
        periodic_cleanup,
        "interval",
        minutes=15,
        id="cleanup",
    )
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(
    title="Universal Downloader API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok"}
