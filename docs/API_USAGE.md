# Horse Farm Management System - API Documentation

## Overview

This document describes all APIs used by the Horse Farm Management System to interact with ShowGroundsLive.

---

## Base URL

```
https://sglapi.wellingtoninternational.com
```

---

## Authentication

All APIs require authentication using a Bearer token obtained from the Login API.

### Required Headers

All requests (including login) must include the **Origin** header; otherwise the server may respond with 401 Unauthorized.

```
Origin: https://www.wellingtoninternational.com
```

For authenticated endpoints, also include:

```
Authorization: Bearer {access_token}
```

### Token Usage

Include the token in all API requests:
```
Authorization: Bearer {access_token}
```

### Token Expiration

When token expires, call the Login API again to get a new token. There is no refresh token endpoint.

---

## API Summary

| # | API | Method | Purpose | Auth Required |
|---|-----|--------|---------|---------------|
| 1 | `/auth/login` | POST | Get access token | ❌ No |
| 2 | `/schedule` | GET | Get daily schedule | ✅ Yes |
| 3 | `/entries/my` | GET | Get all horse entries | ✅ Yes |
| 4 | `/entries/{entry_id}` | GET | Get single entry details | ✅ Yes |
| 5 | `/classes/{class_id}` | GET | Get class details & results | ✅ Yes |

---

## API 1: Login

### Purpose
Authenticate user and obtain access token for subsequent API calls.

### Request

```
POST /auth/login
Content-Type: application/json
```

**Body:**
```json
{
    "username": "ckear0004@gmail.com",
    "password": "5614$$$AshlandFarms",
    "remember_me": "yes",
    "company_id": "15"
}
```

**Parameters:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| username | string | ✅ | User email address |
| password | string | ✅ | User password |
| remember_me | string | ✅ | "yes" for extended session |
| company_id | string | ✅ | Company/Customer ID (same as customer_id in other APIs) |

### Response

**Status:** 200 OK

```json
{
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VybmFtZSI6IkVtaWx5IFNtaXRoIiwic3ViIjoxNTU4NSwiaWF0IjoxNzcwOTgzNzI5LCJleHAiOjE3NzIyNzk3Mjl9.wrwoQz8Hh77cQ_NulDuo-x6_17IO7TkVY3oLN7Ndbto",
    "user": {
        "user": {
            "sgl_id": 15585,
            "first": "Emily",
            "last_name": "Smith",
            "full_name": "Emily Smith",
            "address": "14395 Stroller Way",
            "email_address": "ckear0004@gmail.com",
            "phonenumber": "3025212476",
            "phonenumber_verified": 1,
            "vb_username": "",
            "registration_confirmed": 1,
            "city": "Wellington",
            "state": "FL",
            "postal_code": "33414"
        },
        "userTeams": [
            {
                "teamId": 605,
                "name": "Af Annex",
                "description": "",
                "role": {
                    "sgl_id": 8,
                    "name": "owner",
                    "description": "Team owner with full access to all features and team management",
                    "canAddEntry": true,
                    "canEditEntry": true,
                    "canViewEntries": true,
                    "canCheckout": true,
                    "canOrderSupplies": true,
                    "canManageCards": true,
                    "adminAccess": true,
                    "isActive": true,
                    "createdAt": "2025-09-29T11:22:10.000Z",
                    "updatedAt": "2025-09-29T11:22:10.000Z"
                },
                "isOwner": true,
                "memberCount": 3,
                "joinedAt": "2025-12-02T14:26:09.000Z",
                "teamOwnerId": 15585
            }
        ],
        "userVerfied": true,
        "sgl_on_hold": false
    },
    "update_password": false,
    "sgl_on_hold": false,
    "pendingUserOnboardAction": {
        "hasPendingAction": false
    },
    "verify_login": false,
    "verification_status": "verified",
    "pendingVerifyUserAction": {
        "hasPendingAction": false
    }
}
```

**Key Fields:**

| Field | Type | Description |
|-------|------|-------------|
| access_token | string | JWT token to use in Authorization header |
| user.user.sgl_id | integer | User's SGL ID |
| user.user.full_name | string | User's full name |
| user.userTeams | array | Teams/farms user belongs to |

### Example cURL

