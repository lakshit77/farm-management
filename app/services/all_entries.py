"""
All-Show Entries sync service.

Fetches all entries for a show from the Wellington /entries endpoint (paginated),
upserts them into the entries table as inactive/non-own entries. Own entries
(from /entries/my via Flow 1) are never overwritten.

Triggered once daily by n8n AFTER Flow 1 (daily schedule).
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import and_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import CUSTOMER_ID
from app.core.database import AsyncSessionLocal
from app.core.enums import EntryStatus
from app.models.entry import Entry
from app.models.horse import bulk_upsert_horses, get_horse_ids_by_names
from app.models.show import Show
from app.services.schedule import ensure_farm_and_token, resolve_sync_date
from app.services.wellington_client import (
    WellingtonAPIError,
    get_all_entries_all_pages,
    get_schedule,
)

logger = logging.getLogger(__name__)


async def _get_active_show(
    session: AsyncSession,
    farm_id: Any,
    sync_date_str: str,
    customer_id_str: str,
    token: str,
) -> Tuple[Any, int, str]:
    """
    Resolve the active show for the given date. First tries the DB (most recent
    show for this farm). Falls back to calling GET /schedule to discover it.

    Returns (show_uuid, api_show_id, show_name).
    """
    # Try DB first — most recent show for the farm
    stmt = (
        select(Show)
        .where(Show.farm_id == farm_id)
        .order_by(Show.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    show = result.scalars().first()
    if show and show.api_show_id:
        return show.id, show.api_show_id, show.name or "Unknown Show"

    # Fallback: fetch schedule to discover the show
    schedule_data = await get_schedule(sync_date_str, customer_id_str, token=token)
    show_data = schedule_data.get("show") or {}
    api_show_id = show_data.get("show_id")
    if not api_show_id:
        raise WellingtonAPIError("Cannot determine active show for all-entries sync")

    # Find the show in DB by api_show_id
    stmt2 = select(Show).where(
        and_(Show.farm_id == farm_id, Show.api_show_id == api_show_id)
    )
    result2 = await session.execute(stmt2)
    show2 = result2.scalars().first()
    if show2:
        return show2.id, api_show_id, show2.name or "Unknown Show"

    raise WellingtonAPIError(
        f"Show with api_show_id={api_show_id} not found in DB. Run Flow 1 first."
    )


async def _get_existing_own_horse_ids(
    session: AsyncSession,
    show_id: Any,
) -> Set[Any]:
    """Return set of horse_id UUIDs that already have is_own_entry=true for this show."""
    stmt = (
        select(Entry.horse_id)
        .where(
            and_(
                Entry.show_id == show_id,
                Entry.is_own_entry.is_(True),
            )
        )
        .distinct()
    )
    result = await session.execute(stmt)
    return {row[0] for row in result.all()}


async def sync_all_show_entries(
    date_override: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Fetch all show entries from Wellington /entries and store them in the DB.

    Entries are stored with status=inactive, is_own_entry=false, api_class_id=NULL.
    Own entries (is_own_entry=true) are never overwritten thanks to the conditional
    ON CONFLICT clause.

    Called by n8n daily AFTER Flow 1.
    """
    sync_date_str, _ = resolve_sync_date(date_override)
    customer_id_str = (CUSTOMER_ID or "").strip() or "15"
    logger.info("All-entries sync started | date=%s", sync_date_str)

    async with AsyncSessionLocal() as session:
        try:
            farm_id, token = await ensure_farm_and_token(session)

            show_uuid, api_show_id, show_name = await _get_active_show(
                session, farm_id, sync_date_str, customer_id_str, token
            )
            logger.info(
                "All-entries sync: show=%s (api_id=%s)", show_name, api_show_id
            )

            # Fetch all pages from Wellington API
            all_api_entries, total_count = await get_all_entries_all_pages(
                api_show_id, customer_id_str, token=token
            )
            logger.info(
                "All-entries sync: fetched %d entries (total=%d)",
                len(all_api_entries),
                total_count,
            )

            if not all_api_entries:
                await session.commit()
                return {
                    "summary": {
                        "date": sync_date_str,
                        "show_name": show_name,
                        "total_fetched": 0,
                        "inserted": 0,
                        "updated": 0,
                        "skipped_own": 0,
                    }
                }

            # Upsert all horses (collect unique names)
            horse_names: Set[str] = set()
            for e in all_api_entries:
                name = (e.get("horse") or "").strip()
                if name:
                    horse_names.add(name)

            if horse_names:
                await bulk_upsert_horses(session, farm_id, list(horse_names))
            horse_id_list = await get_horse_ids_by_names(
                session, farm_id, list(horse_names)
            )
            horse_name_to_id: Dict[str, Any] = {n: i for i, n in horse_id_list}

            # Get existing own entries to track skip count
            own_horse_ids = await _get_existing_own_horse_ids(session, show_uuid)

            # Build entry rows for upsert
            entry_rows: List[Dict[str, Any]] = []
            skipped_own = 0
            seen_horse_ids: Set[Any] = set()

            for e in all_api_entries:
                horse_name = (e.get("horse") or "").strip()
                if not horse_name:
                    continue
                horse_id = horse_name_to_id.get(horse_name)
                if not horse_id:
                    continue
                # Dedupe by horse_id (one no-class row per horse per show)
                if horse_id in seen_horse_ids:
                    continue
                seen_horse_ids.add(horse_id)

                # Track skipped own entries for summary
                if horse_id in own_horse_ids:
                    skipped_own += 1

                entry_rows.append({
                    "horse_id": horse_id,
                    "rider_id": None,
                    "show_id": show_uuid,
                    "event_id": None,
                    "class_id": None,
                    "api_entry_id": e.get("entry_id"),
                    "api_horse_id": e.get("horse_id"),
                    "api_rider_id": None,
                    "api_class_id": None,
                    "api_ring_id": None,
                    "api_trip_id": None,
                    "api_trainer_id": e.get("trainer_id"),
                    "back_number": str(e.get("number", "")).strip() or None,
                    "scheduled_date": None,
                    "estimated_start": None,
                    "status": EntryStatus.INACTIVE.value,
                    "class_status": None,
                    "is_own_entry": False,
                    "is_selected": False,
                    "rider_list_text": (e.get("rider_list") or "").strip() or None,
                    "trainer_name": (e.get("trainer") or "").strip() or None,
                    "owner_name": (e.get("owner") or "").strip() or None,
                })

            # Bulk upsert in batches: PostgreSQL has a 32,767 parameter limit.
            # Each row has ~22 columns, so max ~1,400 rows per batch. Use 500 to be safe.
            BATCH_SIZE = 500
            inserted, updated = 0, 0
            if entry_rows:
                for i in range(0, len(entry_rows), BATCH_SIZE):
                    batch = entry_rows[i : i + BATCH_SIZE]
                    stmt = insert(Entry.__table__).values(batch)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["horse_id", "show_id"],
                        index_where=text("api_class_id IS NULL"),
                        set_={
                            "api_entry_id": stmt.excluded.api_entry_id,
                            "api_horse_id": stmt.excluded.api_horse_id,
                            "api_trainer_id": stmt.excluded.api_trainer_id,
                            "back_number": stmt.excluded.back_number,
                            "rider_list_text": stmt.excluded.rider_list_text,
                            "trainer_name": stmt.excluded.trainer_name,
                            "owner_name": stmt.excluded.owner_name,
                            "updated_at": datetime.now(timezone.utc),
                        },
                        where=text("entries.is_own_entry = false"),
                    )
                    await session.execute(stmt)

                # Approximate counts (exact counts would require extra queries)
                inserted = len(entry_rows) - len(own_horse_ids & seen_horse_ids)
                updated = 0  # Hard to distinguish insert vs update without pre-check

            await session.commit()
            logger.info(
                "All-entries sync complete: fetched=%d rows=%d skipped_own=%d",
                len(all_api_entries),
                len(entry_rows),
                skipped_own,
            )

            return {
                "summary": {
                    "date": sync_date_str,
                    "show_name": show_name,
                    "api_show_id": api_show_id,
                    "total_fetched": len(all_api_entries),
                    "unique_horses": len(entry_rows),
                    "inserted": inserted,
                    "skipped_own": skipped_own,
                }
            }

        except Exception as exc:
            await session.rollback()
            logger.exception("All-entries sync failed: %s", exc)
            raise
