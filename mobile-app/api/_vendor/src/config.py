"""
Configuration management for PoE2 Build Optimizer
"""

import logging
import secrets as _secrets
import tempfile
from pathlib import Path
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import Field, ConfigDict, field_validator, model_validator
import yaml

logger = logging.getLogger(__name__)


def _ensure_dir_writable(path: Path, fallback_name: str) -> Path:
    """Create `path` and return it, or fall back to a writable temp dir.

    Serverless/read-only deployments (Vercel, Lambda, ...) ship the repo
    read-only outside of a scratch temp dir, so a plain `mkdir` on a
    gitignored directory that doesn't exist in the deployed bundle (cache/,
    logs/) raises PermissionError/OSError. Falling back to
    tempfile.gettempdir() keeps the module importable there instead of
    crashing at import time — those environments don't expect on-disk
    cache/log persistence across invocations anyway.
    """
    try:
        path.mkdir(exist_ok=True, parents=True)
        return path
    except OSError:
        fallback = Path(tempfile.gettempdir()) / "poe2-mcp" / fallback_name
        fallback.mkdir(exist_ok=True, parents=True)
        logger.warning(f"{path} isn't writable — using {fallback} instead (read-only deploy?)")
        return fallback


# Define paths first - use absolute paths based on script location
BASE_DIR = Path(__file__).parent.parent.resolve()
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = _ensure_dir_writable(BASE_DIR / "cache", "cache")
LOGS_DIR = _ensure_dir_writable(BASE_DIR / "logs", "logs")

# data/ ships committed in the repo, so mkdir is normally a no-op (EEXIST is
# returned before any permission check, so this doesn't need write access on
# a read-only deploy) — but never redirect DATA_DIR itself on failure, since
# that would silently point readers away from the real bundled game data.
try:
    DATA_DIR.mkdir(exist_ok=True, parents=True)
except OSError:
    logger.warning(f"Could not mkdir {DATA_DIR} (read-only deploy?) — continuing anyway")