```bash
curl --location 'https://sglapi.wellingtoninternational.com/auth/login' \
--header 'Content-Type: application/json' \
--header 'Origin: https://www.wellingtoninternational.com' \
--data-raw '{
    "username": "ckear0004@gmail.com",
    "password": "5614$$$AshlandFarms",
    "remember_me": "yes",
    "company_id": "15"
}'
```

---

## API 2: Get Schedule

### Purpose
Get the complete schedule for a specific date including all rings and classes.

### Request

```
GET /schedule?date={date}&customer_id={customer_id}
Authorization: Bearer {access_token}
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| date | string | ✅ | Date in YYYY-MM-DD format |
| customer_id | integer | ✅ | Customer/Company ID (15) |

### Response

**Status:** 200 OK

```json
{
    "show": {
        "show_id": 200000050,
        "show_name": "2026 WEF 6 (#200) CSI3* WCHR IDA Development",
        "facility_id": 1,
        "start_date": "2026-02-10T00:00:00.000Z",
        "end_date": "2026-02-15T00:00:00.000Z"
    },
    "show_date": "2026-02-11",
    "show_display_date": "Tuesday, February 11, 2026",
    "show_days_list": [
        "2026-02-10",
        "2026-02-11",
        "2026-02-12",
        "2026-02-13",
        "2026-02-14",
        "2026-02-15"
    ],
    "rings": [
        {
            "ring_name": "International Ring",
            "ring_number": 1,
            "ring_id": 51,
            "ring_status": "Ring Underway",
            "classes": [
                {
                    "class_id": 200019884,
                    "class_number": "2401",
                    "class_name": "$150 Green Conformation Hunter Model",
                    "sponsor": "Griffis Residential",
                    "estimated_start_time": "07:15:00",
                    "actual_start_time": "07:20:00",
                    "status": "Completed",
                    "total_trips": 12,
                    "completed_trips": 12,
                    "remaining_trips": 0,
                    "class_type": "Hunters",
                    "jumper_table": ""
                },
                {
                    "class_id": 200019885,
                    "class_number": "2402",
                    "class_name": "$500 Green Hunter 3'",
                    "sponsor": "",
                    "estimated_start_time": "08:00:00",
                    "actual_start_time": null,
                    "status": "Not Started",
                    "total_trips": 25,
                    "completed_trips": 0,
                    "remaining_trips": 25,
                    "class_type": "Hunters",
                    "jumper_table": ""
                }
            ]
        },
        {
            "ring_name": "Schooling Ring",
            "ring_number": 7,
            "ring_id": 57,
            "ring_status": "Ring Underway",
            "classes": [
                {
                    "class_id": 200019819,
                    "class_number": "1095",
                    "class_name": "1.25m Schooling Jumper (Table II)",
                    "sponsor": "",
                    "estimated_start_time": "11:50:00",
                    "actual_start_time": null,
                    "status": "Not Started",
                    "total_trips": 68,
                    "completed_trips": 0,
                    "remaining_trips": 68,
                    "class_type": "Jumpers",
                    "jumper_table": "USEF Table II.2.b"
                }
            ]
        }
    ]
}
```

**Key Fields:**

| Field | Type | Description |
|-------|------|-------------|
| show.show_id | integer | Unique show identifier |
| show.show_name | string | Full show name |
| show.start_date | string | Show start date (ISO format) |
| show.end_date | string | Show end date (ISO format) |
| show_date | string | Requested date |
| rings | array | List of rings with their classes |
| rings[].ring_id | integer | Ring identifier |
| rings[].ring_name | string | Ring name |
| rings[].ring_number | integer | Ring number |
| rings[].ring_status | string | "Ring Underway", "Ring Complete" |
| rings[].classes | array | Classes in this ring |
| classes[].class_id | integer | Class identifier |
| classes[].class_name | string | Class name |
| classes[].status | string | "Not Started", "In Progress", "Completed" |
| classes[].estimated_start_time | string | Scheduled start time (HH:MM:SS) |
| classes[].actual_start_time | string | Actual start time (null if not started) |
| classes[].total_trips | integer | Total entries in class |
| classes[].completed_trips | integer | Completed entries |
| classes[].remaining_trips | integer | Remaining entries |

### Example cURL

```bash
curl --location 'https://sglapi.wellingtoninternational.com/schedule?date=2026-02-11&customer_id=15' \
--header 'Origin: https://www.wellingtoninternational.com' \
--header 'Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...'
```

---

## API 3: Get My Entries

### Purpose
Get all horse entries registered by the user/farm for a specific show.

### Request

```
GET /entries/my?show_id={show_id}&customer_id={customer_id}
Authorization: Bearer {access_token}
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| show_id | integer | ✅ | Show ID (from Schedule API) |
| customer_id | integer | ✅ | Customer/Company ID (15) |

