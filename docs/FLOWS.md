# Horse Farm Management System - Flows Documentation

## Overview

This document describes all automated flows that power the Horse Farm Management System.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         CRON TRIGGERS                                │
├─────────────────────────────────────────────────────────────────────┤
│  6:00 AM     │  Every 10 min  │  Every 30 min  │  7:00 PM          │
│  Flow 1      │  Flow 2        │  Flow 5        │  Flow 4           │
└──────┬───────┴───────┬────────┴───────┬────────┴───────┬───────────┘
       │               │                │                │
       ▼               ▼                ▼                ▼
┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│   Morning   │ │    Class    │ │  Reminders  │ │   Daily     │
│    Sync     │ │  Monitoring │ │             │ │  Summary    │
└──────┬──────┘ └──────┬──────┘ └─────────────┘ └─────────────┘
       │               │
       │               ▼
       │        ┌─────────────┐
       │        │    Horse    │ ← Triggered when horse completes
       │        │ Availability│
       │        └─────────────┘
       │               │
       ▼               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         DATABASE                                     │
│  farms │ horses │ riders │ shows │ events │ classes │ entries       │
└─────────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      TELEGRAM NOTIFICATIONS                          │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Flow Summary

| Flow | Name | Trigger | Frequency | Purpose |
|------|------|---------|-----------|---------|
| 1 | Morning Sync | Cron | 6:00 AM daily | Load schedule & entries |
| 2 | Class Monitoring | Cron | Every 10 minutes | Track changes & results |
| 3 | Horse Availability | Event | On horse completion | Calculate free time |
| 4 | Daily Summary | Cron | 7:00 PM daily | End-of-day report |
| 5 | Reminders | Cron | Every 30 minutes | Upcoming class alerts |

---

## Flow 1: Daily Morning Sync

### Purpose
Load today's complete schedule and all horse entries from the API into the database.

### Trigger
- **Type:** Cron
- **Schedule:** 6:00 AM daily

### Input
- `farm_id` — The farm to sync
- `customer_id` — API customer ID
- `date` — Today's date

### Steps

#### Step 1: Get Schedule for Today

**API Call:**
```
GET /schedule?date={today}&customer_id={customer_id}
```

**Response Contains:**
- `show` — Show information
- `rings[]` — List of rings with their classes

**Extract:**
```json
{
    "show": {
        "show_id": 200000050,
        "show_name": "2026 WEF 6",
        "start_date": "2026-02-10",
        "end_date": "2026-02-15"
    },
    "rings": [
        {
            "ring_id": 51,
            "ring_name": "International Ring",
            "ring_number": 1,
            "classes": [...]
        }
    ]
}
```

---

#### Step 2: Upsert Show

**Logic:**
```
Check if show exists by api_show_id:
  - EXISTS → Update name, dates
  - NOT EXISTS → Insert new show

Return show UUID
```

**SQL:**
```sql
INSERT INTO shows (farm_id, api_show_id, name, start_date, end_date)
VALUES ($farm_id, $api_show_id, $name, $start_date, $end_date)
ON CONFLICT (farm_id, api_show_id)
DO UPDATE SET 
    name = EXCLUDED.name,
    start_date = EXCLUDED.start_date,
    end_date = EXCLUDED.end_date,
    updated_at = NOW()
RETURNING id
```

---

#### Step 3: Upsert Events (Rings)

**Logic:**
```
FOR EACH ring IN schedule.rings:
    Check if event exists by NAME:
      - EXISTS → Update ring_number
      - NOT EXISTS → Insert new event
    
    Store mapping: api_ring_id → event_uuid
```

**SQL:**
```sql
INSERT INTO events (farm_id, name, ring_number)
VALUES ($farm_id, $ring_name, $ring_number)
ON CONFLICT (farm_id, name)
DO UPDATE SET 
    ring_number = EXCLUDED.ring_number,
    updated_at = NOW()
RETURNING id
```

**Output:** Map of `api_ring_id → event_uuid`

---

#### Step 4: Upsert Classes

