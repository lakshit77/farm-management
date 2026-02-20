# Postgres / Supabase Best Practices Review

This document reviews the **showgroundlive_monitoring** project against the [Supabase Postgres Best Practices](https://supabase.com/docs/guides/database) skill (query performance, connection management, schema design, data access patterns).

**Stack:** PostgreSQL via SQLAlchemy 2.0 (async, `postgresql+asyncpg`). The database may be Supabase-hosted or any Postgres instance.

---

## What’s already in good shape

- **Schema & identifiers:** Table and column names are lowercase/snake_case; no quoted mixed-case identifiers.
- **Foreign key indexes (most tables):** Initial migration indexes FK columns used in JOINs/filters (e.g. `entries.horse_id`, `entries.show_id`, `entries.class_id`, `horses.farm_id`, etc.).
- **N+1 avoidance:** Services use `selectinload()` for relations (e.g. `class_monitoring`, `schedule_view`, `horse_availability`, `notification_log`) instead of lazy loading in loops.
- **Batch writes:** `bulk_upsert_entries` uses a single `INSERT ... ON CONFLICT` per batch (with-class and no-class), not row-by-row inserts.
- **Notification log queries:** `notification_log` has a composite index `(farm_id, created_at DESC)` matching the main list query.
- **Connection pool:** `pool_size=5`, `max_overflow=10`, `pool_pre_ping=True` are set in `app/core/database.py`.
- **Partial unique indexes:** Entries use correct partial unique constraints for upsert (`api_class_id IS NOT NULL` and `api_class_id IS NULL`).

---

## Issues and recommended changes

### 1. **Index on `farms` – not needed**

**Where:** `get_farm_by_name_and_customer()` filters by `name` and `customer_id`. With only a handful of farms (e.g. ≤5 rows), a full table scan is negligible.

**Decision:** No index added. Add one later only if the farms table grows significantly (e.g. tens/hundreds of rows).

---

### 2. **Missing FK indexes on `horse_location_history` (HIGH – JOINs / CASCADE)**

**Skill rule:** [schema-foreign-key-indexes](https://www.postgresql.org/docs/current/ddl-constraints.html#DDL-CONSTRAINTS-FK).

**Where:** Table has FKs: `horse_id`, `location_id`, `show_id`, `event_id`, `class_id`, `entry_id`. Only `horse_id` (and composite `horse_id, timestamp`) are indexed.

**Impact:** JOINs or CASCADE deletes from `locations`, `shows`, `events`, `classes`, or `entries` will scan `horse_location_history` without an index.

**Change:** Add indexes on `location_id`, `show_id`, `event_id`, `class_id`, `entry_id`. See migration below.

---

### 3. **Connection pool: add `pool_recycle` (MEDIUM – connection management)**

**Skill rule:** [conn-pooling](https://supabase.com/docs/guides/database/connecting-to-postgres#connection-pooler), [conn-idle-timeout](https://www.postgresql.org/docs/current/runtime-config-client.html#GUC-IDLE-IN-TRANSACTION-SESSION-TIMEOUT).

**Where:** `app/core/database.py` – engine has no `pool_recycle` (or equivalent).

**Impact:** If the server or Supabase closes idle connections, the pool can keep connections that are already closed, leading to errors. Recycling connections after a max lifetime avoids that.

**Change:** Set `pool_recycle=600` (or 300–900 seconds) so connections are recycled periodically. See code change below.

---

### 4. **Optional: index on `notification_log.entry_id` (LOW–MEDIUM)**

**Skill rule:** Index foreign key columns for JOINs and CASCADE.

**Where:** `notification_log` has FK `entry_id` but no index on it.

**Impact:** If you ever query “all notifications for this entry” or if CASCADE from `entries` touches this table, an index helps. Current main query is by `farm_id` + `created_at`, which is already indexed.

**Change:** Add `CREATE INDEX idx_notification_log_entry_id ON notification_log(entry_id);` if you add entry-scoped queries or want faster CASCADE. Omitted from the migration below; add when needed.

---

### 5. **Pagination: OFFSET vs cursor (LOW for current usage)**

**Skill rule:** [data-pagination](https://supabase.com/docs/guides/database/pagination).

**Where:** `get_recent_notifications()` uses `LIMIT`/`OFFSET`.

**Impact:** For “recent 50” with small offset this is fine. For very deep pagination (e.g. offset 5000+), OFFSET gets slower.

**Change:** Only if you later support deep pagination (e.g. “load more” many times). Then switch to keyset/cursor pagination on `(created_at DESC, id)`.

---

### 6. **Primary key choice: UUID v4 (LOW – acceptable for current scale)**

**Skill rule:** [schema-primary-keys](https://www.postgresql.org/docs/current/sql-createtable.html#SQL-CREATETABLE-PARMS-GENERATED-IDENTITY).

**Where:** All tables use `uuid_generate_v4()` / `uuid.uuid4()` (random UUIDs).

**Impact:** Random UUIDs can increase index fragmentation and cache pressure on very large, write-heavy tables. For typical farm/schedule sizes this is usually acceptable.

**Change:** Optional long-term improvement: consider UUIDv7 (or time-ordered IDs) for new tables if you see fragmentation or need sortable IDs. No change required for current scope.

---

## Summary

| Area                | Status   | Action                                      |
|---------------------|----------|---------------------------------------------|
| Indexes (farms)     | Skip     | ≤5 rows; full scan fine, no index needed    |
| Indexes (horse_loc) | Missing  | Add FK indexes on `horse_location_history`  |
| Connection pool     | Improve  | Add `pool_recycle` in `database.py`         |
| N+1 / batch         | Good     | No change                                   |
| Schema / naming     | Good     | No change                                   |
| Pagination          | OK       | Consider cursor later if deep pagination    |
| PK strategy         | OK       | Optional UUIDv7 for new tables later        |

Implementing the high-impact index and pool changes is recommended; the rest can be done when you add new features or scale.

---

## What is connection pooling?

**Problem:** Every time your app runs a query, it needs a **connection** to the database. Opening a new connection is expensive: Postgres has to authenticate, allocate memory (often 1–3 MB per connection), and set up session state. If 100 requests hit your API at once and each opens its own connection, you get 100 connections — and Postgres has a limited number it can handle (often in the hundreds). Too many connections slow or crash the database.

**What pooling does:** Instead of “one request = one new connection,” the app uses a **pool** of a fixed number of connections (e.g. 5–20). When a request needs the DB, it **borrows** a connection from the pool, runs the query, then **returns** the connection to the pool. The next request reuses that same connection. So 100 concurrent requests can share 5–10 actual connections instead of opening 100.

**In this project:** `app/core/database.py` uses SQLAlchemy’s pool: `pool_size=5`, `max_overflow=10`. So you have at most 15 connections to Postgres, no matter how many concurrent API calls. `pool_pre_ping=True` checks that a connection is still alive before use (avoids “connection closed” errors). `pool_recycle=600` returns connections to the pool after 10 minutes so they don’t get killed by the server’s idle timeout and then reused as “stale” connections.
