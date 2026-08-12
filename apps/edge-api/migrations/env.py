from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import Any, Literal

from alembic import context
from alembic.autogenerate.api import AutogenContext
from sqlalchemy import CheckConstraint, pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings
from app.persistence import models  # noqa: F401
from app.persistence.base import Base
from app.persistence.types import UtcDateTime

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))
target_metadata = Base.metadata
ENUM_CHECK_CONSTRAINT_NAMES = frozenset(
    str(constraint.name)
    for table in target_metadata.tables.values()
    for constraint in table.constraints
    if isinstance(constraint, CheckConstraint) and getattr(constraint, "_type_bound", False)
)


def render_item(
    object_type: str, object_: Any, autogen_context: AutogenContext
) -> str | Literal[False]:
    """Keep generated revisions independent from application imports."""
    del autogen_context
    if object_type == "type" and isinstance(object_, UtcDateTime):
        return "sa.DateTime(timezone=True)"
    return False


def include_object(
    object_: object,
    name: str | None,
    object_type: str,
    reflected: bool,
    compare_to: object | None,
) -> bool:
    """Ignore reflected enum checks that SQLAlchemy represents on the enum type itself."""
    del object_, compare_to
    return not (
        object_type == "check_constraint" and reflected and name in ENUM_CHECK_CONSTRAINT_NAMES
    )


def run_migrations_offline() -> None:
    database_url = config.get_main_option("sqlalchemy.url")
    if database_url is None:
        raise RuntimeError("Alembic sqlalchemy.url is not configured.")
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=database_url.startswith("sqlite"),
        render_item=render_item,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=connection.dialect.name == "sqlite",
        render_item=render_item,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