### Response

**Status:** 200 OK

```json
{
    "entries": [
        {
            "entry_id": 200143652,
            "show_id": 200000050,
            "number": 1101,
            "horse": "CLASS ACT",
            "horse_id": 118897,
            "customer_id": 15,
            "scratched": 0,
            "trainer_account": 0,
            "trainer_id": 13724
        },
        {
            "entry_id": 200143741,
            "show_id": 200000050,
            "number": 1103,
            "horse": "CLIP DE LA HAYE Z",
            "horse_id": 127180,
            "customer_id": 15,
            "scratched": 0,
            "trainer_account": 0,
            "trainer_id": 13724
        },
        {
            "entry_id": 200143927,
            "show_id": 200000050,
            "number": 1105,
            "horse": "OSTWIND 59",
            "horse_id": 131897,
            "customer_id": 15,
            "scratched": 0,
            "trainer_account": 0,
            "trainer_id": 13724
        }
    ],
    "total_entries": 85,
    "show_id": "200000050",
    "request_entries": [],
    "user_logged_id": true,
    "people_ids": [
        13724,
        85137,
        45836
    ]
}
```

**Key Fields:**

| Field | Type | Description |
|-------|------|-------------|
| entries | array | List of all entries |
| entries[].entry_id | integer | Entry identifier (use for Entry Detail API) |
| entries[].show_id | integer | Show identifier |
| entries[].number | integer | Back number for this show |
| entries[].horse | string | Horse name |
| entries[].horse_id | integer | Horse identifier (show-specific) |
| entries[].scratched | integer | 0 = active, 1 = scratched |
| entries[].trainer_id | integer | Trainer identifier |
| total_entries | integer | Total number of entries |

### Example cURL

```bash
curl --location 'https://sglapi.wellingtoninternational.com/entries/my?show_id=200000050&customer_id=15' \
--header 'Origin: https://www.wellingtoninternational.com' \
--header 'Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...'
```

---

## API 4: Get Entry Detail

### Purpose
Get detailed information about a specific entry including all classes the horse is entered in.

### Request

```
GET /entries/{entry_id}?eid={entry_id}&show_id={show_id}&customer_id={customer_id}
Authorization: Bearer {access_token}
```

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| entry_id | integer | ✅ | Entry ID (from My Entries API) |

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| eid | integer | ✅ | Entry ID (same as path parameter) |
| show_id | integer | ✅ | Show ID |
| customer_id | integer | ✅ | Customer/Company ID (15) |

### Response

**Status:** 200 OK

```json
{
    "entry": {
        "entry_id": 200143927,
        "number": 1105,
        "horse_id": 131897,
        "horse": "OSTWIND 59",
        "trainer_id": 13724,
        "trainer": "EMILY SMITH",
        "entryowner_id": 67760,
        "owner": "MOUNTAIN KING RANCH LLC",
        "rider_id": 0,
        "rider": "",
        "rider_list": "JORDAN GIBBS",
        "show_id": 200000050,
        "responsibleparty_id": 67760,
        "responsibleparty": "MOUNTAIN KING RANCH LLC",
        "ec_responsibleparty_id": 0,
        "prizemoneyrecipient_id": 67760,
        "prizemoneyrecipient": "MOUNTAIN KING RANCH LLC",
        "creating_sgl_id": 15585,
        "scratched": 0,
        "trainer_account": 0
    },
    "classes": [
        {
            "class_id": 200019819,
            "class_number": 1095,
            "name": "1.25m Schooling Jumper (Table II)",
            "sponsor": "Griffis Residential",
            "rider_id": 67418,
            "rider_name": "JORDAN GIBBS",
            "placing": 0,
            "ring": 7,
            "scheduled_date": "2026-02-11T00:00:00.000Z",
            "schedule_starttime": "11:50:05",
            "entryxclasses_uuid": "4E6D7D6906FD497799401ABA8D9E5EFA",
            "scratch_trip": 0,
            "count": 68
        }
    ],
    "show_id": "200000050",
    "entry_show": {
        "show_name": "2026 WEF 6 (#200) CSI3* WCHR IDA Development",
        "city": "",
        "state": "",
        "postal_code": "",
        "phone": "5617841116",
        "start_date": "2026-02-10T00:00:00.000Z",
        "end_date": "2026-02-15T00:00:00.000Z"
    },
    "company_name": {
        "name": "Wellington International"
    },
    "is_videos_enabled": true,
    "entry_riders": [
        {
            "sgl_id": 4355326,
            "entry_id": 200143927,
            "rider_id": 67418,
            "rider_name": "JORDAN GIBBS"
        }
    ],
    "is_responsible": true
}
```

