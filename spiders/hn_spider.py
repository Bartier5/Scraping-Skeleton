import asyncio
import sys
from pipeline.cleaner import DataCleaner
from pipeline.transformer import DataTransformer
from utils.logger import log

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from utils.url_utils import prepare_urls
from spiders.base_spider import BaseSpider
from pipeline.validator import DataValidator
from pydantic import BaseModel
from typing import Optional

class HNStorySchema(BaseModel):
    title: str
    author: str
    url: Optional[str] = ""
    points: Optional[int] = 0
    num_comments: Optional[int] = 0
    created_at: Optional[str] = ""

class HNSpider(BaseSpider):
    BASE_URL = "https://hn.algolia.com/api/v1/search"
    QUERY = "python"
    HITS_PER_PAGE = 20

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._cleaner = DataCleaner()
        self._transformer = DataTransformer(add_metadata=True)
        self._validator = DataValidator(schema=HNStorySchema)

    async def run(self, urls=None, **kwargs):
        self.start_run([self.BASE_URL])

        async with self:
            page = 0

            while True:
                api_url = (
                    f"{self.BASE_URL}"
                    f"?query={self.QUERY}"
                    f"&tags=story"
                    f"&page={page}"
                    f"&hitsPerPage={self.HITS_PER_PAGE}"
                )

                result = await self.fetch(api_url)
                if result.failed:
                    self.logger.warning(f"Failed on page {page}")
                    break

                # --- JSON parsing — no BS4 needed ---
                import json
                data = json.loads(result.html)
                hits = data.get("hits", [])
                total_pages = data.get("nbPages", 1)

                if not hits:
                    break

                raw = []
                for hit in hits:
                    raw.append({
                        "title":        hit.get("title", ""),
                        "author":       hit.get("author", ""),
                        "url":          hit.get("url", ""),
                        "points":       hit.get("points", 0),
                        "num_comments": hit.get("num_comments", 0),
                        "created_at":   hit.get("created_at", ""),
                    })

                cleaned     = self._cleaner.clean_items(raw)
                transformed = self._transformer.transform_items(cleaned)
                batch       = self._validator.validate_batch(transformed)
                await self.save(batch.valid_items)

                self._stats["items_scraped"] += len(batch.valid_items)
                log.info(f"Page {page}/{total_pages} — {len(batch.valid_items)} stories")

                page += 1
                if page >= total_pages or page >= 5:  # cap at 5 pages for test
                    break

        self.finish_run()
        return self.get_stats()