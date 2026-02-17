# Horse Farm Management System (Showground Live Monitoring)

A system for managing a **horse farm's** participation at **equestrian shows**: it loads today's schedule and your farm's entries from an external API (Wellington / Showground Live), stores them in a database, and monitors classes throughout the day—detecting when classes start, when results are posted, when horses complete or get scratched—and can send real-time alerts (e.g. Telegram).

This README explains **what the project does**, **domain terminology**, **what data we store**, **how flows work**, and **how we expose that data**. For detailed flow steps and API contracts, see [docs/FLOWS.md](docs/FLOWS.md).

---

## Table of Contents

- [What Is This Domain?](#what-is-this-domain)
- [Terminology Glossary](#terminology-glossary)
- [Flow Overview](#flow-overview)
- [Flow 1: Morning Sync — What We Load and Store](#flow-1-morning-sync--what-we-load-and-store)
- [Flow 2: Class Monitoring — What We Do and Change](#flow-2-class-monitoring--what-we-do-and-change)
- [Database: Tables, Columns, and Possible Values](#database-tables-columns-and-possible-values)
- [How We Show the Database (Schedule View)](#how-we-show-the-database-schedule-view)
- [Quick Reference: Entry Status and Class Status](#quick-reference-entry-status-and-class-status)
- [Further Reading](#further-reading)

---

## What Is This Domain?

The domain is **horse show / farm management**:

- A **farm** (e.g. a stable) competes at **equestrian shows** (e.g. "2026 WEF 6" at Wellington International).
- The system tracks **which horses** from the farm are entered in **which classes** at the show.
- It knows **when** those classes run and **how each horse did** (order of go, faults, time, placing, prize money, scratched, etc.).
- It can send **alerts** when something changes (class started, result posted, horse scratched).

Data is pulled from the **Wellington** (Showground Live) API; we store our own copy and update it via **Flow 1** (morning sync) and **Flow 2** (class monitoring).

---

## Terminology Glossary

| Term | Meaning |
|------|--------|
| **Farm** | Your stable or organization. The system is multi-tenant: each farm has its own horses, riders, and data. |
| **Show** | A competition event (e.g. "2026 WEF 6") with a start and end date. |
| **Ring** | A physical arena at the show. In the database this is stored as an **Event** (e.g. "International Ring", "Ring 7"). |
| **Class** | A single competition within a ring (e.g. "1.25m Schooling Jumper", "$15,000 Junior Jumper"). It has a number, optional sponsor, prize money, and type (e.g. jumper vs hunter). |
| **Entry** | One horse entered in **one class**. So: "Horse OSTWIND 59 in class 1.25m Schooling Jumper on 2026-02-11." An entry links: horse, rider, show, ring (event), class, plus all result/status fields. |
| **Trip** | One horse's performance in that class (one "round"). The external API calls it a "trip"; we store trip-related data on the **Entry** (e.g. `api_trip_id`, faults, time, placing). |
| **Order of go** | The order in which horses go in that class (e.g. 9th to go). |
| **Back number** | The number the horse wears at the show (e.g. 1105). |
| **Placing** | Final position (1st, 2nd, …). We treat **100000** as "unplaced" (per API convention). |
| **Scratched** | The horse was withdrawn from that class (did not compete). |
| **Gone in** | The horse has completed its round (went in the ring and finished). |

---

## Flow Overview

| Flow | Name | Trigger | Purpose |
|------|------|---------|---------|
| 1 | Morning Sync | 6:00 AM daily | Load today's schedule and all horse entries from the API into the database. |
| 2 | Class Monitoring | Every 10 minutes | Monitor active classes for changes (status, time, results, scratches) and update the database; produce alerts. |
| 3 | Horse Availability | On horse completion | Calculate horse's free time and next class (placeholder). |
| 4 | Daily Summary | 7:00 PM daily | End-of-day report. |
| 5 | Reminders | Every 30 minutes | Upcoming class alerts. |

---

## Flow 1: Morning Sync — What We Load and Store

**When:** 6:00 AM daily (cron).

**What it does:** For "today", it fetches the **schedule** and **your farm's entries** from the Wellington API and writes them into our database. After Flow 1, the DB has:

- The **show** (name, dates).
- All **rings** (events) and **classes** that appear in the schedule.
- All **horses** and **riders** that appear in your entries (matched by name).
- One **entry** per (horse, class) for today: when the class is, which ring, rider, back number, etc. At this point we do **not** yet have results; those come from Flow 2.

**What is stored:** farms, shows, events (rings), classes, horses, riders, and **entries** with schedule data and API IDs. Result/status fields on entries are left for Flow 2 to fill.

---

## Flow 2: Class Monitoring — What We Do and Change

**When:** Every 10 minutes (cron).

**What it does:**

1. Finds **today's entries** in classes that are **not yet completed**.
2. For each such class, calls the Wellington API to get current class status and all **trips** (performances).
3. Matches **our** entries to the API trips (by `api_entry_id`).
4. **Compares** API data to DB and detects: class status/time/progress changes, and for our horses: result posted, horse completed (`gone_in`), horse scratched.
5. **Updates the database:** for each of our entries in that class we overwrite class-level fields (e.g. `class_status`, `estimated_start`, `completed_trips`) and entry-level result fields (placing, faults, times, `gone_in`, `scratch_trip`, etc.), and set **entry status** to `active` | `completed` | `scratched` based on `scratch_trip` and `gone_in`.
6. Returns **changes** and **alerts** (e.g. for Telegram). Flow 3 trigger (horse availability) is a placeholder.

**What changes:** Only the **entries** table: we refresh class-level and result columns and set `status` from the API and from `scratch_trip` / `gone_in`.

---

## Database: Tables, Columns, and Possible Values

### Table: **farms**

| Column | Type | Meaning | Notes |
|--------|------|---------|-------|
| `id` | UUID | Primary key | Generated. |
| `name` | string | Farm display name | e.g. "My Stable". |
| `customer_id` | integer (nullable) | Wellington API customer ID | Used in API calls. |
| `settings` | JSONB (nullable) | Extra config | Optional. |
| `created_at`, `updated_at` | timestamps | Audit | Set by DB. |

---

### Table: **shows**

| Column | Type | Meaning | Notes |
|--------|------|---------|-------|
| `id` | UUID | Primary key | Generated. |
| `farm_id` | UUID | Farm | FK to `farms.id`. |
| `api_show_id` | integer (nullable) | Wellington show ID | Unique per show; used for API. |
| `name` | string | Show name | e.g. "2026 WEF 6". |
| `start_date`, `end_date` | date (nullable) | Show dates | YYYY-MM-DD. |
| `venue` | string (nullable) | Venue name | Optional. |
| `is_active` | boolean | Whether show is active | Default true. |
| `metadata` | JSONB (nullable) | Extra data | Optional. |
| `created_at`, `updated_at` | timestamps | Audit | Set by DB. |

---

### Table: **events** (rings)

| Column | Type | Meaning | Notes |
|--------|------|---------|-------|
| `id` | UUID | Primary key | Generated. |
| `farm_id` | UUID | Farm | FK to `farms.id`. |
| `name` | string | Ring name | e.g. "International Ring". Matched by name on upsert. |
| `ring_number` | integer (nullable) | Ring number at venue | e.g. 1, 7. |
| `description` | text (nullable) | Optional description | Optional. |
| `created_at`, `updated_at` | timestamps | Audit | Set by DB. |

---

### Table: **classes** (show classes)

| Column | Type | Meaning | Notes |
|--------|------|---------|-------|
| `id` | UUID | Primary key | Generated. |
| `farm_id` | UUID | Farm | FK to `farms.id`. |
| `name` | string | Class name | e.g. "1.25m Schooling Jumper". Matched by name (+ class_number) on upsert. |
| `class_number` | string (nullable) | Class number | e.g. "1095". |
| `sponsor` | string (nullable) | Sponsor name | Optional. |
| `prize_money` | decimal (nullable) | Prize money | e.g. 15000.00. |
| `class_type` | string (nullable) | Type of class | e.g. jumper vs hunter; free-form. |
| `jumper_table` | string (nullable) | Jumper table type | Optional. |
| `metadata` | JSONB (nullable) | Extra data | Optional. |
| `created_at`, `updated_at` | timestamps | Audit | Set by DB. |

---

### Table: **horses**

| Column | Type | Meaning | Notes |
|--------|------|---------|-------|
| `id` | UUID | Primary key | Generated. |
| `farm_id` | UUID | Farm | FK to `farms.id`. |
| `name` | string | Horse name | e.g. "OSTWIND 59". Matched by name on sync. |
| `status` | string | Horse status | Default `"active"`. |
| `metadata` | JSONB (nullable) | Extra data | Optional. |
| `created_at`, `updated_at` | timestamps | Audit | Set by DB. |

---

### Table: **riders**

| Column | Type | Meaning | Notes |
|--------|------|---------|-------|
| `id` | UUID | Primary key | Generated. |
| `farm_id` | UUID | Farm | FK to `farms.id`. |
| `name` | string | Rider name | e.g. "JORDAN GIBBS". Matched by name on sync. |
| `country` | string (nullable) | Country | Optional. |
| `metadata` | JSONB (nullable) | Extra data | Optional. |
| `created_at`, `updated_at` | timestamps | Audit | Set by DB. |

---

### Table: **entries** (main “what’s happening today” table)

An **entry** = one horse in one class for one show (and thus one ring, one rider). All API IDs for the show are stored here.

**Internal links (UUIDs):**

| Column | Type | Meaning |
|--------|------|---------|
| `id` | UUID | Primary key. |
| `horse_id` | UUID | Horse (FK to `horses.id`). |
| `rider_id` | UUID (nullable) | Rider (FK to `riders.id`). |
| `show_id` | UUID (nullable) | Show (FK to `shows.id`). |
| `event_id` | UUID (nullable) | Ring (FK to `events.id`). |
| `class_id` | UUID (nullable) | Class (FK to `classes.id`). |

**API IDs (for syncing and API calls):**

| Column | Type | Meaning |
|--------|------|---------|
| `api_entry_id` | int (nullable) | Wellington entry ID. |
| `api_horse_id` | int (nullable) | Wellington horse ID. |
| `api_rider_id` | int (nullable) | Wellington rider ID. |
| `api_class_id` | int (nullable) | Wellington class ID. |
| `api_ring_id` | int (nullable) | Wellington ring ID. |
| `api_trip_id` | int (nullable) | Wellington trip ID (set by Flow 2). |
| `api_trainer_id` | int (nullable) | Wellington trainer ID. |

**Entry-level info:**

| Column | Type | Meaning | Possible values / notes |
|--------|------|---------|--------------------------|
| `back_number` | string (nullable) | Number on horse's back | e.g. "1105". |
| `order_of_go` | int (nullable) | Order in class | 1, 2, 3, … |
| `order_total` | int (nullable) | Total number of horses in class | Optional. |

**Status (entry-level):**

| Column | Type | Meaning | Possible values |
|--------|------|---------|-----------------|
| `status` | string | **Derived** entry state | `"active"` (still to go), `"completed"` (gone in), `"scratched"` (withdrawn). Set by Flow 2 from `scratch_trip` and `gone_in`. |
| `scratch_trip` | boolean | Horse scratched from this class | `true` / `false`. |
| `gone_in` | boolean | Horse has completed its round | `true` / `false`. |

**Class-level (duplicated per entry; updated by Flow 2):**

| Column | Type | Meaning | Possible values / notes |
|--------|------|---------|--------------------------|
| `estimated_start` | string (nullable) | When class estimated to start | e.g. "2026-02-11 11:50:05" (stored as string). |
| `actual_start` | string (nullable) | When class actually started | Same format. |
| `scheduled_date` | date (nullable) | Day of class | YYYY-MM-DD. |
| `class_status` | string (nullable) | **Class** status from API | e.g. `"Completed"`, or other API values (e.g. started, in progress). We only treat `"Completed"` specially (stop monitoring). |
| `ring_status` | string (nullable) | Ring status from API | Optional. |
| `total_trips` | int (nullable) | Total trips in class | From API. |
| `completed_trips` | int (nullable) | Trips completed so far | From API. |
| `remaining_trips` | int (nullable) | Trips left | From API. |

**Results:**

| Column | Type | Meaning | Possible values / notes |
|--------|------|---------|--------------------------|
| `placing` | int (nullable) | Final position | 1, 2, 3, …; **100000** = unplaced (per API). |
| `points_earned` | decimal (nullable) | Points | Optional. |
| `total_prize_money` | decimal (nullable) | Prize money | Optional. |

**Round 1 (e.g. jumpers):** `faults_one`, `time_one`, `time_fault_one`, `disqualify_status_one`.

**Round 2 / jump-off:** `faults_two`, `time_two`, `time_fault_two`, `disqualify_status_two`.

**Hunter scores (6 judges):** `score1` … `score6` (decimal, nullable).

**Audit:** `created_at`, `updated_at`.

---

### Other tables

- **locations** — Physical or event venues; `type` is e.g. `"physical"` or `"event_venue"`.
- **horse_location_history** — Tracks horse movements (used by Flow 3); links horse, location, show, event, class, entry, notes, timestamp.

---

## How We Show the Database (Schedule View)

We don’t expose raw tables. We expose a **schedule view** built from the DB:

- **API:** e.g. `GET /schedule/view?date=YYYY-MM-DD` (see `app/api/v1/endpoints/schedule.py` and `app/services/schedule_view.py`).
- **Logic:** Load entries for that date for your farm (via `FARM_NAME` and `CUSTOMER_ID`), with relations (horse, rider, event, show, show_class). Build a nested structure: **events (rings) → classes → entries**.
- **Payload:** Root has `date`, `show_name`, `show_id`, and `events[]`. Each event has `id`, `name`, `ring_number`, and `classes[]`. Each class has `id`, `name`, `class_number`, `sponsor`, `prize_money`, `class_type`, and `entries[]`. Each entry includes horse (id, name, status), rider (id, name), and all the entry/class/result fields we store (back_number, order_of_go, status, scratch_trip, gone_in, estimated_start, actual_start, class_status, placing, faults, times, scores, etc.) as defined in `app/schemas/schedule_view.py`.

So “how we show the database” is: **one nested tree per day — rings → classes → entries with horse, rider, and all status/result fields** for the front-end to display.

---

## Quick Reference: Entry Status and Class Status

**Entry `status`** (derived by Flow 2):

| Value | Meaning |
|-------|---------|
| `active` | Horse has not yet gone in; not scratched. |
| `completed` | Horse has completed its round (`gone_in` = true). |
| `scratched` | Horse was scratched from this class. |

**Entry `class_status`** (from API, class-level):

| Value | Meaning |
|-------|---------|
| `Completed` | Class is finished; we stop monitoring this class. |
| (other) | e.g. not started, in progress; we keep monitoring. |

**Placing:** `1`, `2`, `3`, … = position; **`100000`** = unplaced (per API).

---

## Further Reading

- **[docs/FLOWS.md](docs/FLOWS.md)** — Detailed flow steps, API request/response examples, SQL, and alert templates.
- **[docs/API_USAGE.md](docs/API_USAGE.md)** — API-related information (endpoints, request/response formats, usage).
- **Backend:** FastAPI app in `app/`; models in `app/models/`, services in `app/services/`, API routes in `app/api/`.
- **Front-end:** See `front-end/` for the schedule UI.