**Key Fields:**

| Field | Type | Description |
|-------|------|-------------|
| entry.entry_id | integer | Entry identifier |
| entry.number | integer | Back number |
| entry.horse_id | integer | Horse identifier (show-specific) |
| entry.horse | string | Horse name |
| entry.trainer_id | integer | Trainer identifier |
| entry.trainer | string | Trainer name |
| entry.owner | string | Owner name |
| entry.rider_list | string | Comma-separated rider names |
| classes | array | Classes horse is entered in |
| classes[].class_id | integer | Class identifier (show-specific) |
| classes[].class_number | integer | Class number |
| classes[].name | string | Class name |
| classes[].rider_id | integer | Rider ID for this class |
| classes[].rider_name | string | Rider name for this class |
| classes[].ring | integer | Ring number |
| classes[].scheduled_date | string | Scheduled date (ISO format) |
| classes[].schedule_starttime | string | Start time (HH:MM:SS) |
| classes[].scratch_trip | integer | 0 = active, 1 = scratched |
| classes[].count | integer | Total entries in class |
| entry_riders | array | All riders associated with this entry |

### Example cURL

```bash
curl --location 'https://sglapi.wellingtoninternational.com/entries/200143927?eid=200143927&show_id=200000050&customer_id=15' \
--header 'Origin: https://www.wellingtoninternational.com' \
--header 'Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...'
```

---

## API 5: Get Class Detail

### Purpose
Get detailed class information including all trips (horse performances) and results.

### Request

```
GET /classes/{class_id}?show_id={show_id}&customer_id={customer_id}&cgid={class_group_id}
Authorization: Bearer {access_token}
```

**Path Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| class_id | integer | ✅ | Class ID |

**Query Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| show_id | integer | ✅ | Show ID |
| customer_id | integer | ✅ | Customer/Company ID (15) |
| cgid | integer | ❌ | Class group ID (optional) |

### Response

**Status:** 200 OK