class Settings(BaseSettings):
    """Application settings loaded from environment and config file"""

    # Server
    HOST: str = Field(default="127.0.0.1")
    PORT: int = Field(default=8080)
    DEBUG: bool = Field(default=True)
    ENV: str = Field(default="development")

    # Database
    DATABASE_URL: str = Field(default=f"sqlite:///{(DATA_DIR / 'poe2_optimizer.db').as_posix()}")
    DB_POOL_SIZE: int = Field(default=10)
    DB_ECHO: bool = Field(default=False)

    @field_validator("DATABASE_URL")
    @classmethod
    def _anchor_relative_sqlite_url(cls, v: str) -> str:
        """Anchor relative sqlite paths to the repo (#157).

        MCP clients launch the server with arbitrary working directories
        (Claude Desktop: C:\\WINDOWS\\system32). A .env override like
        ``sqlite:///data/poe2_optimizer.db`` then resolves into system32 —
        PermissionError creating ./data, then 'unable to open database
        file'. Rewrite relative sqlite URLs against BASE_DIR and normalize
        to forward slashes so SQLAlchemy gets a clean absolute URL.
        """
        for scheme in ("sqlite+aiosqlite:///", "sqlite:///"):
            if v.startswith(scheme):
                raw = v[len(scheme) :]
                path = Path(raw)
                if not path.is_absolute():
                    path = BASE_DIR / raw
                return f"{scheme}{path.resolve().as_posix()}"
        return v

    # Redis
    REDIS_URL: str = Field(default="redis://localhost:6379/0")
    REDIS_ENABLED: bool = Field(default=False)

    # API Configuration
    # REQUIRED: Trade API authentication (run: python scripts/setup_trade_auth.py)
    POESESSID: Optional[str] = Field(default=None)

    # OPTIONAL: OAuth credentials (not yet implemented - for future use)
    # Apply at: https://www.pathofexile.com/developer/docs
    POE_CLIENT_ID: Optional[str] = Field(default=None)
    POE_CLIENT_SECRET: Optional[str] = Field(default=None)

    # Third-party APIs
    POE_NINJA_API: str = Field(default="https://poe.ninja/api")
    POE_NINJA_PROFILE_URL: str = Field(default="https://poe.ninja")
    POE_OFFICIAL_API: str = Field(default="https://www.pathofexile.com")
    TRADE_API_URL: str = Field(default="https://www.pathofexile.com/trade2/search/poe2")
    REQUEST_TIMEOUT: int = Field(default=30)

    # Rate Limiting
    POE_API_RATE_LIMIT: int = Field(default=10)
    ENABLE_CACHING: bool = Field(default=False)
    CACHE_TTL: int = Field(default=3600)

    # Feature Flags
    ENABLE_TRADE_INTEGRATION: bool = Field(default=True)
    ENABLE_POB_EXPORT: bool = Field(default=True)
    ENABLE_BUILD_SHARING: bool = Field(default=True)
    ENABLE_AI_INSIGHTS: bool = Field(
        default=False
    )  # AI-powered insights (requires additional setup)

    # Web Interface
    WEB_PORT: int = Field(default=3000)
    CORS_ORIGINS: str = Field(default="http://localhost:3000,http://127.0.0.1:3000")
    MAX_SAVED_BUILDS_PER_USER: int = Field(default=50)

    def get_cors_origins_list(self) -> List[str]:
        """Parse CORS_ORIGINS string into list"""
        if isinstance(self.CORS_ORIGINS, str):
            return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]
        return self.CORS_ORIGINS

    # Logging
    LOG_LEVEL: str = Field(default="INFO")
    LOG_FILE: str = Field(default="logs/poe2_optimizer.log")
    LOG_ROTATION: str = Field(default="100 MB")
    LOG_RETENTION: str = Field(default="7 days")

    # Security
    # Set via environment variables (.env file) for persistence:
    # Generate with: python -c "import secrets; print(secrets.token_hex(32))"
    # Never commit actual secrets to version control.
    # When unset, an ephemeral cryptographically-random key is generated per
    # process (see _ensure_secret_keys) so a fresh install starts instead of
    # dying in a Pydantic ValidationError at import time (#157). Ephemeral
    # keys mean anything they encrypt/sign does not survive a restart.
    SECRET_KEY: Optional[str] = Field(
        default=None, description="Cryptographically secure random key for session management"
    )
    ENCRYPTION_KEY: Optional[str] = Field(
        default=None, description="Cryptographically secure random key for data encryption"
    )
    SESSION_TIMEOUT: int = Field(default=86400)

    @model_validator(mode="after")
    def _ensure_secret_keys(self):
        """Generate ephemeral keys when none are configured (#157)."""
        for field_name in ("SECRET_KEY", "ENCRYPTION_KEY"):
            if not getattr(self, field_name):
                setattr(self, field_name, _secrets.token_hex(32))
                logger.warning(
                    f"{field_name} is not set — generated an ephemeral random "
                    f"key for this process only. Sessions/encrypted data will "
                    f"not survive a restart. For persistence, add it to .env: "
                    f'python -c "import secrets; print(secrets.token_hex(32))"'
                )
        return self

    # Performance
    MAX_WORKERS: int = Field(default=4)
    REQUEST_TIMEOUT: int = Field(default=30)
    CALCULATION_TIMEOUT: int = Field(default=10)

    # Monitoring
    SENTRY_DSN: Optional[str] = Field(default=None)
    PROMETHEUS_ENABLED: bool = Field(default=False)
    PROMETHEUS_PORT: int = Field(default=9090)

    model_config = ConfigDict(
        env_file=str(BASE_DIR / ".env"),  # Use absolute path
        env_file_encoding="utf-8",
        case_sensitive=True,
        # Forward-compat: launcher-level flags like POE2_MCP_AUTO_UPDATE /
        # POE2_MCP_NO_CODE_CHECK / POE2_MCP_NO_DATA_FETCH live in os.environ
        # but aren't Settings fields. Without `extra='ignore'` pydantic
        # raises ValidationError on them. Also future-proofs any new
        # process-level env var we add without touching this class.
        extra="ignore",
    )


def load_yaml_config(config_path: str = "config.yaml") -> dict:
    """Load configuration from YAML file"""
    config_file = Path(config_path)
    if config_file.exists():
        with open(config_file, "r") as f:
            return yaml.safe_load(f)
    return {}


# Global settings instance
settings = Settings()

# Load additional YAML config if exists
yaml_config = load_yaml_config()


def get_setting(key: str, default=None):
    """
    Get setting from environment, YAML config, or default
    Priority: Environment > YAML > Default
    """
    # Try environment variable first
    if hasattr(settings, key):
        return getattr(settings, key)

    # Try YAML config
    if key in yaml_config:
        return yaml_config[key]

    return default


# Paths already defined at top of file
