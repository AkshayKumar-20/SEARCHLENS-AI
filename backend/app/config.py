from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    audit_db_path: str = ""
    request_timeout: float = 8.0
    max_pages: int = 10
    max_depth: int = 3
    max_response_bytes: int = 2_000_000
    max_link_checks: int = 200  # unique internal URLs checked per audit; extra ones are reported as skipped
    link_check_workers: int = 4  # parallel link checks (each still waits request_delay)
    pagespeed_api_key: str = ""
    pagespeed_strategy: str = "mobile"
    pagespeed_timeout: float = 60.0  # Google often needs 30-40 s per URL
    # Any OpenAI-compatible chat API, used only to write the action list.
    # Leave base URL or model empty to use the rule-based fallback list.
    llm_base_url: str = ""  # e.g. https://api.openai.com/v1
    llm_api_key: str = ""  # optional for local servers such as Ollama
    llm_model: str = ""  # e.g. gpt-4o-mini
    llm_timeout: float = 30.0
    model_config = SettingsConfigDict(env_prefix="SEARCHLENS_", env_file=".env", extra="ignore")


settings = Settings()