```json
{
    "cdm_data": [],
    "class": {
        "class_id": 200019884,
        "number": 2401,
        "name": "$150 Green Conformation Hunter Model",
        "sponsor": "",
        "order_of_go_set": 1,
        "order_set_date": "2026-02-10T00:00:00.000Z",
        "order_set_time": "16:36:22",
        "class_type": "Hunters",
        "verification_detail": "02-11-26 - 10:47:04 - Luciana quinones",
        "results_verified": 1,
        "schedule_sequencetype": "Model",
        "show_id": 200000050,
        "combined_class_id": 0,
        "jumper_table": "",
        "schedule_ring_id": 51,
        "customer_id": 15,
        "is_team_event": false,
        "is_under_saddle_class": true,
        "oog_status_text": "Class is Model",
        "has_splits": false
    },
    "class_related_data": {
        "status": "Completed",
        "unscratched_count": 12,
        "show_results": true,
        "has_prize_money": true,
        "grouped_class": false,
        "show_ring_info": true,
        "actual_time": "00:00:00",
        "estimated_time": "07:15:00",
        "default_time": "07:15:00",
        "date": "2026-02-11T00:00:00.000Z",
        "class_group_id": 200019613,
        "ring": 1,
        "total_trips": 12,
        "completed_trips": 12,
        "remaining_trips": 0,
        "order_check_in": 0,
        "hunter_scoreby": "",
        "hunter_type": "No Score, No Jog",
        "type": "",
        "ring_name": "International Ring",
        "judges": [
            {
                "name": "RACHEL KENNEDY",
                "position": "",
                "isjudge": 1,
                "iscoursedesigner": 0
            },
            {
                "name": "HOLLY ORLANDO",
                "position": "",
                "isjudge": 1,
                "iscoursedesigner": 0
            }
        ],
        "judges_count": 4,
        "class_split_codes": ["A"],
        "current_split_code": "A",
        "class_prizes": [
            {
                "place": 1,
                "prize_money": 45,
                "points": 5
            },
            {
                "place": 2,
                "prize_money": 33,
                "points": 3
            },
            {
                "place": 3,
                "prize_money": 22.5,
                "points": 2
            }
        ],
        "show_est_time": true,
        "show_planned_time": false,
        "is_videos_enabled": true
    },
    "jumper_table_info": {
        "class_jumper_table": "",
        "class_group_jumper_table": "",
        "show_id": 200000050,
        "timeallowed_tripone": 0,
        "timeallowed_jo": 0,
        "ring": 1,
        "hasR3Data": false,
        "table_type": 1,
        "jumper_table": "",
        "hasJO": false,
        "after_delay_JO": false,
        "MandatoryJO": false,
        "has_aggregate_faults": false,
        "fei_rule": false,
        "separateJOVideo": false,
        "roundLabels": {
            "r1": { "name": "Round 1", "abbr": "R1" },
            "r2": { "name": "Round 2", "abbr": "R2" },
            "r3": { "name": "Round 3", "abbr": "R3" }
        }
    },
    "total_entry_trips": 13,
    "trips": [
        {
            "entry_id": 200187277,
            "number": 3412,
            "horse": "WELL PLAYED",
            "rider": "",
            "Owner": "CLEMENTINA BROWN",
            "trainer": "CHRISTINA SERIO",
            "owner_id": 3209,
            "trainer_id": 7080,
            "trip_id": 200283381,
            "total_prize_money": 45,
            "estimated_go_time": "09:15:00",
            "rider_name": "CHRISTINA SERIO",
            "rider_id": 7080,
            "points_earned": 5,
            "time_one": 0,
            "time_fault_one": 0,
            "faults_one": 0,
            "time_two": 0,
            "time_fault_two": 0,
            "faults_two": 0,
            "time_three": 0,
            "time_fault_three": 0,
            "faults_three": 0,
            "scratch_trip": 0,
            "actual_order": 0,
            "placing": 1,
            "position": 100000,
            "order_of_go": 9,
            "score1": 0,
            "score2": 0,
            "score3": 0,
            "score4": 0,
            "score5": 0,
            "score6": 0,
            "disqualify_status_one": "",
            "disqualify_status_two": "",
            "disqualify_status_three": "",
            "entryxclasses_uuid": "EC7778D2A54942F38E0606132EA59CC1",
            "gone_in": 1,
            "team_id": 0,
            "r3_trip": 0,
            "team_name": null,
            "team_type": null,
            "team_abbr": null,
            "rank_placing": "1<sup>st</sup>",
            "rank": 1,
            "place": 1,
            "split_section": "A",
            "score": 0,
            "competing_country": "USA"
        },
        {
            "entry_id": 200168364,
            "number": 1804,
            "horse": "BASANO",
            "rider": "",
            "Owner": "RIVERS EDGE",
            "trainer": "KENNETH BERKLEY",
            "owner_id": 4091,
            "trainer_id": 2983,
            "trip_id": 200284050,
            "total_prize_money": 33,
            "estimated_go_time": "08:45:00",
            "rider_name": "SCOTT STEWART",
            "rider_id": 13283,
            "points_earned": 3,
            "time_one": 0,
            "time_fault_one": 0,
            "faults_one": 0,
            "time_two": 0,
            "time_fault_two": 0,
            "faults_two": 0,
            "scratch_trip": 0,
            "placing": 2,
            "order_of_go": 7,
            "score1": 0,
            "score2": 0,
            "score3": 0,
            "score4": 0,
            "score5": 0,
            "score6": 0,
            "disqualify_status_one": "",
            "disqualify_status_two": "",
            "gone_in": 1,
            "rank": 2,
            "place": 2,
            "split_section": "A",
            "competing_country": "USA"
        },
        {
            "entry_id": 200202231,
            "number": 1320,
            "horse": "VIRTUE",
            "rider": "",
            "Owner": "LULAV GROUP LTD.",
            "trainer": "DAVID BELFORD",
            "owner_id": 74973,
            "trainer_id": 2931,
            "trip_id": 200283085,
            "total_prize_money": 0,
            "estimated_go_time": "07:30:00",
            "rider_name": "CHRISTOPHER PAYNE",
            "rider_id": 6447,
            "points_earned": 0,
            "time_one": 0,
            "time_fault_one": 0,
            "faults_one": 0,
            "scratch_trip": 1,
            "placing": 100000,
            "order_of_go": 2,
            "disqualify_status_one": "DNS",
            "disqualify_status_two": "",
            "gone_in": 0,
            "rank": 0,
            "place": 9,
            "split_section": "A",
            "competing_country": "USA"
        }
    ],
    "show_id": "200000050",
    "team_scoring_result": [],
    "class_group_order_of_go": {
        "entries": []
    }
}
```

