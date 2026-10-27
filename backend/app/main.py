import os
import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.api.health_platforms import router as health_platforms_router
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

# Host header validation middleware
@app.middleware("http")
async def validate_host_header(request: Request, call_next):
    host = request.headers.get("host", "")
    if host:
        if host.startswith("["):
            parts = host.split("]")
            host_name = parts[0][1:]
            port_part = parts[1][1:] if len(parts) > 1 and parts[1].startswith(":") else ""
        else:
            parts = host.split(":")
            host_name = parts[0].lower()
            port_part = parts[1] if len(parts) > 1 else ""

        if host_name not in ("127.0.0.1", "localhost", "testserver"):
            return JSONResponse(
                status_code=400,
                content={"detail": "Invalid Host header"},
            )

        backend_port = os.environ.get("BACKEND_PORT") or os.environ.get("PORT") or "8000"
        if port_part and port_part != backend_port:
            return JSONResponse(
                status_code=400,
                content={"detail": "Invalid Host header port"},
            )

    return await call_next(request)


# Mutating request & sensitive GET token verification middleware
@app.middleware("http")
async def verify_app_token(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)

    expected_token = os.environ.get("APP_SESSION_TOKEN")
    if expected_token:
        path = request.url.path
        is_mutating = request.method in ("POST", "DELETE", "PUT", "PATCH")
        is_sensitive_get = request.method == "GET" and (
            path == "/api/stream"
            or path.startswith("/api/stream/")
            or path.startswith("/api/file/")
        )
        if is_mutating or is_sensitive_get:
            token = request.headers.get("X-App-Token") or request.query_params.get("token")
            if not token or not hmac.compare_digest(token, expected_token):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Forbidden: invalid or missing X-App-Token"},
                )
    return await call_next(request)


# Allow only specific local origins where Electron serves UI (no wildcard)
frontend_origins_raw = os.environ.get("FRONTEND_ORIGIN", "")
if frontend_origins_raw:
    allowed_origins = [o.strip() for o in frontend_origins_raw.split(",") if o.strip()]
else:
    allowed_origins = [
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(health_platforms_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
