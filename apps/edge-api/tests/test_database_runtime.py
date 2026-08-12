from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from app.persistence.database import Database


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_sqlite_uses_edge_safe_connection_pragmas(
    tmp_path: Path,
    anyio_backend: str,
) -> None:
    del anyio_backend
    database_path = (tmp_path / "runtime.db").as_posix()
    database = Database(f"sqlite+aiosqlite:///{database_path}")
    try:
        async with database.engine.connect() as connection:
            foreign_keys = await connection.scalar(text("PRAGMA foreign_keys"))
            busy_timeout = await connection.scalar(text("PRAGMA busy_timeout"))
            journal_mode = await connection.scalar(text("PRAGMA journal_mode"))
            synchronous = await connection.scalar(text("PRAGMA synchronous"))
        assert foreign_keys == 1
        assert busy_timeout == 30_000
        assert str(journal_mode).casefold() == "wal"
        assert synchronous == 1  # NORMAL
    finally:
        await database.dispose()
