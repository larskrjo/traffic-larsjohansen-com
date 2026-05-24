"""Apply table DDL from `db/init/001_schema.sql` at app startup.

The schema is authored to be idempotent (every `CREATE TABLE` uses
`IF NOT EXISTS`), so we can safely run it on every boot. That buys us:

  * Prod cutovers: pointing `MYSQL_DATABASE` at a freshly-created
    database (e.g. operator runs `CREATE DATABASE time2leave;`) no
    longer needs a separate schema-apply step. The app creates the
    tables itself on first boot.
  * Dev resilience: adding a new table no longer requires `make clean`
    to wipe the MySQL volume and re-run the container's
    `/docker-entrypoint-initdb.d` scripts.

Contract: **the database itself must already exist.** Creating it is
the operator's job (in dev: docker-mysql does it from `MYSQL_DATABASE`;
in prod: a one-time `CREATE DATABASE` by whoever has root). The app
user from AWS Secrets Manager only needs DDL on tables inside that
database, not the global `CREATE` privilege. We strip any
`CREATE DATABASE` / `USE` statements out of the schema before
executing — they're kept in the file for human readers and for
docker-mysql's first-boot path.

We intentionally do NOT apply the `002_seed.sql` fixture from here —
that's local-dev data (a hardcoded `dev@example.com` user plus 840
fixture commute samples) and has no business in prod.
"""

from __future__ import annotations

import logging
import secrets
from pathlib import Path
from typing import Any

import mysql.connector
from mysql.connector import Error as MySQLError

from app.config import Settings, get_settings
from app.db.migrations import apply_pending_migrations

logger = logging.getLogger(__name__)

_SCHEMA_FILE = (
    Path(__file__).resolve().parents[2] / "db" / "init" / "001_schema.sql"
)


_SKIP_PREFIXES = ("CREATE DATABASE", "USE ")


def split_sql_statements(text: str) -> list[str]:
    """Split a semicolon-delimited SQL file into individual statements.

    The parser is intentionally minimal: it strips line comments
    (`-- ...`) and blank lines, then splits on `;`. It doesn't handle
    semicolons inside string literals, stored procedures, or triggers
    — none of which appear in `001_schema.sql`.
    """
    cleaned: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("--") or not stripped:
            continue
        cleaned.append(line)
    joined = "\n".join(cleaned)
    return [s.strip() for s in joined.split(";") if s.strip()]


def _table_only_statements(text: str) -> list[str]:
    """Drop `CREATE DATABASE` / `USE` lines; the DB is the operator's job."""
    return [
        s
        for s in split_sql_statements(text)
        if not s.upper().lstrip().startswith(_SKIP_PREFIXES)
    ]


def _connect(settings: Settings) -> Any:
    """Open a connection scoped to the configured database."""
    return mysql.connector.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_database,
        autocommit=True,
    )


def ensure_schema(settings: Settings | None = None) -> None:
    """Apply the table DDL to MySQL. Idempotent and safe to retry.

    The target database (`settings.mysql_database`) must already exist;
    we connect with `database=...` and only run the table-level DDL.
    After the DDL we run any in-place column migrations that the
    `CREATE TABLE IF NOT EXISTS` statements can't apply (because the
    table already exists from a previous boot).
    """
    settings = settings or get_settings()
    if not _SCHEMA_FILE.exists():
        logger.warning(
            "Schema file %s not found; skipping schema bootstrap", _SCHEMA_FILE
        )
        return

    statements = _table_only_statements(_SCHEMA_FILE.read_text())
    if not statements:
        return

    logger.info(
        "Applying schema from %s (%d statements) to %s@%s:%s/%s",
        _SCHEMA_FILE.name,
        len(statements),
        settings.mysql_user,
        settings.mysql_host,
        settings.mysql_port,
        settings.mysql_database,
    )
    conn = _connect(settings)
    try:
        cursor = conn.cursor()
        try:
            for stmt in statements:
                cursor.execute(stmt)
            _ensure_trips_slug_column(cursor)
            # Apply any pending file-based migrations (see
            # `backend/db/migrations/` and the workflow rule in
            # `.cursor/rules/db-schema-via-migrations.mdc`). This is
            # what makes schema additions safe to deploy: any
            # ALTER recorded in a migration file gets applied
            # exactly once on each database that doesn't already
            # have the change.
            apply_pending_migrations(cursor)
        finally:
            cursor.close()
    finally:
        conn.close()
    logger.info(
        "Schema bootstrap complete; %s is ready", settings.mysql_database
    )


