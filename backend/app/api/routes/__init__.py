from __future__ import annotations

from backend.app.api.routes.chat import router as chat_router
from backend.app.api.routes.health import router as health_router
from backend.app.api.routes.sessions import router as sessions_router

__all__ = ["chat_router", "health_router", "sessions_router"]