**Key Fields:**

| Field | Type | Description |
|-------|------|-------------|
| class.class_id | integer | Class identifier |
| class.name | string | Class name |
| class.class_type | string | "Hunters" or "Jumpers" |
| class.jumper_table | string | Jumper scoring table |
| class_related_data.status | string | "Not Started", "In Progress", "Completed" |
| class_related_data.estimated_time | string | Scheduled start time |
| class_related_data.actual_time | string | Actual start time |
| class_related_data.total_trips | integer | Total entries |
| class_related_data.completed_trips | integer | Completed entries |
| class_related_data.remaining_trips | integer | Remaining entries |
| class_related_data.ring_name | string | Ring name |
| class_related_data.ring | integer | Ring number |
| trips | array | All horse performances |
| trips[].entry_id | integer | Entry identifier |
| trips[].trip_id | integer | Trip identifier |
| trips[].horse | string | Horse name |
| trips[].number | integer | Back number |
| trips[].rider_name | string | Rider name |
| trips[].rider_id | integer | Rider identifier |
| trips[].order_of_go | integer | Order in class |
| trips[].placing | integer | Final placing (100000 = unplaced) |
| trips[].faults_one | decimal | Round 1 faults |
| trips[].time_one | decimal | Round 1 time |
| trips[].time_fault_one | decimal | Round 1 time faults |
| trips[].faults_two | decimal | Jump-off faults |
| trips[].time_two | decimal | Jump-off time |
| trips[].time_fault_two | decimal | Jump-off time faults |
| trips[].score1-6 | decimal | Hunter judge scores |
| trips[].total_prize_money | decimal | Prize money won |
| trips[].points_earned | decimal | Points earned |
| trips[].gone_in | integer | 0 = waiting, 1 = completed |
| trips[].scratch_trip | integer | 0 = active, 1 = scratched |
| trips[].disqualify_status_one | string | "DNS", "DQ", "WD", "" |
| trips[].disqualify_status_two | string | "DNS", "DQ", "WD", "" |
| trips[].competing_country | string | Country code |

### Example cURL

```bash
curl --location 'https://sglapi.wellingtoninternational.com/classes/200019884?show_id=200000050&customer_id=15&cgid=200019613' \
--header 'Origin: https://www.wellingtoninternational.com' \
--header 'Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...'
```

---

## Field Value Reference

### Status Values

| Field | Values |
|-------|--------|
| class_related_data.status | "Not Started", "In Progress", "Completed" |
| ring_status | "Ring Underway", "Ring Complete" |
| disqualify_status | "", "DNS" (Did Not Start), "DQ" (Disqualified), "WD" (Withdrew) |

### Placing Values

| Value | Meaning |
|-------|---------|
| 1-999 | Actual placing |
| 100000 | Unplaced / Not yet placed |
| 0 | Not applicable |

### Boolean Integers

| Value | Meaning |
|-------|---------|
| 0 | False / No |
| 1 | True / Yes |

---

## API to Database Mapping

### Schedule API → Database

