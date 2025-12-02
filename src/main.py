from __future__ import annotations

import uvicorn

from .alita.api import create_app
from .alita.config import settings

app = create_app()

if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=False)