**Logic:**
```
FOR EACH ring IN schedule.rings:
    FOR EACH class IN ring.classes:
        Check if class exists by NAME:
          - EXISTS → Update sponsor, prize_money
          - NOT EXISTS → Insert new class
        
        Store mapping: api_class_id → class_uuid
```

**SQL:**
```sql
INSERT INTO classes (farm_id, name, class_number, sponsor, prize_money, class_type)
VALUES ($farm_id, $class_name, $class_number, $sponsor, $prize_money, $class_type)
ON CONFLICT (farm_id, name)
DO UPDATE SET 
    sponsor = EXCLUDED.sponsor,
    prize_money = EXCLUDED.prize_money,
    updated_at = NOW()
RETURNING id
```

**Output:** Map of `api_class_id → class_uuid`

---

#### Step 5: Get My Entries

**API Call:**
```
GET /entries/my?show_id={api_show_id}&customer_id={customer_id}
```

**Response Contains:**
- `entries[]` — List of all horse entries for this show

**Extract:**
```json
{
    "entries": [
        {
            "entry_id": 200143927,
            "horse_id": 131897,
            "horse": "OSTWIND 59",
            "number": 1105,
            "trainer_id": 13724
        }
    ],
    "total_entries": 85
}
```

---

#### Step 6: For Each Entry → Get Entry Details

**API Call (per entry):**
```
GET /entries/{entry_id}?show_id={api_show_id}&customer_id={customer_id}
```

**Response Contains:**
- `entry` — Entry details with horse, trainer, owner
- `classes[]` — Classes this horse is entered in
- `entry_riders[]` — Riders for this entry

**Extract:**
```json
{
    "entry": {
        "entry_id": 200143927,
        "horse_id": 131897,
        "horse": "OSTWIND 59",
        "trainer_id": 13724,
        "trainer": "EMILY SMITH"
    },
    "classes": [
        {
            "class_id": 200019819,
            "class_number": 1095,
            "name": "1.25m Schooling Jumper",
            "rider_id": 67418,
            "rider_name": "JORDAN GIBBS",
            "ring": 7,
            "scheduled_date": "2026-02-11",
            "schedule_starttime": "11:50:05"
        }
    ],
    "entry_riders": [
        {
            "rider_id": 67418,
            "rider_name": "JORDAN GIBBS"
        }
    ]
}
```

---

#### Step 7: Upsert Horse & Rider

**Logic:**
```
// Upsert Horse (match by NAME)
horse_uuid = INSERT INTO horses (farm_id, name)
             ON CONFLICT (farm_id, name) DO NOTHING
             RETURNING id

// Upsert Rider (match by NAME)
rider_uuid = INSERT INTO riders (farm_id, name)
             ON CONFLICT (farm_id, name) DO NOTHING
             RETURNING id
```

---

#### Step 8: Create Entries

**Logic:**
```
FOR EACH class_entry IN entry_detail.classes:
    
    // Get internal UUIDs from mappings
    event_uuid = ring_mapping[class_entry.ring]
    class_uuid = class_mapping[class_entry.class_id]
    
    // Parse estimated_start
    estimated_start = scheduled_date + schedule_starttime
    
    // Insert/Update entry
    INSERT INTO entries (
        horse_id,
        rider_id,
        show_id,
        event_id,
        class_id,
        api_entry_id,
        api_horse_id,
        api_rider_id,
        api_class_id,
        api_ring_id,
        api_trainer_id,
        back_number,
        scheduled_date,
        estimated_start,
        status,
        class_status
    ) VALUES (
        $horse_uuid,
        $rider_uuid,
        $show_uuid,
        $event_uuid,
        $class_uuid,
        $api_entry_id,
        $api_horse_id,
        $api_rider_id,
        $api_class_id,
        $api_ring_id,
        $api_trainer_id,
        $back_number,
        $scheduled_date,
        $estimated_start,
        NULL,           -- status: will be set by Flow 2
        NULL            -- class_status: will be set by Flow 2
    )
    ON CONFLICT (horse_id, show_id, api_class_id)
    DO UPDATE SET
        rider_id = EXCLUDED.rider_id,
        estimated_start = EXCLUDED.estimated_start,
        updated_at = NOW()
```

---

