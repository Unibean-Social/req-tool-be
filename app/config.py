from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator, model_validator
from typing import List
from cryptography.hazmat.primitives.serialization import load_pem_private_key


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Database
    database_url: str = "postgresql+asyncpg://postgres:password@localhost:5432/reqflow"

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_database_url(cls, v: str) -> str:
        # Cloud providers (Heroku, Railway, Neon, Supabase) emit postgres:// or postgresql://
        # asyncpg requires postgresql+asyncpg://
        if v.startswith("postgres://"):
            return "postgresql+asyncpg://" + v[len("postgres://"):]
        if v.startswith("postgresql://"):
            return "postgresql+asyncpg://" + v[len("postgresql://"):]
        return v

    # JWT
    jwt_secret_key: str = "change-this-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    # Token encryption (Fernet key — generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
    encryption_key: str = ""

    # Password pepper (HMAC key — generate with: python -c "import secrets; print(secrets.token_hex(32))")
    # Defaults to jwt_secret_key in dev so no extra config is required locally.
    password_pepper: str = ""

    # GitHub OAuth App (user login/auth only)
    github_client_id: str = ""
    github_client_secret: str = ""
    github_redirect_uri: str = "http://localhost:8000/auth/github/callback"
    # Separate HMAC key for OAuth CSRF state tokens — must not share jwt_secret_key
    github_state_secret: str = ""

    # GitHub App (repo connect — installation token flow)
    github_app_id: str = ""
    github_app_client_id: str = ""  # reserved for future user-to-server App OAuth; not used in current flow
    github_app_private_key: str = ""  # PEM string — in .env use literal \n, not actual newlines
    github_app_slug: str = ""  # used to build install URL: github.com/apps/{slug}/installations/new
    github_app_redirect_uri: str = "http://localhost:8000/api/v1/github/connect/callback"

    # App
    app_env: str = "development"
    app_debug: bool = False
    cors_origins: List[str] = ["http://localhost:3000", "http://localhost:5173"]
    auto_migrate: bool = True

    @model_validator(mode="after")
    def _enforce_production_secrets(self) -> "Settings":
        if self.app_env != "development":
            if self.jwt_secret_key == "change-this-in-production":
                raise ValueError("JWT_SECRET_KEY must be changed in non-development environments")
            if len(self.jwt_secret_key) < 32:
                raise ValueError("JWT_SECRET_KEY must be at least 32 characters")
            if not self.encryption_key:
                raise ValueError("ENCRYPTION_KEY must be set in non-development environments")
            if not self.password_pepper:
                raise ValueError("PASSWORD_PEPPER must be set in non-development environments")
            if not self.github_client_id or not self.github_client_secret:
                raise ValueError("GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET must be set in non-development environments")
            if not self.github_state_secret:
                raise ValueError("GITHUB_STATE_SECRET must be set in non-development environments")
            if not self.github_app_id:
                raise ValueError("GITHUB_APP_ID must be set in non-development environments")
            if not self.github_app_private_key:
                raise ValueError("GITHUB_APP_PRIVATE_KEY must be set in non-development environments")
            if not self.github_app_slug:
                raise ValueError("GITHUB_APP_SLUG must be set in non-development environments")
            if not self.cors_origins:
                raise ValueError("CORS_ORIGINS must be non-empty in non-development environments")
        if self.github_app_private_key:
            self._validate_pem_key(self.github_app_private_key)
        return self

    @staticmethod
    def _validate_pem_key(key: str) -> None:
        key_bytes = key.replace("\\n", "\n").encode()
        try:
            load_pem_private_key(key_bytes, password=None)
        except Exception as e:
            raise ValueError(
                f"GITHUB_APP_PRIVATE_KEY is not a valid PEM private key: {e}. "
                "Ensure the key uses literal \\n (backslash-n) between lines in .env."
            )


settings = Settings()
