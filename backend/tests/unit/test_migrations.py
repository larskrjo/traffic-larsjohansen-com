"""Unit tests for app.db.migrations — the schema-migration runner.

These tests live next to `test_schema_bootstrap.py` because the runner
is part of the same boot-time schema-management pipeline: every call
to `ensure_schema()` now also calls `apply_pending_migrations()`.

The runner has three subtle behaviours that we lock in with tests so
the next session can't regress them silently:

  1. **Discovery.** Only `NNNN_*.sql` files are picked up, sorted
     numerically. Garbage in the directory (README.md, .DS_Store,
     editor swap files) is ignored.
  2. **Idempotence.** A migration already recorded in
     `schema_migrations` is skipped. Running twice in a row is a
     no-op on the second pass.
  3. **Already-applied SQL swallow.** MySQL errors 1060 (column
     already exists), 1061 (index already exists), and 1091 (DROP
     target missing) are swallowed and the migration is still
     recorded as applied — this is what lets a brand-new install
     (whose `001_schema.sql` already produced the post-migration
     shape) flow through the runner cleanly.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from mysql.connector import Error as MySQLError

from app.db import migrations as migrations_mod
from app.db.migrations import apply_pending_migrations


# ----------------------------------------------------------------------
# A reusable cursor mock that tracks the "applied" set so the test can
# assert end-state instead of micro-managing every fetchall return value.
# ----------------------------------------------------------------------


class FakeCursor:
    """Just enough of a DB-API cursor to drive the runner.

    Records every `execute()` call so tests can assert what SQL ran,
    and keeps an in-memory `schema_migrations` table for the
    `INSERT IGNORE` + `SELECT version` round trip the runner makes.
    Errors can be queued via `queue_error()` so we can simulate the
    MySQL 1060 / 1061 codes.
    """

    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple | None]] = []
        self._applied: set[str] = set()
        self._next_errors: dict[str, MySQLError] = {}

    def queue_error(self, sql_substring: str, err: MySQLError) -> None:
        self._next_errors[sql_substring] = err

    def execute(self, sql: str, params: tuple | None = None) -> None:
        self.executed.append((sql, params))
        # Simulate MySQL errors when a queued substring matches.
        for needle, err in list(self._next_errors.items()):
            if needle in sql:
                del self._next_errors[needle]
                raise err
        # Track applied migrations so SELECT/INSERT round-trip works.
        s = sql.strip().upper()
        if s.startswith("INSERT IGNORE INTO SCHEMA_MIGRATIONS") and params:
            self._applied.add(params[0])

    def fetchall(self) -> list[tuple]:
        # The runner does exactly one SELECT — return what we have.
        return [(v,) for v in sorted(self._applied)]


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _write_migration(dirpath: Path, name: str, sql: str) -> Path:
    f = dirpath / name
    f.write_text(sql, encoding="utf-8")
    return f


def _redirect_migrations_dir(monkeypatch, tmp_path: Path) -> Path:
    """Point the runner at a throwaway directory under tmp_path."""
    target = tmp_path / "migrations"
    target.mkdir()
    monkeypatch.setattr(migrations_mod, "_MIGRATIONS_DIR", target)
    return target


# ----------------------------------------------------------------------
# Discovery
# ----------------------------------------------------------------------


def test_runs_files_in_numeric_order(monkeypatch, tmp_path):
    """Files apply in NNNN order, not in OS-glob order."""
    d = _redirect_migrations_dir(monkeypatch, tmp_path)
    # Intentionally out-of-order on disk.
    _write_migration(d, "0003_third.sql",  "CREATE TABLE c (id INT);")
    _write_migration(d, "0001_first.sql",  "CREATE TABLE a (id INT);")
    _write_migration(d, "0002_second.sql", "CREATE TABLE b (id INT);")
    cursor = FakeCursor()

    applied = apply_pending_migrations(cursor)

    assert applied == 3
    # Filter out the bookkeeping `CREATE TABLE schema_migrations` so we
    # only inspect statements from the migration files themselves.
    create_table_sql = [
        s for s, _ in cursor.executed
        if "CREATE TABLE" in s and "schema_migrations" not in s
    ]
    assert create_table_sql == [
        "CREATE TABLE a (id INT)",
        "CREATE TABLE b (id INT)",
        "CREATE TABLE c (id INT)",
    ]
    # All three versions stamped.
    inserts = [
        params[0] for s, params in cursor.executed
        if s.strip().upper().startswith("INSERT IGNORE INTO SCHEMA_MIGRATIONS")
    ]
    assert inserts == ["0001_first", "0002_second", "0003_third"]


def test_ignores_non_migration_files(monkeypatch, tmp_path):
    """README.md, .DS_Store, etc. don't get treated as migrations."""
    d = _redirect_migrations_dir(monkeypatch, tmp_path)
    _write_migration(d, "0001_real.sql", "CREATE TABLE a (id INT);")
    _write_migration(d, "README.md", "# docs")
    _write_migration(d, ".DS_Store", "garbage")
    _write_migration(d, "abc_not_numbered.sql", "DROP DATABASE oops;")
    _write_migration(d, "01_too_few_digits.sql", "DROP DATABASE oops;")
    cursor = FakeCursor()

    applied = apply_pending_migrations(cursor)

    assert applied == 1
    sql_run = [s for s, _ in cursor.executed]
    assert "DROP DATABASE oops" not in " ".join(sql_run)


