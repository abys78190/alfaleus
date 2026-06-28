from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import List
import json


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://alfaleus:alfaleus_dev@localhost:5432/alfaleus_db"
    
    @field_validator("DATABASE_URL", mode="before")
    def fix_database_url(cls, v: str) -> str:
        if v and v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        if v and v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        return v

    REDIS_URL: str = "redis://localhost:6379/0"
    OLLAMA_URL: str = "http://localhost:11434"

    NOTION_API_KEY: str = ""
    NOTION_DATABASE_ID: str = ""

    GOOGLE_API_KEY: str = ""
    GOOGLE_CSE_ID: str = ""

    SECRET_KEY: str = "change-me-in-production-use-a-long-random-string"
    CORS_ORIGINS: str = "*"

    SCORE_THRESHOLD: int = 60
    ICP_WEIGHT_FIT: float = 0.6
    ICP_WEIGHT_SIGNALS: float = 0.4

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    def get_cors_origins(self) -> List[str]:
        if self.CORS_ORIGINS == "*":
            return ["*"]
        try:
            return json.loads(self.CORS_ORIGINS)
        except Exception:
            return [o.strip() for o in self.CORS_ORIGINS.split(",")]


settings = Settings()