#### Step 9: Send Telegram Summary

**Message:**
```
📅 Today's Schedule - {date}

🐴 Horses: {unique_horse_count}
🎯 Classes: {total_class_entries}
🏟️ Rings: {unique_ring_count}

First class: {earliest_time} - {ring_name}
Last class: {latest_time} - {ring_name}

Show: {show_name}
```

---

### Output
- Database populated with today's schedule
- All entries created for today
- Telegram summary sent

---

## Flow 2: Class Monitoring

### Purpose
Monitor active classes for changes and send real-time alerts.

### Trigger
- **Type:** Cron
- **Schedule:** Every 10 minutes

### Input
- `farm_id` — The farm to monitor
- `customer_id` — API customer ID

### Steps

#### Step 1: Get Active Entries for Today

**Query incomplete classes:**
```sql
SELECT DISTINCT 
    api_class_id,
    api_show_id,
    show_id,
    class_id,
    event_id,
    class_status
FROM entries e
JOIN shows s ON e.show_id = s.id
WHERE e.scheduled_date = CURRENT_DATE
  AND (e.class_status IS NULL OR e.class_status != 'Completed')
  AND e.farm_id = $farm_id
```

**Output:** List of `api_class_id` values to monitor

---

#### Step 2: For Each Class → Call Class API

**API Call:**
```
GET /classes/{api_class_id}?show_id={api_show_id}&customer_id={customer_id}
```

**Response Contains:**
- `class` — Class metadata
- `class_related_data` — Status, times, progress
- `trips[]` — All horse performances

**Extract:**
```json
{
    "class_related_data": {
        "status": "Completed",
        "estimated_time": "07:15:00",
        "actual_time": "07:20:00",
        "total_trips": 12,
        "completed_trips": 12,
        "remaining_trips": 0,
        "ring_name": "International Ring"
    },
    "trips": [
        {
            "entry_id": 200143927,
            "horse": "OSTWIND 59",
            "trip_id": 200283381,
            "order_of_go": 9,
            "placing": 1,
            "faults_one": 0,
            "time_one": 45.23,
            "faults_two": 0,
            "time_two": 32.15,
            "total_prize_money": 45,
            "points_earned": 5,
            "gone_in": 1,
            "scratch_trip": 0,
            "disqualify_status_one": "",
            "disqualify_status_two": ""
        }
    ]
}
```

---

#### Step 3: Find Our Horses in Trips

**Query our entries:**
```sql
SELECT * FROM entries 
WHERE api_class_id = $api_class_id
  AND show_id = $show_id
```

**Match with API trips:**
```
FOR EACH our_entry IN db_entries:
    matching_trip = api_trips.find(t => t.entry_id == our_entry.api_entry_id)
```

---

#### Step 4: Compare & Detect Changes

**Change Detection Logic:**
```python
changes = []

# Get current DB values for this class
db_entry = first_entry_for_class  # Use any entry since class-level data is same

# ============ CLASS-LEVEL CHANGES ============

# Status Change
if api.class_related_data.status != db_entry.class_status:
    changes.append({
        'type': 'STATUS_CHANGE',
        'old': db_entry.class_status,
        'new': api.class_related_data.status,
        'class_name': class_name
    })

# Time Change
api_estimated = parse_time(api.class_related_data.estimated_time)
if api_estimated != db_entry.estimated_start:
    changes.append({
        'type': 'TIME_CHANGE',
        'old': db_entry.estimated_start,
        'new': api_estimated,
        'class_name': class_name
    })

# Progress Change
if api.class_related_data.completed_trips != db_entry.completed_trips:
    changes.append({
        'type': 'PROGRESS_UPDATE',
        'completed': api.class_related_data.completed_trips,
        'total': api.class_related_data.total_trips,
        'class_name': class_name
    })

# ============ ENTRY-LEVEL CHANGES (for our horses) ============

FOR EACH our_entry, matching_trip IN matched_pairs:
    
    # Result Posted
    if matching_trip.placing != db_entry.placing:
        if matching_trip.placing > 0 and matching_trip.placing < 100000:
            changes.append({
                'type': 'RESULT',
                'horse': our_entry.horse_name,
                'placing': matching_trip.placing,
                'prize_money': matching_trip.total_prize_money,
                'class_name': class_name
            })
    
    # Horse Completed Trip
    if matching_trip.gone_in == 1 and db_entry.gone_in == False:
        changes.append({
            'type': 'HORSE_COMPLETED',
            'horse': our_entry.horse_name,
            'horse_id': our_entry.horse_id,
            'class_name': class_name
        })
    
    # Horse Scratched
    if matching_trip.scratch_trip == 1 and db_entry.scratch_trip == False:
        changes.append({
            'type': 'SCRATCHED',
            'horse': our_entry.horse_name,
            'class_name': class_name
        })
```

