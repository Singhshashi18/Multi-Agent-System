from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Multi-Agent Collaboration API"
    app_env: str = "development"
    database_url: str = "sqlite:///./multi_agent.db"
    openai_api_key: str | None = None
    google_api_key: str | None = None
    gemini_model: str = "gemini-flash-latest"
    tavily_api_key: str | None = None
    jwt_secret_key: str = "change-this-in-env"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
