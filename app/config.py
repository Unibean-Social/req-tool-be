from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator
from typing import List


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Database
    database_url: str = "postgresql+asyncpg://postgres:password@localhost:5432/reqflow"

    # JWT
    jwt_secret_key: str = "change-this-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    # Token encryption (Fernet key — generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
    encryption_key: str = ""

    # GitHub OAuth
    github_client_id: str = ""
    github_client_secret: str = ""
    github_redirect_uri: str = "http://localhost:8000/auth/github/callback"

    # App
    app_env: str = "development"
    app_debug: bool = False
    cors_origins: List[str] = ["http://localhost:3000", "http://localhost:5173"]

    @model_validator(mode="after")
    def _enforce_production_secrets(self) -> "Settings":
        if self.app_env != "development":
            if self.jwt_secret_key == "change-this-in-production":
                raise ValueError("JWT_SECRET_KEY must be changed in non-development environments")
            if len(self.jwt_secret_key) < 32:
                raise ValueError("JWT_SECRET_KEY must be at least 32 characters")
            if not self.encryption_key:
                raise ValueError("ENCRYPTION_KEY must be set in non-development environments")
            if not self.github_client_id or not self.github_client_secret:
                raise ValueError("GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET must be set in non-development environments")
        return self


settings = Settings()
