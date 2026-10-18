from pathlib import Path

from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)


BASE_DIR = Path(__file__).resolve().parent

class Settings(BaseSettings):
    openai_api_key: str

    openai_model: str = "openai:gpt-5-mini"

    telegram_bot_token: str

    embedding_model: str = "text-embedding-3-small"



    google_credentials_file: str = (
        "credentials/credentials.json"
    )
    google_token_file: str = "credentials/token.json"
    google_calendar_id: str = "primary"

    clinic_timezone: str = "Asia/Riyadh"
    clinic_open_hour: int = 9
    clinic_close_hour: int = 17
    break_start_hour: int = 13
    break_end_hour: int = 14
    appointment_duration_minutes: int = 30

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    @property
    def resolved_google_credentials_file(self) -> Path:
        return (BASE_DIR / self.google_credentials_file).resolve()

    @property
    def resolved_google_token_file(self) -> Path:
        return (BASE_DIR / self.google_token_file).resolve()

settings = Settings()
