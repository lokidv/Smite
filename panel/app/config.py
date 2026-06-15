"""Application configuration"""
import os
import secrets
from pathlib import Path
from pydantic_settings import BaseSettings
from typing import Literal


class Settings(BaseSettings):
    panel_port: int = 8000
    panel_host: str = "0.0.0.0"
    panel_domain: str = ""
    https_enabled: bool = False
    https_cert_path: str = "./certs/server.crt"
    https_key_path: str = "./certs/server.key"
    docs_enabled: bool = False
    cors_allow_origins: str = "*"
    
    db_type: Literal["sqlite"] = "sqlite"
    db_path: str = "./data/smite.db"
    db_host: str = "localhost"
    db_port: int = 3306
    db_name: str = "smite"
    db_user: str = "smite"
    db_password: str = ""
    
    node_port: int = 4443
    node_cert_path: str = "./certs/ca.crt"
    node_key_path: str = "./certs/ca.key"
    node_server_cert_path: str = "./certs/ca-server.crt"
    node_server_key_path: str = "./certs/ca-server.key"
    
    secret_key: str = "changeme-secret-key-change-in-production"
    
    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()


_DEFAULT_SECRET = "changeme-secret-key-change-in-production"


def _ensure_secret_key() -> None:
    """If the JWT secret is unset/default/weak, generate a strong one and persist
    it to the .env so issued tokens survive restarts.

    This upgrades insecure installs in place instead of refusing to start (the
    default key would otherwise let anyone forge admin tokens).
    """
    key = settings.secret_key or ""
    if key and key != _DEFAULT_SECRET and len(key) >= 16:
        return
    new_key = secrets.token_hex(32)
    settings.secret_key = new_key
    try:
        env_path = Path(os.environ.get("SMITE_ENV_FILE") or "/opt/smite/.env")
        lines = env_path.read_text().splitlines() if env_path.is_file() else []
        for i, line in enumerate(lines):
            if line.strip().startswith("SECRET_KEY="):
                lines[i] = f"SECRET_KEY={new_key}"
                break
        else:
            lines.append(f"SECRET_KEY={new_key}")
        if env_path.parent.exists():
            env_path.write_text("\n".join(lines) + "\n")
    except Exception:
        # Persistence is best-effort; the in-memory key still secures this run.
        pass


_ensure_secret_key()

