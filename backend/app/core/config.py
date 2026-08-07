from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str
    ENV: str

    DATABASE_URL: str

    OPENAI_API_KEY: str = ""

    OLLAMA_BASE_URL: str

    DEFAULT_AI_PROVIDER: str = "ollama"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()