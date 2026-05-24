-- 0001_add_apple_sub_to_users.sql
--
-- Bring the `users` table in line with the Sign-in-with-Apple
-- feature shipped in app/services/users.py + app/auth/apple.py.
--
-- This is exactly the drift that produced the 500 on /auth/google
-- and /auth/apple on 24 May 2026: schema_bootstrap.ensure_schema()
-- only runs `CREATE TABLE IF NOT EXISTS` and therefore never adds
-- columns to an existing table. With the migration runner in place,
-- this file is what closes the gap on existing databases (prod and
-- any dev DB whose volume wasn't wiped); brand-new installs come up
-- post-migration already via 001_schema.sql and the runner just
-- records this file as applied via its 1060/1061 error-swallow.
--
-- Three operations, each as its own ALTER so the runner can swallow
-- the "already applied" error per-op (e.g., when 001_schema.sql
-- already produced the column on a fresh install but not the index,
-- or vice versa during recovery from a half-applied state):
--   1. `google_sub` was originally NOT NULL on the legacy table;
--      Apple-only sign-ins need it nullable so we can insert
--      `(apple_sub, email, name)` rows without a Google identity.
--   2. Add the `apple_sub` column itself.
--   3. Add the unique index that prevents two rows ever sharing an
--      Apple subject identifier.

ALTER TABLE users
    MODIFY COLUMN `google_sub` varchar(255) DEFAULT NULL;

ALTER TABLE users
    ADD COLUMN `apple_sub` varchar(255) DEFAULT NULL AFTER `google_sub`;

ALTER TABLE users
    ADD UNIQUE KEY `uniq_users_apple_sub` (`apple_sub`);
