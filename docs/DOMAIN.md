# Horse Farm Management System - Domain Knowledge

## Overview

This system helps horse farms manage their horses' participation in equestrian shows/competitions. It monitors schedules, tracks horse activities, and sends real-time notifications via Telegram.

---

## The Business Context

### What is a Horse Farm?

A horse farm (or stable) owns/manages multiple horses that compete in equestrian shows. The farm has:
- **Horses** - The animals that compete
- **Riders** - People who ride the horses in competition
- **Trainers** - People who train horses and coordinate entries
- **Staff** - People who need to know where horses are and when they compete

### The Problem We're Solving

During a multi-day show:
- Horses compete in multiple classes across different rings
- Schedules change frequently (delays, time shifts)
- Staff needs to know when to prepare horses
- Management wants to track results and performance
- Everyone needs real-time updates

**Currently:** Staff manually checks websites, emails, and apps constantly.

**Our Solution:** Automated monitoring system that syncs with show APIs and sends Telegram alerts.

---

## Key Domain Terminology

### Show

A **Show** is a multi-day equestrian competition/event.

| Attribute | Example |
|-----------|---------|
| Name | "2026 WEF 6 (#200) CSI3* WCHR IDA Development" |
| Duration | February 10 - February 15 (6 days) |
| Venue | Wellington International |
| API ID | 200000050 (same for all days) |

**Key Point:** One show spans multiple days. The `show_id` remains the same throughout.

```
SHOW: WEF 6 (Feb 10-15)
├── Day 1 (Feb 10): 45 classes across 5 rings
├── Day 2 (Feb 11): 52 classes across 5 rings
├── Day 3 (Feb 12): 48 classes across 5 rings
└── ... continues until Feb 15
```

---

### Ring (Event)

A **Ring** is a physical arena/location where classes take place.

| Attribute | Example |
|-----------|---------|
| Name | "International Ring", "Grand Hunter Ring", "Denemethy" |
| Ring Number | 1, 2, 3, 4, 5, 7 |

A show venue has multiple rings operating simultaneously. Each ring runs different classes throughout the day.

```
Show Venue
├── Ring 1: International Ring
│   ├── 7:00 AM - Class 2401
│   ├── 9:00 AM - Class 2402
│   └── 11:00 AM - Class 2403
├── Ring 2: Grand Hunter Ring
│   ├── 7:15 AM - Class 1095
│   └── 10:00 AM - Class 1096
└── Ring 7: Schooling Ring
    └── 8:00 AM - Class 3001
```

**Note:** In our system, we call rings "Events" in the database.

---

### Class

A **Class** is a specific competition within a show.

| Attribute | Example |
|-----------|---------|
| Name | "$150 Green Conformation Hunter Model" |
| Class Number | 2401 |
| Type | Hunters, Jumpers |
| Sponsor | "Griffis Residential" |
| Prize Money | $150 total |
| Scheduled Time | 7:15 AM |
| Ring | International Ring |

**Types of Classes:**

| Type | Description |
|------|-------------|
| **Hunters** | Judged on style, form, and movement |
| **Jumpers** | Timed event, judged on faults and speed |

**Class Status Lifecycle:**
```
Not Started → In Progress → Completed
```

---

### Entry

An **Entry** is a horse's registration for a show.

When a farm registers a horse for a show:
- Horse gets a **back number** (e.g., 1105)
- Entry is associated with a trainer
- Horse can be entered into multiple classes

| Attribute | Example |
|-----------|---------|
| Entry ID | 200143927 |
| Horse | OSTWIND 59 |
| Back Number | 1105 |
| Show | WEF 6 |
| Trainer | EMILY SMITH |

```
Entry: OSTWIND 59 (#1105) at WEF 6
├── Class 1: 1.25m Schooling Jumper (Feb 11)
├── Class 2: $150 Green Hunter (Feb 11)
├── Class 3: Junior Jumper (Feb 12)
└── Class 4: Grand Prix (Feb 14)
```

---

### Trip

A **Trip** is a horse's single performance/run in a class.

When a horse enters the ring, performs, and exits — that's one trip.

| Attribute | Example |
|-----------|---------|
| Trip ID | 200283381 |
| Order of Go | 9 (goes 9th out of 12) |
| Faults | 0 |
| Time | 45.23 seconds |
| Placing | 1st |
| Prize Money | $45 |

**Trip Lifecycle:**
```
Waiting → In Ring → Completed
         (gone_in: 0)  (gone_in: 1)
```

**Class Progress Example:**
```
Class: 1.25m Jumper (12 horses)

#  | Horse        | Status      | Faults | Time  | Place
---|--------------|-------------|--------|-------|------
1  | LUCKY YOU    | Completed   | 4      | 52.1  | 8th
2  | VIRTUE       | Scratched   | -      | -     | DNS
3  | TIMELESS     | Completed   | 0      | 48.3  | 3rd
4  | SAMBA        | In Ring     | -      | -     | -
5  | LONDON PARK  | Waiting     | -      | -     | -
...
12 | CAROSELLO    | Waiting     | -      | -     | -

total_trips: 12
completed_trips: 3
remaining_trips: 8
```

---

### Rider

A **Rider** is the person who rides the horse during a class.

