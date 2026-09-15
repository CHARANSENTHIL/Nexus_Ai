import os
os.environ["OLLAMA_MODELS"] = r"D:\nexus_ai\models"

from typing import List, Union
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Nexus AI"
    API_V1_STR: str = "/api/v1"
    
    # JWT Authentication
    SECRET_KEY: str = "super-secret-jwt-key-nexus-ai-local-dev-change-in-prod"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours
    
    # Databases & Cache
    DATABASE_URL: str = "sqlite+aiosqlite:///D:/nexus_ai/backend/nexus_ai.db"
    SYNC_DATABASE_URL: str = "sqlite:///D:/nexus_ai/backend/nexus_ai.db"
    REDIS_URL: str = "redis://localhost:6379/0"
    CHROMADB_HOST: str = "localhost"
    CHROMADB_PORT: int = 8000
    CHROMADB_PATH: str = "./chroma_db"
    
    # Telegram Bot & Whitelist
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_ALLOWED_USER_IDS: Union[List[int], str] = [123456789]
    
    # Ollama LLM Settings
    OLLAMA_MODEL: str = "llama3:latest"
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    # Multi-Model Local Routing Architecture (Ollama)
    OLLAMA_ROUTER_MODEL: str = "qwen3:1.7b"
    OLLAMA_SIMPLE_MODEL: str = "qwen3:1.7b"
    OLLAMA_COMPLEX_MODEL: str = "qwen3:4b"
    OLLAMA_VISION_MODEL: str = "gemma3:4b"
    OLLAMA_CODING_MODEL: str = "phi4-mini:latest"

    # Digital Twin & Health Monitor Settings
    DIGITAL_TWIN_POLL_INTERVAL_SECONDS: int = 5
    HEALTH_MONITOR_INTERVAL_SECONDS: int = 30
    DISK_ALERT_THRESHOLD_DAYS: float = 14.0

    # Event-Driven Architecture (Redis Streams Event Bus)
    EVENT_DRIVEN_MODE: bool = True
    REDIS_STREAM_MAX_LEN: int = 10000
    EVENT_BUS_CONSUMER_TIMEOUT_MS: int = 5000
    TASK_COMPLETION_TIMEOUT: float = 120.0

    # SMTP Email Settings (Gmail)
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = "charanharshini7@gmail.com"
    SMTP_PASSWORD: str = "cxxf siut upns frnm"
    SENDER_EMAIL: str = "charanharshini7@gmail.com"
    SENDER_NAME: str = "JARVIS"



    @field_validator("TELEGRAM_ALLOWED_USER_IDS", mode="before")
    def parse_telegram_ids(cls, v):
        if isinstance(v, int):
            return [v]
        if isinstance(v, str):
            if not v.strip():
                return []
            return [int(uid.strip()) for uid in v.split(",") if uid.strip()]
        return v

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    def get_ollama_url(self) -> str:
        """Return working Ollama base URL with fallback for non-container environment."""
        url = getattr(self, "OLLAMA_BASE_URL", "http://localhost:11434")
        if "host.docker.internal" in url:
            import socket
            try:
                socket.gethostbyname("host.docker.internal")
            except socket.gaierror:
                return "http://localhost:11434"
        return url

settings = Settings()