---

#### Step 5: Update Database

**Update each entry:**
```sql
UPDATE entries
SET
    -- Class-level data
    class_status = $api_status,
    estimated_start = $api_estimated_time,
    actual_start = $api_actual_time,
    total_trips = $api_total_trips,
    completed_trips = $api_completed_trips,
    remaining_trips = $api_remaining_trips,
    
    -- Entry-level data (from matching trip)
    api_trip_id = $trip_id,
    order_of_go = $order_of_go,
    "placing" = $placing,
    faults_one = $faults_one,
    time_one = $time_one,
    faults_two = $faults_two,
    time_two = $time_two,
    time_fault_one = $time_fault_one,
    time_fault_two = $time_fault_two,
    total_prize_money = $total_prize_money,
    points_earned = $points_earned,
    gone_in = ($gone_in = 1),
    scratch_trip = ($scratch_trip = 1),
    disqualify_status_one = $disqualify_status_one,
    disqualify_status_two = $disqualify_status_two,
    score1 = $score1,
    score2 = $score2,
    score3 = $score3,
    score4 = $score4,
    score5 = $score5,
    score6 = $score6,
    
    -- Derived status
    status = CASE
        WHEN $scratch_trip = 1 THEN 'scratched'
        WHEN $gone_in = 1 THEN 'completed'
        ELSE 'active'
    END,
    
    updated_at = NOW()
WHERE id = $entry_id
```

---

#### Step 6: Send Telegram Alerts

**Alert Templates:**

**STATUS_CHANGE (Class Started):**
```
🟢 Class Started

📋 {class_name}
📍 {ring_name}
🐴 Our horses: {horse_list}
#️⃣ Order: {order_list}
```

**STATUS_CHANGE (Class Completed):**
```
🏁 Class Completed

📋 {class_name}
📍 {ring_name}

Our Results:
{horse_results_list}
```

**TIME_CHANGE:**
```
⏰ Time Change

📋 {class_name}
📍 {ring_name}
🕐 {old_time} → {new_time}
```

**RESULT:**
```
🏆 Result!

🐴 {horse_name}
📋 {class_name}
🥇 Place: #{placing}
💰 Prize: ${prize_money}
```

**HORSE_COMPLETED:**
```
✅ Trip Completed

🐴 {horse_name}
📋 {class_name}
📊 Faults: {faults} | Time: {time}s
```

**SCRATCHED:**
```
❌ Horse Scratched

🐴 {horse_name}
📋 {class_name}
```

---

#### Step 7: Trigger Flow 3 (If Horse Completed)

**Condition:** When `gone_in` changes from `FALSE` to `TRUE`

**Call Flow 3 with:**
```json
{
    "horse_id": "uuid",
    "horse_name": "OSTWIND 59",
    "completed_class_id": "uuid",
    "show_id": "uuid"
}
```

---

### Output
- Database updated with latest class data
- Telegram alerts sent for changes
- Flow 3 triggered for completed horses

---

## Flow 3: Horse Availability Tracker

### Purpose
Calculate horse's free time and next scheduled class after completing a class.

### Trigger
- **Type:** Event (from Flow 2)
- **Condition:** Horse completes a trip (gone_in: 0 → 1)

### Input
- `horse_id` — Horse UUID
- `horse_name` — Horse name
- `completed_class_id` — Class just completed
- `show_id` — Current show UUID

### Steps

#### Step 1: Get Horse's Remaining Classes Today

