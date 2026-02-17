#!/usr/bin/env python3
"""
Test database connection using app config (.env).
Run from project root: python scripts/check_db_connection.py
"""
import asyncio
import sys

# Allow importing app (project root in path)
sys.path.insert(0, ".")


async def check_connection() -> None:
    """Connect to DB, run a simple query, and list tables if possible."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import get_settings

    settings = get_settings()
    url = settings.DATABASE_URL
    # Hide password in print
    safe_url = url.split("@")[-1] if "@" in url else url
    print(f"Connecting to ...@{safe_url}")

    engine = create_async_engine(url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            print("Connection OK: SELECT 1 succeeded.")

            # List tables (public schema)
            result = await conn.execute(
                text(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                    ORDER BY table_name
                    """
                )
            )
            rows = result.fetchall()
            if rows:
                print(f"Tables in public schema ({len(rows)}):")
                for (name,) in rows:
                    print(f"  - {name}")
            else:
                print("No tables in public schema (or no access).")
    except Exception as e:
        print(f"Connection failed: {e}")
        raise
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(check_connection())