| Attribute | Example |
|-----------|---------|
| Name | JORDAN GIBBS |
| Country | USA |

**Note:** The same horse may have different riders for different classes.

---

### Trainer

A **Trainer** manages horses and coordinates entries.

| Attribute | Example |
|-----------|---------|
| Name | EMILY SMITH |
| Trainer ID | 13724 |

A trainer typically manages multiple horses for a farm.

---

## Relationships

```
FARM
 │
 ├── HORSES (many)
 │     └── Participate in → ENTRIES
 │
 ├── RIDERS (many)
 │     └── Ride in → ENTRIES
 │
 └── Competes at → SHOWS
                    │
                    ├── Has → RINGS (Events)
                    │
                    └── Has → CLASSES
                              │
                              └── Contains → TRIPS (performances)
```

### One-to-Many Relationships

| Parent | Child | Meaning |
|--------|-------|---------|
| Farm | Horses | A farm has many horses |
| Farm | Riders | A farm has many riders |
| Show | Classes | A show has many classes |
| Class | Trips | A class has many trips (one per horse) |
| Horse | Entries | A horse can have many entries across shows |
| Entry | Trips | An entry can have trips in multiple classes |

---

## Scoring

### Jumper Classes

Scored on **faults** (penalties) and **time**.

| Fault Type | Penalty |
|------------|---------|
| Rail down | 4 faults |
| Refusal | 4 faults |
| Fall | Elimination |
| Time fault | 1 fault per second over time allowed |

**Jump-Off:** If multiple horses have 0 faults in Round 1, they compete in a timed jump-off (faster wins).

```
Round 1: Clear round?
├── No (faults) → Placing based on faults
└── Yes (0 faults) → Goes to Jump-Off
                      └── Fastest clean round wins
```

### Hunter Classes

Scored on **style and form** (subjective judging).

| Criteria | Description |
|----------|-------------|
| Movement | Smooth, even pace |
| Jumping Style | Clean, round arc |
| Manners | Calm, obedient behavior |

Judges give scores (0-100), and placings are based on total scores.

---

## API IDs Behavior

**Critical Understanding:** API IDs change per show!

| Entity | API ID Behavior |
|--------|-----------------|
| Show | `show_id` is unique per show ✓ |
| Horse | `horse_id` changes each show ✗ |
| Rider | `rider_id` changes each show ✗ |
| Class | `class_id` changes each show ✗ |
| Ring | `ring_id` changes each show ✗ |

**Example:**
```
Horse "OSTWIND 59" at WEF 5: horse_id = 98765
Horse "OSTWIND 59" at WEF 6: horse_id = 131897  (different!)
```

**Solution:** Match entities by **NAME**, store API IDs only in entries table.

---

## Data Sources

### ShowGroundsLive API

The show management platform providing real-time data.

| API | Purpose | Data Returned |
|-----|---------|---------------|
| `/schedule` | Daily schedule | Show, rings, classes, times |
| `/entries/my` | Farm's entries | All horse registrations |
| `/entries/{id}` | Entry detail | Horse, rider, classes enrolled |
| `/classes/{id}` | Class detail | Status, trips, results |

---

## System Goals

### 1. Automated Sync
- Pull schedule daily
- Load all farm entries
- Keep database updated

### 2. Real-Time Monitoring
- Track class progress
- Detect time changes
- Capture results immediately

### 3. Telegram Notifications
- Schedule updates
- Time changes
- Class starts/completions
- Results and placings
- Horse availability

### 4. Horse Tracking
- Know where each horse is
- Calculate free time between classes
- Track next upcoming class

### 5. Daily Summaries
- Morning schedule overview
- Evening results dashboard
- Performance statistics

---

## Example Day Flow

```
6:00 AM  │ System runs Morning Sync
         │ → Loads today's schedule
         │ → Sends Telegram: "Today: 5 horses, 12 classes"
         │
7:00 AM  │ Class 2401 starts
         │ → System detects status change
         │ → Sends: "🟢 Class 2401 started - OSTWIND goes #9"
         │
7:45 AM  │ OSTWIND completes trip
         │ → System detects gone_in = 1
         │ → Sends: "✅ OSTWIND finished, next class at 11:30"
         │
8:00 AM  │ Class 2401 completes
         │ → System detects results
         │ → Sends: "🏆 OSTWIND placed 1st - $45"
         │
         │ ... continues throughout day ...
         │
7:00 PM  │ System runs Daily Summary
         │ → Sends: "📊 Today: 3 wins, $540 earned"
```

---

## Glossary

| Term | Definition |
|------|------------|
| **Back Number** | Horse's identification number for a show (e.g., 1105) |
| **Class** | A specific competition event |
| **Entry** | Horse's registration for a show |
| **Faults** | Penalties in jumper classes |
| **Gone In** | Horse has completed their performance |
| **Jump-Off** | Tiebreaker round for clear rounds |
| **Order of Go** | Sequence in which horses perform |
| **Placing** | Final rank in a class (1st, 2nd, etc.) |
| **Ring** | Physical arena where classes occur |
| **Scratch** | Withdrawal from a class |
| **Show** | Multi-day competition event |
| **Trip** | One horse's performance in a class |
| **WEF** | Winter Equestrian Festival (major show series) |
