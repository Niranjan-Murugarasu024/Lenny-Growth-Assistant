from __future__ import annotations

from collections.abc import Generator
from typing import Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Session,
    sessionmaker,
)

from backend.app.config import Settings, get_settings


class Base(DeclarativeBase):
    """Base declarative class for all SQLAlchemy ORM models."""
    pass


def create_db_engine(
    settings: Settings | None = None,
    **engine_kwargs: Any,
) -> Engine:
    """Create a configured SQLAlchemy engine for PostgreSQL."""
    app_settings = settings or get_settings()

    kwargs: dict[str, Any] = {
        "pool_pre_ping": True,
    }
    kwargs.update(engine_kwargs)

    return create_engine(app_settings.database_url, **kwargs)


def create_session_factory(
    engine: Engine | None = None,
    settings: Settings | None = None,
) -> sessionmaker[Session]:
    """Create a sessionmaker bound to an engine."""
    eng = engine or create_db_engine(settings=settings)
    return sessionmaker(
        bind=eng,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )


def get_db(
    session_factory: sessionmaker[Session] | None = None,
) -> Generator[Session, None, None]:
    """Provide a transactional database session scope."""
    factory = session_factory or create_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db_setting(session: Session, key: str, default: str | None = None) -> str | None:
    """Retrieve an application setting value from the app_settings table."""
    try:
        from backend.app.models import AppSetting
        setting = session.get(AppSetting, key)
        if setting and hasattr(setting, "value") and isinstance(setting.value, str):
            return setting.value
        return default
    except Exception:
        return default


def set_db_setting(session: Session, key: str, value: str) -> None:
    """Upsert an application setting value in the app_settings table."""
    from backend.app.models import AppSetting
    setting = session.get(AppSetting, key)
    if setting:
        setting.value = value
    else:
        setting = AppSetting(key=key, value=value)
        session.add(setting)
    session.commit()

