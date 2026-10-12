from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context

# Ensure workspace root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.config import get_settings  # noqa: E402
from backend.app.database import Base, create_db_engine  # noqa: E402
import backend.app.models  # noqa: F401, E402

# Alembic Config object
config = context.config

# Interpret config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_target_url() -> str:
    """Retrieve target database URL, allowing explicit overrides via -x url or config."""
    cmd_opts = context.get_x_argument(as_dictionary=True)
    if "url" in cmd_opts and cmd_opts["url"]:
        return cmd_opts["url"]

    main_url = config.get_main_option("sqlalchemy.url")
    if main_url and main_url != "driver://user:pass@localhost/dbname":
        return main_url

    return get_settings().database_url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_target_url()

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    url = get_target_url()
    from backend.app.config import Settings
    settings = Settings(database_url=url)
    connectable = create_db_engine(settings=settings)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
