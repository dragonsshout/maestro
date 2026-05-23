from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = Field(default="local", validation_alias="ENVIRONMENT")

    database_url: str = Field(
        default="postgresql+asyncpg://maestro_user:maestro_password@localhost:5432/maestro_db",
        validation_alias="DB_URL"
    )

    jenkins_url: str = Field(default="http://localhost:8080")
    jenkins_username: Optional[str] = Field(default=None)
    jenkins_token: Optional[str] = Field(default=None)

    github_organization: str = Field(default="my-org")
    github_token: Optional[str] = Field(default=None)

settings = Settings()
