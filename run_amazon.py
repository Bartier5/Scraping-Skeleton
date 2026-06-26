import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from storage.csv_storage import CsvStorage
from spiders.amazon_spider import AmazonSpider

async def main():
    spider = AmazonSpider(storage=CsvStorage())
    stats = await spider.run()
    print("\n=== STATS ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")

asyncio.run(main())