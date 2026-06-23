import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from spiders.hn_spider import HNSpider

async def main():
    from storage.csv_storage import CsvStorage
    spider = HNSpider(storage=CsvStorage())
    stats = await spider.run()
    print("\n=== STATS ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")

asyncio.run(main())