**Query:**
```sql
SELECT 
    e.*,
    c.name as class_name,
    ev.name as ring_name
FROM entries e
JOIN classes c ON e.class_id = c.id
JOIN events ev ON e.event_id = ev.id
WHERE e.horse_id = $horse_id
  AND e.show_id = $show_id
  AND e.scheduled_date = CURRENT_DATE
  AND (e.class_status IS NULL OR e.class_status != 'Completed')
  AND e.gone_in = FALSE
  AND e.id != $completed_entry_id
ORDER BY e.estimated_start ASC
```

---

#### Step 2: Calculate Free Time

**Logic:**
```python
current_time = NOW()
remaining_classes = query_result

if len(remaining_classes) > 0:
    next_class = remaining_classes[0]
    free_time = next_class.estimated_start - current_time
    free_minutes = free_time.total_seconds() / 60
    free_hours = int(free_minutes / 60)
    free_mins = int(free_minutes % 60)
    
    has_next = True
else:
    has_next = False
    free_hours = None
    free_mins = None
```

---

#### Step 3: Log to Horse Location History

**Insert:**
```sql
INSERT INTO horse_location_history (
    horse_id,
    location_id,      -- Event venue location
    show_id,
    event_id,         -- Ring of completed class
    class_id,         -- Completed class
    entry_id,         -- Completed entry
    notes,
    timestamp
) VALUES (
    $horse_id,
    $venue_location_id,
    $show_id,
    $completed_event_id,
    $completed_class_id,
    $completed_entry_id,
    'Completed Class: {class_name}. Free for {hours}h {mins}m',
    NOW()
)
```

---

#### Step 4: Send Telegram Availability Update

**If has next class:**
```
🐴 {horse_name} - Trip Completed

✅ Finished: {completed_class_name}
📍 Ring: {completed_ring_name}

⏭️ Next: {next_class_name}
⏰ Time: {next_class_time}
📍 Ring: {next_ring_name}
#️⃣ Order: #{order_of_go} of {total}

⏳ Free time: {hours}h {minutes}m
```

**If no more classes today:**
```
🐴 {horse_name} - Done for Today!

✅ Finished: {completed_class_name}
📍 Ring: {completed_ring_name}

🎉 No more classes scheduled today
```

---

### Output
- Horse location history logged
- Telegram update sent with availability info

---

## Flow 4: Daily Summary Dashboard

### Purpose
Send end-of-day summary with results and statistics.

### Trigger
- **Type:** Cron
- **Schedule:** 7:00 PM daily

### Input
- `farm_id` — The farm
- `date` — Today's date

### Steps

#### Step 1: Query Today's Results

**Query:**
```sql
SELECT 
    h.name as horse,
    c.name as class,
    e."placing",
    e.total_prize_money,
    e.points_earned,
    e.faults_one,
    e.time_one,
    e.class_status
FROM entries e
JOIN horses h ON e.horse_id = h.id
JOIN classes c ON e.class_id = c.id
WHERE e.scheduled_date = CURRENT_DATE
  AND e.farm_id = $farm_id
ORDER BY e."placing" ASC NULLS LAST
```

---

#### Step 2: Calculate Statistics

**Aggregations:**
```python
total_entries = len(results)
total_horses = len(set(r.horse for r in results))
completed_classes = len([r for r in results if r.class_status == 'Completed'])
total_prize_money = sum(r.total_prize_money or 0 for r in results)
total_points = sum(r.points_earned or 0 for r in results)
placings = len([r for r in results if r.placing and r.placing <= 8])
wins = len([r for r in results if r.placing == 1])
```

---

#### Step 3: Get Tomorrow's Preview

**Query:**
```sql
SELECT COUNT(*) as class_count
FROM entries
WHERE scheduled_date = CURRENT_DATE + 1
  AND farm_id = $farm_id
```

---

#### Step 4: Send Dashboard to Telegram

