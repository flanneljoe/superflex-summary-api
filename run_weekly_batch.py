import asyncio
from database import SessionLocal
from generation import check_and_run_weekly_batch

async def main():
    db = SessionLocal()
    try:
        await check_and_run_weekly_batch(db)
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(main())