| API Field | Database Table | Database Column |
|-----------|---------------|-----------------|
| show.show_id | shows | api_show_id |
| show.show_name | shows | name |
| show.start_date | shows | start_date |
| show.end_date | shows | end_date |
| rings[].ring_id | entries | api_ring_id |
| rings[].ring_name | events | name (match by name) |
| rings[].ring_number | events | ring_number |
| classes[].class_id | entries | api_class_id |
| classes[].class_number | classes | class_number |
| classes[].class_name | classes | name (match by name) |
| classes[].sponsor | classes | sponsor |
| classes[].estimated_start_time | entries | estimated_start |

### My Entries API → Database

| API Field | Database Table | Database Column |
|-----------|---------------|-----------------|
| entries[].entry_id | entries | api_entry_id |
| entries[].horse_id | entries | api_horse_id |
| entries[].horse | horses | name (match by name) |
| entries[].number | entries | back_number |
| entries[].trainer_id | entries | api_trainer_id |

### Entry Detail API → Database

| API Field | Database Table | Database Column |
|-----------|---------------|-----------------|
| entry.entry_id | entries | api_entry_id |
| entry.horse_id | entries | api_horse_id |
| entry.horse | horses | name (match by name) |
| entry.trainer_id | entries | api_trainer_id |
| classes[].class_id | entries | api_class_id |
| classes[].ring | entries | api_ring_id |
| classes[].rider_id | entries | api_rider_id |
| classes[].rider_name | riders | name (match by name) |
| classes[].scheduled_date | entries | scheduled_date |
| classes[].schedule_starttime | entries | estimated_start |

### Class Detail API → Database

| API Field | Database Table | Database Column |
|-----------|---------------|-----------------|
| class_related_data.status | entries | class_status |
| class_related_data.estimated_time | entries | estimated_start |
| class_related_data.actual_time | entries | actual_start |
| class_related_data.total_trips | entries | total_trips |
| class_related_data.completed_trips | entries | completed_trips |
| class_related_data.remaining_trips | entries | remaining_trips |
| trips[].trip_id | entries | api_trip_id |
| trips[].order_of_go | entries | order_of_go |
| trips[].placing | entries | placing |
| trips[].faults_one | entries | faults_one |
| trips[].time_one | entries | time_one |
| trips[].time_fault_one | entries | time_fault_one |
| trips[].faults_two | entries | faults_two |
| trips[].time_two | entries | time_two |
| trips[].time_fault_two | entries | time_fault_two |
| trips[].score1-6 | entries | score1-6 |
| trips[].total_prize_money | entries | total_prize_money |
| trips[].points_earned | entries | points_earned |
| trips[].gone_in | entries | gone_in (convert to boolean) |
| trips[].scratch_trip | entries | scratch_trip (convert to boolean) |
| trips[].disqualify_status_one | entries | disqualify_status_one |
| trips[].disqualify_status_two | entries | disqualify_status_two |

---

## Error Handling

### Common HTTP Status Codes

| Code | Meaning | Action |
|------|---------|--------|
| 200 | Success | Process response |
| 401 | Unauthorized | Token expired, call Login API again |
| 403 | Forbidden | Check permissions |
| 404 | Not Found | Resource doesn't exist |
| 500 | Server Error | Retry with backoff |

### Retry Strategy

```
Retry 3 times with exponential backoff:
- Attempt 1: Immediate
- Attempt 2: Wait 2 seconds
- Attempt 3: Wait 4 seconds
```

---

## Usage Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                      API CALL SEQUENCE                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. Login API                                                    │
│     POST /auth/login                                             │
│     → Get access_token                                           │
│                    │                                             │
│                    ▼                                             │
│  2. Schedule API (for daily schedule)                            │
│     GET /schedule?date={today}                                   │
│     → Get show_id, rings, classes                                │
│                    │                                             │
│                    ▼                                             │
│  3. My Entries API (for horse registrations)                     │
│     GET /entries/my?show_id={show_id}                            │
│     → Get list of entry_ids                                      │
│                    │                                             │
│                    ▼                                             │
│  4. Entry Detail API (for each entry)                            │
│     GET /entries/{entry_id}                                      │
│     → Get horse details, classes enrolled                        │
│                    │                                             │
│                    ▼                                             │
│  5. Class Detail API (for monitoring)                            │
│     GET /classes/{class_id}                                      │
│     → Get real-time status, trips, results                       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```