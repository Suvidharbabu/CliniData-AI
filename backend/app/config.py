from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    supabase_url: str = ""
    supabase_jwt_secret: str = ""
    database_url: str = ""

    neo4j_uri: str = ""
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    pinecone_api_key: str = ""
    pinecone_index: str = "clinidata"
    pinecone_rerank_model: str = "bge-reranker-v2-m3"

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: str = "low"
    anthropic_hyde_model: str = "claude-haiku-4-5"

    allowed_origins: str = "http://localhost:5173"
    daily_query_limit: int = 20

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