def test_no_migrations_dir_is_a_no_op(monkeypatch, tmp_path):
    monkeypatch.setattr(
        migrations_mod, "_MIGRATIONS_DIR", tmp_path / "does-not-exist"
    )
    cursor = FakeCursor()
    assert apply_pending_migrations(cursor) == 0
    assert cursor.executed == []


# ----------------------------------------------------------------------
# Idempotence
# ----------------------------------------------------------------------


def test_already_applied_migrations_are_skipped(monkeypatch, tmp_path):
    d = _redirect_migrations_dir(monkeypatch, tmp_path)
    _write_migration(d, "0001_a.sql", "CREATE TABLE a (id INT);")
    _write_migration(d, "0002_b.sql", "CREATE TABLE b (id INT);")
    cursor = FakeCursor()
    cursor._applied.add("0001_a")  # pretend 0001 already shipped

    applied = apply_pending_migrations(cursor)

    assert applied == 1
    create_sql = [
        s for s, _ in cursor.executed
        if "CREATE TABLE" in s and "schema_migrations" not in s
    ]
    assert create_sql == ["CREATE TABLE b (id INT)"]


def test_second_run_is_a_no_op(monkeypatch, tmp_path):
    d = _redirect_migrations_dir(monkeypatch, tmp_path)
    _write_migration(d, "0001_a.sql", "CREATE TABLE a (id INT);")
    cursor = FakeCursor()

    first = apply_pending_migrations(cursor)
    cursor.executed.clear()  # only inspect what the SECOND call does
    second = apply_pending_migrations(cursor)

    assert first == 1
    assert second == 0
    assert not any(
        "CREATE TABLE a" in s for s, _ in cursor.executed
    )


# ----------------------------------------------------------------------
# Already-applied SQL: the 1060 / 1061 / 1091 swallow
# ----------------------------------------------------------------------


def _mysql_error(errno: int, msg: str = "") -> MySQLError:
    err = MySQLError(msg=msg or f"errno {errno}")
    err.errno = errno
    return err


def test_swallows_duplicate_column_error_and_records_migration(
    monkeypatch, tmp_path
):
    """ER_DUP_FIELDNAME (1060) means the column already exists.

    This is the brand-new-install path: `001_schema.sql` already
    produced `apple_sub`, so when the runner tries to ADD COLUMN it
    crashes with 1060. We swallow + still record the migration, so
    subsequent boots are a fast skip.
    """
    d = _redirect_migrations_dir(monkeypatch, tmp_path)
    _write_migration(
        d, "0001_x.sql", "ALTER TABLE users ADD COLUMN x INT;"
    )
    cursor = FakeCursor()
    cursor.queue_error("ADD COLUMN x INT", _mysql_error(1060))

    applied = apply_pending_migrations(cursor)

    assert applied == 1
    assert "0001_x" in cursor._applied


