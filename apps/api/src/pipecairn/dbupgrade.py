"""Start up schema step for SQLite: create missing tables (create_all) and add missing columns to tables an older version created.

Postgres is migrated with `alembic upgrade head`. SQLite has no migration step in the zero setup path, so a new column in an update would leave an existing
`.sqlite3` file broken. This adds, for every table that already exists, each column the models have and the file lacks: a nullable column as it is, a required one
with its server default or its plain default value. A change it cannot make safely (a required column with no default) is reported, never guessed.
"""

from __future__ import annotations

import logging

from sqlalchemy import Column, Engine, inspect, text

from sendora_core.db import Base

log = logging.getLogger("pipecairn.dbupgrade")


def _default_sql(col: Column) -> str | None:
    if col.server_default is not None and getattr(col.server_default, "arg", None) is not None:
        arg = col.server_default.arg
        return str(arg.text) if hasattr(arg, "text") else "'" + str(arg).replace("'", "''") + "'"
    d = col.default.arg if col.default is not None and getattr(col.default, "is_scalar", False) else None
    if isinstance(d, bool):
        return "1" if d else "0"
    if isinstance(d, int | float):
        return str(d)
    if isinstance(d, str):
        return "'" + d.replace("'", "''") + "'"
    return None


def create_and_upgrade(engine: Engine) -> list[str]:
    """create_all, then add the missing columns. Returns the names of the columns added ("table.column")."""
    Base.metadata.create_all(engine)
    added: list[str] = []
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have or col.primary_key:
                    continue
                default = _default_sql(col)
                if not col.nullable and default is None:
                    log.error("table %s lacks the required column %s and it has no default; run a fresh database or use Postgres with alembic", table.name, col.name)
                    continue
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col.type.compile(dialect=engine.dialect)}'
                if default is not None:
                    ddl += f" DEFAULT {default}"
                if not col.nullable:
                    ddl += " NOT NULL"
                conn.execute(text(ddl))
                added.append(f"{table.name}.{col.name}")
    return added
