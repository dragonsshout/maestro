from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = Field(
        default="postgresql+asyncpg://maestro_user:maestro_password@localhost:5432/maestro_db",
        validation_alias="DB_URL"
    )

settings = Settings()