# ---------------------------------------------------------------------------
# In-place migrations
#
# `CREATE TABLE IF NOT EXISTS` is a no-op when the table already exists, so
# any new columns added after first deploy need a separate migration step.
# Each helper here is idempotent: it inspects information_schema before
# touching anything.
# ---------------------------------------------------------------------------


_SLUG_HEX_BYTES = 5  # 5 bytes → 10 lowercase hex chars, like a git short SHA.


def _generate_slug() -> str:
    return secrets.token_hex(_SLUG_HEX_BYTES)


def _column_exists(cursor: Any, table: str, column: str) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = %s
          AND column_name = %s
        LIMIT 1
        """,
        (table, column),
    )
    return cursor.fetchone() is not None


def _ensure_trips_slug_column(cursor: Any) -> None:
    """Add `trips.slug` (+ unique index) to a pre-existing trips table.

    Three-phase migration so we never have a window with a NOT NULL
    column that some rows can't satisfy:

      1. ADD COLUMN nullable.
      2. Backfill every NULL row with a fresh random slug, retrying on
         the (vanishingly rare) UNIQUE collision.
      3. MODIFY COLUMN to NOT NULL and add the UNIQUE index.

    For a brand-new database the `CREATE TABLE` in 001_schema.sql
    already has all of this, and `_column_exists(...)` returns True,
    so this whole function is a cheap no-op.
    """
    if _column_exists(cursor, "trips", "slug"):
        return

    logger.info("Adding `trips.slug` column (in-place migration)")
    cursor.execute(
        "ALTER TABLE trips ADD COLUMN `slug` VARCHAR(16) NULL AFTER `id`"
    )

    cursor.execute("SELECT id FROM trips WHERE slug IS NULL")
    rows = cursor.fetchall() or []
    pending_ids = [int(r[0]) for r in rows]
    if pending_ids:
        logger.info("Backfilling slugs for %d existing trip(s)", len(pending_ids))
        for trip_id in pending_ids:
            _assign_random_slug(cursor, trip_id)

    cursor.execute(
        "ALTER TABLE trips MODIFY COLUMN `slug` VARCHAR(16) NOT NULL"
    )
    cursor.execute(
        "ALTER TABLE trips ADD UNIQUE KEY `uniq_trips_slug` (`slug`)"
    )
    logger.info("`trips.slug` migration complete")


_MAX_SLUG_RETRIES = 8


def _assign_random_slug(cursor: Any, trip_id: int) -> None:
    """Pick a random slug and write it to one row, retrying on collision.

    A 10-hex-char slug has ~1.1e12 possibilities; collisions in the
    backfill set are statistically impossible at our trip volumes.
    The retry loop is here purely as a defense in depth so a single
    unlucky hash never aborts the migration.
    """
    for _ in range(_MAX_SLUG_RETRIES):
        candidate = _generate_slug()
        try:
            cursor.execute(
                "UPDATE trips SET slug = %s WHERE id = %s",
                (candidate, trip_id),
            )
            return
        except MySQLError as exc:
            # Duplicate-key on slug → try again. Anything else propagates.
            if getattr(exc, "errno", None) != 1062:
                raise
    raise RuntimeError(
        f"Exhausted slug-generation retries for trip {trip_id}; "
        "is the slug column constrained correctly?"
    )
