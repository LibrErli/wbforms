import logging
import os
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import Depends, FastAPI
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles

from wbforms.api import wd_migrate
from wbforms.api.auth import login_user
from wbforms.api.frontend import router as frontend_router
from wbforms.api.oauth import router as oauth_router
from wbforms.codegen import get_routers
from wbforms.settings import log_effective_settings


def _setup_logging() -> None:
    level = logging.getLevelName(os.getenv("LOG_LEVEL", "DEBUG").upper())
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)s - %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    # Suppress noisy third-party loggers
    for noisy in ("httpx", "httpcore", "hpack", "wikibaseintegrator"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.basicConfig(level=level)


_setup_logging()
log_effective_settings()

app = FastAPI()

_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

for router in get_routers():
    app.include_router(router)

app.include_router(wd_migrate.router)
app.include_router(oauth_router)

# Frontend router last so it doesn't shadow API routes
app.include_router(frontend_router)


@app.post("/token")
async def login(form_data: Annotated[OAuth2PasswordRequestForm, Depends()]):
    return await login_user(form_data.username, form_data.password)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