**Message:**
```
📊 Daily Summary - {date}
══════════════════════════

📈 Overview
• Entries: {total_entries}
• Horses: {total_horses}
• Classes Completed: {completed_classes}
• Wins: {wins} 🏆
• Placings (Top 8): {placings}

💰 Earnings
• Prize Money: ${total_prize_money}
• Points: {total_points}

🏆 Top Results
{for each placing <= 3}
{placing_emoji} {horse} - {class} - ${prize}
{end for}

📋 All Results
{for each completed entry}
• {horse} - {class} - #{placing}
{end for}

📅 Tomorrow: {tomorrow_count} classes scheduled
```

---

### Output
- Telegram dashboard message sent

---

## Flow 5: Reminders

### Purpose
Send reminders before upcoming classes.

### Trigger
- **Type:** Cron
- **Schedule:** Every 30 minutes

### Input
- `farm_id` — The farm
- `reminder_window` — Minutes before class (default: 60)

### Steps

#### Step 1: Find Upcoming Classes

**Query:**
```sql
SELECT 
    e.*,
    h.name as horse_name,
    c.name as class_name,
    ev.name as ring_name
FROM entries e
JOIN horses h ON e.horse_id = h.id
JOIN classes c ON e.class_id = c.id
JOIN events ev ON e.event_id = ev.id
WHERE e.scheduled_date = CURRENT_DATE
  AND e.farm_id = $farm_id
  AND (e.class_status IS NULL OR e.class_status = 'Not Started')
  AND e.estimated_start BETWEEN NOW() AND NOW() + INTERVAL '60 minutes'
  AND (e.reminder_sent IS NULL OR e.reminder_sent = FALSE)
```

---

#### Step 2: Send Reminders

**For each upcoming entry:**
```python
minutes_until = (entry.estimated_start - NOW()).total_seconds() / 60

send_telegram(f"""
⏰ Upcoming Class Reminder

🐴 Horse: {horse_name}
🎯 Class: {class_name}
📍 Ring: {ring_name}
⏱️ Starting in: ~{minutes_until} minutes
#️⃣ Order: #{order_of_go} of {order_total}
""")
```

---

#### Step 3: Mark Reminder as Sent

**Update:**
```sql
UPDATE entries
SET reminder_sent = TRUE
WHERE id = $entry_id
```

**Note:** You may need to add `reminder_sent BOOLEAN DEFAULT FALSE` column to entries table.

---

### Output
- Telegram reminders sent
- Entries marked as reminded

---

## API Reference

### Endpoints Used

| Endpoint | Flow | Purpose |
|----------|------|---------|
| `GET /schedule?date={}&customer_id={}` | Flow 1 | Daily schedule |
| `GET /entries/my?show_id={}&customer_id={}` | Flow 1 | Farm's entries |
| `GET /entries/{id}?show_id={}&customer_id={}` | Flow 1 | Entry details |
| `GET /classes/{id}?show_id={}&customer_id={}` | Flow 2 | Class results |

### Base URL
```
https://sglapi.wellingtoninternational.com
```

---

## Database Tables Used

| Table | Flow 1 | Flow 2 | Flow 3 | Flow 4 | Flow 5 |
|-------|--------|--------|--------|--------|--------|
| farms | ✓ | ✓ | | ✓ | ✓ |
| horses | ✓ (upsert) | | ✓ | ✓ | ✓ |
| riders | ✓ (upsert) | | | | |
| shows | ✓ (upsert) | ✓ | ✓ | | |
| events | ✓ (upsert) | ✓ | ✓ | | ✓ |
| classes | ✓ (upsert) | ✓ | ✓ | ✓ | ✓ |
| entries | ✓ (upsert) | ✓ (update) | ✓ | ✓ | ✓ |
| horse_location_history | | | ✓ (insert) | | |

---

## Error Handling

### API Failures
- Retry 3 times with exponential backoff
- Log error and continue with next item
- Send alert if critical failure

### Database Failures
- Rollback transaction
- Log error
- Send alert

### Missing Data
- Use NULL/defaults for missing fields
- Log warning
- Continue processing

---

## Monitoring & Logging

### Log Events
- Flow start/end times
- API calls (request/response)
- Database operations
- Changes detected
- Alerts sent
- Errors

### Metrics to Track
- Flow execution duration
- API response times
- Number of changes detected per run
- Alert count per day