"""Nexus AI — FastAPI Application Entry Point."""
import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Ensure backend root is always in sys.path even when spawned by reloaders or subprocesses
backend_root = str(Path(__file__).resolve().parent.parent)
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


from app.config import settings
from app.api import digital_twin
from app.api import planner as planner_api
from app.api import metrics as metrics_api
from app.health_monitor.worker import health_monitor_worker

from app.api import events_api
from app.events.event_bus import event_bus
from app.events.workers import ALL_WORKERS

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

stop_event = asyncio.Event()
health_task = None
telegram_task = None
event_workers_started = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    global health_task, telegram_task, event_workers_started
    stop_event.clear()

    # Initialize SQLite database schema
    try:
        from app.db.session import init_db
        import app.db.models  # ensure models are registered
        await init_db()
        logger.info("SQLite database schema initialized.")
    except Exception as e:
        logger.warning(f"Database init warning: {e}")

    # Initialize Event Bus & Micro-Agent Workers if EVENT_DRIVEN_MODE is enabled
    if settings.EVENT_DRIVEN_MODE:
        try:
            await event_bus.initialize()
            for worker in ALL_WORKERS:
                await worker.start()
            event_workers_started = True
            logger.info("⚡ [EventBus] Event-driven architecture active — 7 agent workers started.")
        except Exception as eb_err:
            logger.error(f"[EventBus] Failed to start event workers: {eb_err}")

    # Start health monitor
    health_task = asyncio.create_task(health_monitor_worker.run(stop_event))

    # Start Telegram bot if token is configured
    telegram_token = getattr(settings, "TELEGRAM_BOT_TOKEN", "") or os.getenv("TELEGRAM_BOT_TOKEN", "")
    if telegram_token:
        from app.telegram_bot.bot import build_telegram_app
        tg_app = build_telegram_app(telegram_token)
        telegram_task = asyncio.create_task(_run_telegram(tg_app))
        logger.info("Telegram bot started.")
    else:
        logger.warning("TELEGRAM_BOT_TOKEN not set — Telegram bot disabled.")

    yield

    stop_event.set()
    if event_workers_started:
        for worker in ALL_WORKERS:
            await worker.stop()
    if health_task:
        await health_task
    if telegram_task:
        telegram_task.cancel()



async def _run_telegram(tg_app):
    """Run Telegram bot polling in the background with single-instance protection."""
    from app.telegram_bot.bot import acquire_bot_lock
    if not acquire_bot_lock():
        logger.info("[Telegram] Another instance is already running — skipping duplicate bot startup.")
        return

    try:
        await tg_app.initialize()
        await tg_app.start()
        await tg_app.updater.start_polling(drop_pending_updates=True)
        await stop_event.wait()
        await tg_app.updater.stop()
        await tg_app.stop()
        await tg_app.shutdown()
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"Telegram bot error: {e}")



app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Autonomous AI Desktop Agent — LangChain + CrewAI + Llama 3",
    version="1.0.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.api import vision_api

# Routers
app.include_router(digital_twin.router, prefix=settings.API_V1_STR, tags=["Digital Twin"])
app.include_router(planner_api.router, prefix=settings.API_V1_STR, tags=["Planner"])
app.include_router(metrics_api.router, prefix=settings.API_V1_STR, tags=["Metrics"])
app.include_router(vision_api.router, prefix=settings.API_V1_STR, tags=["Vision"])
app.include_router(events_api.router, prefix=settings.API_V1_STR, tags=["Events & Timeline"])




@app.get("/", tags=["Health"])
async def root():
    return {"message": "Nexus AI Backend Operational", "version": "1.0.0", "status": "ok"}


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "healthy"}
