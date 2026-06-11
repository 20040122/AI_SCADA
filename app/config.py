from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"

    db_path: str = str(Path(__file__).resolve().parent.parent / "data" / "material.db")
    chroma_dir: str = str(Path(__file__).resolve().parent.parent / "data" / "chroma" / "db")
    schema_path: str = str(Path(__file__).resolve().parent.parent / "data" / "canvas_schema.json")
    control_jsonl_path: str = str(Path(__file__).resolve().parent.parent / "data" / "control.jsonl")

    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    model_config = {"env_file": ".env.local", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()