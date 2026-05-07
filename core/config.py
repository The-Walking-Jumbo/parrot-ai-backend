from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    # LiveKit
    LIVEKIT_URL: str
    LIVEKIT_API_KEY: str
    LIVEKIT_API_SECRET: str

    # Turso Database
    DATABASE_URL: str
    TURSO_AUTH_TOKEN: str

    # Upstash Redis
    UPSTASH_REDIS_REST_URL: str
    UPSTASH_REDIS_REST_TOKEN: str
    REDIS_URL: str

    # Google Cloud Storage
    GOOGLE_APPLICATION_CREDENTIALS: str
    GCS_BUCKET_NAME: str
    GCP_PROJECT_ID: str

    # AI Services
    GROQ_API_KEY: str
    DEEPGRAM_API_KEY: str
    SARVAM_API_KEY: str
    OPENAI_API_KEY: Optional[str] = None

    # Security
    SECRET_KEY: str
    FERNET_KEY: str

    # App
    ENVIRONMENT: str = "production"
    BACKEND_URL: str
    FRONTEND_URL: str

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