def test_swallows_duplicate_key_error(monkeypatch, tmp_path):
    """ER_DUP_KEYNAME (1061) means the index already exists."""
    d = _redirect_migrations_dir(monkeypatch, tmp_path)
    _write_migration(
        d, "0001_idx.sql", "ALTER TABLE users ADD UNIQUE KEY uniq_x (x);"
    )
    cursor = FakeCursor()
    cursor.queue_error("ADD UNIQUE KEY uniq_x", _mysql_error(1061))

    apply_pending_migrations(cursor)

    assert "0001_idx" in cursor._applied


def test_swallows_missing_drop_target(monkeypatch, tmp_path):
    """ER_CANT_DROP_FIELD_OR_KEY (1091): DROP target already gone."""
    d = _redirect_migrations_dir(monkeypatch, tmp_path)
    _write_migration(
        d, "0001_drop.sql", "ALTER TABLE users DROP COLUMN legacy;"
    )
    cursor = FakeCursor()
    cursor.queue_error("DROP COLUMN legacy", _mysql_error(1091))

    apply_pending_migrations(cursor)

    assert "0001_drop" in cursor._applied


def test_real_error_propagates_and_migration_not_recorded(
    monkeypatch, tmp_path
):
    """Errors OUTSIDE the safe-swallow set abort the boot.

    Critical: if SQL fails for a *real* reason (typo, FK violation,
    DB out of disk space) we must NOT record the migration as
    applied — otherwise the next boot would skip it and the schema
    stays broken silently. Crashing on boot is the loud signal we
    want.
    """
    d = _redirect_migrations_dir(monkeypatch, tmp_path)
    _write_migration(
        d, "0001_bad.sql", "ALTER TABLE users DO_SOMETHING_INVALID;"
    )
    cursor = FakeCursor()
    cursor.queue_error(
        "DO_SOMETHING_INVALID",
        _mysql_error(1064, "syntax error"),  # 1064 = ER_PARSE_ERROR
    )

    with pytest.raises(MySQLError):
        apply_pending_migrations(cursor)

    assert "0001_bad" not in cursor._applied


# ----------------------------------------------------------------------
# Multi-statement files
# ----------------------------------------------------------------------


def test_multi_statement_migration_runs_each_statement(
    monkeypatch, tmp_path
):
    """Each top-level `;` is its own execute() call.

    The Apple-Sign-In migration is exactly this shape: MODIFY +
    ADD COLUMN + ADD UNIQUE KEY. If we batched them into one ALTER
    a partial-overlap state (column exists, key missing) would
    abort the whole statement.
    """
    d = _redirect_migrations_dir(monkeypatch, tmp_path)
    _write_migration(d, "0001_three.sql", """
        ALTER TABLE users MODIFY COLUMN google_sub VARCHAR(255) DEFAULT NULL;
        ALTER TABLE users ADD COLUMN apple_sub VARCHAR(255) DEFAULT NULL;
        ALTER TABLE users ADD UNIQUE KEY uniq_apple (apple_sub);
    """)
    cursor = FakeCursor()
    # Half-applied state: column exists, index doesn't.
    cursor.queue_error("ADD COLUMN apple_sub", _mysql_error(1060))

    apply_pending_migrations(cursor)

    sqls = [s for s, _ in cursor.executed if s.strip().startswith("ALTER")]
    assert len(sqls) == 3
    assert "MODIFY COLUMN google_sub" in sqls[0]
    assert "ADD COLUMN apple_sub" in sqls[1]
    assert "ADD UNIQUE KEY uniq_apple" in sqls[2]
    assert "0001_three" in cursor._applied
