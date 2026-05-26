"""User repository helpers: upsert on login, lookup by id."""

from __future__ import annotations

from dataclasses import dataclass

from app.auth.apple import AppleIdentity
from app.auth.google import GoogleIdentity
from app.db.db import Database


@dataclass(frozen=True)
class User:
    id: int
    google_sub: str | None
    apple_sub: str | None
    email: str
    name: str | None
    picture_url: str | None


_USER_COLUMNS = "id, google_sub, apple_sub, email, name, picture_url"


def get_user_by_id(user_id: int) -> User | None:
    """Lookup a user by primary key. Returns None if not found."""
    query = f"SELECT {_USER_COLUMNS} FROM users WHERE id = %s"
    with Database() as cursor:
        cursor.execute(query, (user_id,))
        row = cursor.fetchone()
    return _row_to_user(row) if row else None


def get_user_by_email(email: str) -> User | None:
    """Lookup a user by lowercased email."""
    query = f"SELECT {_USER_COLUMNS} FROM users WHERE email = %s"
    with Database() as cursor:
        cursor.execute(query, (email.lower(),))
        row = cursor.fetchone()
    return _row_to_user(row) if row else None


def upsert_user_from_google(identity: GoogleIdentity) -> User:
    """Insert (or refresh) the user row tied to a verified Google identity.

    Re-uses an existing row when we've seen the same `google_sub` or email
    before. Google's `sub` is the stable identifier across email changes
    so we match on that first, then fall back to email.
    """
    email = identity.email.lower()

    with Database() as cursor:
        cursor.execute(
            "SELECT id FROM users WHERE google_sub = %s OR email = %s LIMIT 1",
            (identity.sub, email),
        )
        row = cursor.fetchone()

        if row is None:
            cursor.execute(
                """
                INSERT INTO users (google_sub, email, name, picture_url)
                VALUES (%s, %s, %s, %s)
                """,
                (identity.sub, email, identity.name, identity.picture),
            )
        else:
            cursor.execute(
                """
                UPDATE users
                SET google_sub  = %s,
                    email       = %s,
                    name        = COALESCE(%s, name),
                    picture_url = COALESCE(%s, picture_url)
                WHERE id = %s
                """,
                (identity.sub, email, identity.name, identity.picture, row[0]),
            )

        cursor.execute(
            f"SELECT {_USER_COLUMNS} FROM users WHERE google_sub = %s",
            (identity.sub,),
        )
        refreshed = cursor.fetchone()

    assert refreshed is not None, "user row disappeared mid-upsert"
    return _row_to_user(refreshed)


class AppleIdentityWithoutLinkError(Exception):
    """Raised when an Apple sign-in arrives with no email *and* no
    pre-existing user row matching the Apple `sub`.

    In practice this should never happen — Apple always provides
    `email` on the *first* authorization for a given app+user pair,
    so by the time we'd see a token without email we should already
    have a user row keyed off the same `sub`. If we ever do hit
    this path the user can recover by going to Settings → Apple ID
    → Sign In with Apple → time2leave → "Stop Using Apple ID",
    which forces Apple to re-issue the email next sign-in.
    """


def upsert_user_from_apple(
    identity: AppleIdentity,
    *,
    name: str | None = None,
) -> User:
    """Insert (or refresh) the user row tied to a verified Apple identity.

    Resolution order, highest priority first:
      1. Existing row with the same `apple_sub`. This is the
         steady-state path — we set `last_login_at` (via the timestamp
         column's ON UPDATE), refresh the email if Apple supplied one
         this time, and persist the name if the client sent it (which
         only happens on the first sign-in).
      2. Existing row with the same email (cross-provider link). Lets
         a user who first signed in with Google adopt Apple Sign In
         later without becoming a duplicate row. We attach `apple_sub`
         to that row.
      3. New row with `apple_sub` + email. Requires email — see
         `AppleIdentityWithoutLinkError`.

    `name` is sourced from the iOS client's
    `AppleAuthentication.signInAsync` response (only populated on
    first sign-in by Apple's privacy design); it isn't carried in
    the identity token itself, which is why it's a separate kwarg
    instead of a field on `AppleIdentity`.
    """
    apple_sub = identity.sub
    email = identity.email  # may be None after first sign-in

    with Database() as cursor:
        # Try the apple_sub match first (steady state).
        cursor.execute(
            "SELECT id FROM users WHERE apple_sub = %s LIMIT 1",
            (apple_sub,),
        )
        row = cursor.fetchone()

        if row is None and email is not None:
            # Cross-provider link by email.
            cursor.execute(
                "SELECT id FROM users WHERE email = %s LIMIT 1",
                (email,),
            )
            row = cursor.fetchone()

        if row is None:
            if email is None:
                raise AppleIdentityWithoutLinkError(
                    "Apple identity has no email and no "
                    "matching apple_sub on file"
                )
            cursor.execute(
                """
                INSERT INTO users (apple_sub, email, name)
                VALUES (%s, %s, %s)
                """,
                (apple_sub, email, name),
            )
        else:
            # Refresh the row. Email only updates when Apple actually
            # sends one this round; otherwise we keep what's stored.
            # `name` is COALESCE'd so a re-login (which never carries
            # a name) doesn't blow away the name we captured on the
            # first sign-in.
            cursor.execute(
                """
                UPDATE users
                SET apple_sub = %s,
                    email     = COALESCE(%s, email),
                    name      = COALESCE(%s, name)
                WHERE id = %s
                """,
                (apple_sub, email, name, row[0]),
            )

        cursor.execute(
            f"SELECT {_USER_COLUMNS} FROM users WHERE apple_sub = %s",
            (apple_sub,),
        )
        refreshed = cursor.fetchone()

    assert refreshed is not None, "user row disappeared mid-upsert"
    return _row_to_user(refreshed)


def delete_user(user_id: int) -> bool:
    """Hard-delete a user row and everything that hangs off it.

    Returns True if a row was deleted, False if no row matched
    (idempotent — the caller can keep retrying without a separate
    "still there?" probe).

    `users.id` is the FK target of three CASCADE relationships
    (`trips`, `trip_mutation_log`, `commute_samples` via `trips`),
    so a single DELETE on this table atomically removes the user's
    trips, their per-week commute samples, and their mutation
    audit log — i.e. every row in the database that's tied to them.

    Auth-state implications worth knowing:
      * Existing session JWTs (cookie + bearer) keep their crypto
        signature valid until `exp`, but `get_optional_user` does
        a `get_user_by_id` lookup on every request and returns
        None when the row is gone — so a stale token degrades to
        anonymous (401 on protected routes) immediately, without
        needing a server-side blocklist.
      * The user can re-sign-in with the same email + provider
        and we'll INSERT a new row with a fresh `id`. The
        previous trips / samples / audit log do NOT come back —
        that's the point of "delete my account".
      * The email stays on `auth_allowlist` (which is gated by
        the operator, not by user action), so a deleted user
        who's still on the allowlist can re-create their account
        on next sign-in. Deliberate — allowlist management is an
        operator's job, not a self-service path.
    """
    with Database() as cursor:
        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        return cursor.rowcount > 0


def _row_to_user(row: tuple) -> User:
    return User(
        id=int(row[0]),
        google_sub=row[1],
        apple_sub=row[2],
        email=row[3],
        name=row[4],
        picture_url=row[5],
    )
