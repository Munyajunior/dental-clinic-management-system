from pydantic_settings import BaseSettings
from pydantic import Field, field_validator, model_validator
from typing import List
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    # Environment setting
    PRODUCTION: bool = Field()
    DEVELOPMENT: bool = Field(True)

    # API settings
    API_PREFIX: str = Field("")
    DEBUG: bool = Field(False)
    ALLOWED_ORIGINS: str = Field("*")

    # Database settings
    DB_HOST: str = Field("")
    DB_PORT: int = Field(5432)
    DB_USER: str = Field("")
    DB_PASSWORD: str = Field("")
    DB_NAME: str = Field("")
    DB_DOMAIN: str = Field("")
    DB_DRIVER: str = Field("postgresql+asyncpg")

    SQLITE_MODE: bool = Field(False)

    # Redis settings
    REQUIRE_REDIS: bool = True
    CACHE_ENABLED: bool = True

    REDIS_HOST: str = Field("")
    REDIS_PORT: int = Field(6379)
    REDIS_PASSWORD: str = Field("")
    REDIS_DB: int = Field(0)

    # Jwt Security settings
    SECRET_KEY: str = Field("")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field()
    ALGORITHM: str = Field("HS256")
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field()
    ACCESS_TOKEN_EXPIRE_HOURS: int = Field()
    ACCESS_TOKEN_EXPIRE: int = Field()

    # RLS and Multi-tenancy
    CREATE_DEFAULT_TENANT: bool = Field(
        True, description="Create default tenant on startup"
    )
    ENVIRONMENT: str = Field(
        "development", description="Environment: development, staging, production"
    )

    # Tenant identification methods
    TENANT_ID_HEADER: str = Field(
        "X-Tenant-ID", description="Header for tenant identification"
    )
    TENANT_SUBDOMAIN_ENABLED: bool = Field(
        True, description="Enable tenant identification via subdomain"
    )

    # RLS Settings
    RLS_ENABLED: bool = Field(True, description="Enable Row-Level Security")

    # Uvicorn settings
    UVICORN_HOST: str = Field()
    UVICORN_PORT: int = Field()
    WORKERS_COUNT: int = Field(1)
    RELOAD: bool = Field(True)

    # Email settings
    MAIL_USERNAME: str = Field("")
    MAIL_FROM: str = Field("")
    MAIL_PORT: int = Field(465)
    MAIL_SERVER: str = Field("")
    MAILGUN_API_KEY: str = Field("")
    MAILGUN_DOMAIN: str = Field("")

    @property
    def POSTGRESQL_DATABASE_URL(self) -> str:
        return (
            f"{self.DB_DRIVER}://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @property
    def SQLITE_DATABASE_URL(self) -> str:
        return f"sqlite+aiosqlite:///{self.DB_NAME}.db"

    @property
    def DATABASE_URL(self) -> str:
        return (
            self.SQLITE_DATABASE_URL
            if self.SQLITE_MODE
            else self.POSTGRESQL_DATABASE_URL
        )

    @property
    def REDIS_CACHE_URL(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @field_validator("ALLOWED_ORIGINS")
    def validate_origins(cls, v: str) -> List[str]:
        return v.split(",") if v else []

    @model_validator(mode="after")
    def check_database_config(cls, values):
        if values.SQLITE_MODE:
            if not values.SQLITE_DATABASE_URL.strip():
                raise ValueError(
                    "SQLite mode is enabled but SQLITE_DATABASE_URL is missing."
                )
        else:
            missing = [
                field
                for field in ["DB_USER", "DB_PASSWORD", "DB_HOST", "DB_NAME"]
                if not getattr(values, field).strip()
            ]
            if missing:
                raise ValueError(
                    f"PostgreSQL mode is enabled but the following fields are missing: {', '.join(missing)}"
                )
        return values

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


settings = Settings()
