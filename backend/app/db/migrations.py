"""Sequenced, idempotent schema migrations.

A small, dependency-free migration runner that backs the workflow
documented in `.cursor/rules/db-schema-via-migrations.mdc`. The goal is
that ``t2l deploy be`` is the only operator step needed to roll out a
schema change — no separate "apply migrations" command, no risk of
forgetting to ``ALTER`` prod the way we forgot ``users.apple_sub`` on
24 May 2026.

Mechanism
---------

* Every change to the database shape ships as
  ``backend/db/migrations/NNNN_short_name.sql``, where ``NNNN`` is a
  monotonically-increasing 4-digit version.
* On every backend boot, ``apply_pending_migrations()`` (called from
  ``schema_bootstrap.ensure_schema()`` right after the ``CREATE TABLE
  IF NOT EXISTS`` pass) walks the directory in name order and runs any
  file whose stem is not yet present in the ``schema_migrations``
  table. Each successfully-applied filename is recorded there.
* Statements inside a migration file are split on top-level
  semicolons and executed one at a time so partial-overlap states are
  recoverable. MySQL error codes 1060 (``ER_DUP_FIELDNAME`` —
  column already exists), 1061 (``ER_DUP_KEYNAME`` — index already
  exists), and 1091 (``ER_CANT_DROP_FIELD_OR_KEY`` — DROP target
  missing) are swallowed; the migration is still recorded as
  applied. This is what lets a brand-new install (whose
  ``001_schema.sql`` already produced the post-migration shape)
  flow through the runner without crashing — the runner just
  notices the change is a no-op and stamps the row.

Why not Alembic / Flyway / etc.
-------------------------------

This project uses ``mysql-connector`` with hand-written SQL, not
SQLAlchemy ORM models. Bolting Alembic on for two columns/quarter
would add ~50 MB of deps and a whole new mental model. The runner
here is ~100 lines and covers everything we need today; if we ever
want true rollbacks, branching migrations, or data-aware Python
migrations, we can graduate then.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from mysql.connector import Error as MySQLError

logger = logging.getLogger(__name__)

# `backend/db/migrations/` — sibling of `backend/db/init/`.
_MIGRATIONS_DIR = (
    Path(__file__).resolve().parents[2] / "db" / "migrations"
)

# MySQL error codes that mean "this DDL is a no-op against the
# current schema state" — i.e. the migration is already effectively
# applied (a fresh install whose `001_schema.sql` already produced the
# post-migration shape, or an operator who ran the SQL manually
# before the runner shipped). Treat as success and still record the
# migration so future boots skip it.
_ALREADY_APPLIED_ERRNOS = {
    1060,  # ER_DUP_FIELDNAME           — column already exists
    1061,  # ER_DUP_KEYNAME             — key/index already exists
    1091,  # ER_CANT_DROP_FIELD_OR_KEY  — column/key to drop is missing
}

# Filename pattern: 4-digit zero-padded version + underscore +
# snake_case description + .sql. Anything else (README.md, .DS_Store,
# editor swap files) is ignored so the directory can host docs.
_FILENAME_RE = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


def apply_pending_migrations(cursor: Any) -> int:
    """Apply every `backend/db/migrations/*.sql` not yet recorded.

    Returns the number of migrations newly applied. Logs each one.
    Safe to call on every boot — idempotent both at the file level
    (already-recorded migrations skipped) and at the SQL level
    (already-applied DDL swallowed via the 1060/1061/1091 codes).
    """
    if not _MIGRATIONS_DIR.is_dir():
        logger.debug(
            "No migrations directory at %s — nothing to apply.",
            _MIGRATIONS_DIR,
        )
        return 0

    candidates = sorted(
        p for p in _MIGRATIONS_DIR.iterdir()
        if p.is_file() and _FILENAME_RE.match(p.name)
    )
    if not candidates:
        return 0

    _ensure_schema_migrations_table(cursor)
    cursor.execute("SELECT version FROM schema_migrations")
    applied = {str(row[0]) for row in cursor.fetchall() or ()}

    new_count = 0
    for migration_file in candidates:
        version = migration_file.stem  # e.g. "0001_add_apple_sub_to_users"
        if version in applied:
            continue
        _apply_one_migration(cursor, migration_file, version)
        new_count += 1

    if new_count:
        logger.info("Schema migrations: applied %d new file(s)", new_count)
    return new_count


def _ensure_schema_migrations_table(cursor: Any) -> None:
    """Create the bookkeeping table on first run. Idempotent."""
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            `version`    VARCHAR(255) NOT NULL,
            `applied_at` TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (`version`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
        """
    )


def _apply_one_migration(cursor: Any, path: Path, version: str) -> None:
    """Run every statement in `path`, then record `version` as applied.

    DDL in MySQL implicitly commits each statement, so "transactional"
    is a misnomer here — what we get instead is per-statement progress
    plus error-swallowing on the codes that mean "already applied".
    """
    statements = _split_sql(path.read_text(encoding="utf-8"))
    if not statements:
        logger.info("Migration %s is empty — recording as applied.", version)
        _record_applied(cursor, version)
        return

    logger.info("Applying migration %s (%d statement(s))", version, len(statements))
    for stmt in statements:
        try:
            cursor.execute(stmt)
        except MySQLError as exc:
            errno = getattr(exc, "errno", None)
            if errno in _ALREADY_APPLIED_ERRNOS:
                logger.info(
                    "  ↻ skipped statement (MySQL %d, already applied): %s",
                    errno,
                    _summarize(stmt),
                )
                continue
            logger.exception(
                "Migration %s failed at statement: %s",
                version,
                _summarize(stmt),
            )
            raise
    _record_applied(cursor, version)


def _record_applied(cursor: Any, version: str) -> None:
    """Insert the version row; `INSERT IGNORE` so a re-run is a no-op."""
    cursor.execute(
        "INSERT IGNORE INTO schema_migrations (`version`) VALUES (%s)",
        (version,),
    )


def _split_sql(text: str) -> list[str]:
    """Split a SQL file into individual statements.

    Reuses the same tiny parser as
    `schema_bootstrap.split_sql_statements`: strip ``--`` line
    comments + blank lines, then split on top-level ``;``. Migrations
    should stick to plain DDL — anything with embedded semicolons
    (triggers, stored procedures) needs a beefier parser, which we
    don't have a use case for yet.
    """
    cleaned: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("--") or not stripped:
            continue
        cleaned.append(line)
    joined = "\n".join(cleaned)
    return [s.strip() for s in joined.split(";") if s.strip()]


def _summarize(stmt: str) -> str:
    """One-line preview of a statement for log lines."""
    flat = " ".join(stmt.split())
    return flat if len(flat) <= 120 else flat[:117] + "..."


__all__ = ["apply_pending_migrations"]
