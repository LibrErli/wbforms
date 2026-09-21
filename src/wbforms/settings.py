"""Application settings loaded from environment / .env file."""

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# Repo root in a source checkout (…/src/wbforms/settings.py → parents[2]).
# In an installed package this points into site-packages and the .env lookup
# there simply finds nothing, which pydantic-settings ignores.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Configuration for the wbforms backend.

    All Wikibase URLs default to the ceur-dev instance so the service runs
    without any extra configuration. Override via environment variables
    (prefix ``WBFORMS_``) or a ``.env`` file to point at a different
    Wikibase deployment. ``WBFORMS_ENV_FILE`` selects an alternative env
    file (e.g. ``.env.factgrid``) without copying it to ``.env``.
    """

    model_config = SettingsConfigDict(
        env_prefix="WBFORMS_",
        # Later entries take priority; missing files are ignored. The
        # project-root anchor makes the lookup independent of the CWD the
        # server happens to be launched from.
        env_file=(_PROJECT_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )
    # ToDo: Check where these constants are used
    wikibase_website: HttpUrl = HttpUrl("https://ceur-dev.wikibase.cloud/")
    wikibase_sparql_endpoint: HttpUrl = HttpUrl("https://ceur-dev.wikibase.cloud/query/sparql")
    wikibase_item_prefix: HttpUrl = HttpUrl("https://ceur-dev.wikibase.cloud/entity/")
    wikibase_property_prefix: HttpUrl = HttpUrl("https://ceur-dev.wikibase.cloud/prop/direct/")
    wikibase_mediawiki_api_url: HttpUrl = HttpUrl("https://ceur-dev.wikibase.cloud/w/api.php")
    wikibase_mediawiki_rest_url: HttpUrl = HttpUrl("https://ceur-dev.wikibase.cloud/w/rest.php")

    schema_path: Path = Path(__file__).parent / "schema" / "ceur_graph.yaml"

    oauth_version: Literal["1.0a", "2.0"] = "2.0"
    oauth_client_id: str | None = None
    oauth_client_secret: SecretStr | None = None
    oauth_redirect_uri: HttpUrl | None = None

    app_base_url: HttpUrl = HttpUrl("http://localhost:8000/")
    session_ttl_minutes: int = 60

    # Request headers
    request_header_user_agent: str | None = None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    env_file = os.getenv("WBFORMS_ENV_FILE")
    return Settings(_env_file=env_file) if env_file else Settings()


def log_effective_settings() -> None:
    """Log where the configuration came from and which Wikibase it targets.

    Called from main.py after logging is configured — get_settings() itself
    runs at import time (via codegen), before any log handler exists.
    """
    settings = get_settings()
    env_file = os.getenv("WBFORMS_ENV_FILE")
    if env_file:
        candidates: tuple[str | Path, ...] = (env_file,)
    else:
        candidates = (_PROJECT_ROOT / ".env", ".env")
    found = [str(Path(c).resolve()) for c in candidates if Path(c).is_file()]
    if found:
        logger.info(f"Settings loaded from env file(s): {', '.join(dict.fromkeys(found))}")
    else:
        logger.warning(
            "No env file found (looked for %s); using built-in ceur-dev defaults and environment variables only",
            ", ".join(str(c) for c in candidates),
        )
    logger.info(
        f"Effective Wikibase target: website={settings.wikibase_website} "
        f"sparql={settings.wikibase_sparql_endpoint} schema={settings.schema_path}"
    )
