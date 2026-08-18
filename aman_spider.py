"""Scrapy spider for aman.ai.

Crawls every URL listed in aman-ai-links.txt and splits each page into
sections (one per h2/h3/h4 heading). Every section becomes one document with:

  - url          : page URL + "#anchor" so a UI can deep-link to the exact section
  - page_url     : the page URL itself
  - title        : page <h1> title
  - section_title: the heading text ("Introduction" for pre-heading content)
  - level        : "h2" / "h3" / "h4" / "intro"
  - section_path : breadcrumb of ancestor headings, e.g. ["Gradient Ascent", "PCA"]
  - content      : the section's text (TOC excluded)

Usage:
  .venv/Scripts/python -m scrapy runspider aman_spider.py -o aman-ai-sections.jsonl
"""

import hashlib
import re

import scrapy

LINKS_FILE = "aman-ai-links.txt"

NON_HTML_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
    ".zip", ".gz", ".mp4", ".mp3", ".woff", ".woff2", ".ico",
}


def load_urls(path: str) -> list[str]:
    urls = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            url = line.strip()
            if url:
                urls.append(url)
    return urls


def clean_text(elements) -> str:
    """Join the visible text of lxml elements (document order, no duplicates)."""
    parts = []
    for el in elements:
        if el.text:
            parts.append(el.text)
        for d in el.iterdescendants():
            if d.text:
                parts.append(d.text)
            if d.tail:
                parts.append(d.tail)
        if el.tail:
            parts.append(el.tail)
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def heading_level(tag: str) -> int:
    return int(tag[1])  # "h2" -> 2, "h3" -> 3, "h4" -> 4


class AmanAISpider(scrapy.Spider):
    name = "aman_ai"

    custom_settings = {
        "ROBOTSTXT_OBEY": False,  # deliberate: user asked to scrape every link incl. /h/
        "CONCURRENT_REQUESTS": 8,
        "DOWNLOAD_DELAY": 0.5,
        "USER_AGENT": "aman-ai-search-indexer/1.0 (personal research index)",
        "RETRY_TIMES": 3,
        "LOG_LEVEL": "INFO",
        "FEED_EXPORT_ENCODING": "utf-8",
    }

    # Scrapy >= 2.13 calls this async generator; start_requests() is deprecated.
    async def start(self):
        for url in load_urls(LINKS_FILE):
            ext = url.rsplit(".", 1)[-1].lower()
            if f".{ext}" in NON_HTML_EXTENSIONS:
                self.logger.warning("Skipping non-HTML: %s", url)
                continue
            yield scrapy.Request(url, callback=self.parse_page, errback=self.handle_error)

    def handle_error(self, failure):
        self.logger.error("Failed %s: %s", failure.request.url, repr(failure.value))

    def parse_page(self, response):
        sel = response.selector

        h1 = (
            sel.xpath('//header[contains(@class,"post-header")]//h1/text()').get()
            or sel.xpath("//h1/text()").get()
            or sel.xpath("//title/text()").get()
            or response.url
        )
        title = " ".join(h1.split())

        content = sel.xpath('//article[contains(@class,"post-content")]')
        if not content:
            content = sel.xpath('//div[contains(@class,"post")]')
        if not content:
            content = sel.xpath("//body")
        root = content[0].root

        # Drop the markdown TOC so its duplicate heading links aren't indexed.
        for toc in root.xpath('.//ul[@id="markdown-toc"]'):
            toc.getparent().remove(toc)

        elements = list(root.iter())[1:]  # descendants of the container, doc order
        positions = {id(el): i for i, el in enumerate(elements)}

        heading_els = root.xpath(".//h2 | .//h3 | .//h4")

        # Split the flat element list into sections: content before the first
        # heading (intro), then the content following each heading.
        sections = []  # (heading_el | None, [elements])
        prev_heading = None
        prev = 0
        for h in heading_els:
            pos = positions[id(h)]
            sections.append((prev_heading, elements[prev:pos]))
            prev_heading = h
            prev = pos + 1
        sections.append((prev_heading, elements[prev:]))

        # Breadcrumb path for each heading (ancestor headings only).
        paths = {}
        stack = []
        for h in heading_els:
            level = heading_level(h.tag)
            while stack and stack[-1][0] >= level:
                stack.pop()
            h_title = " ".join(h.itertext()).strip()
            stack.append((level, h_title))
            paths[id(h)] = [t for _, t in stack]

        for heading, section_els in sections:
            text = clean_text(section_els)
            if heading is None:
                # Intro section (content before the first heading)
                if not text:
                    continue
                anchor = None
                section_title = "Introduction"
                level = "intro"
                path = []
            else:
                anchor = heading.get("id")
                section_title = " ".join(heading.itertext()).strip()
                level = heading.tag
                path = paths.get(id(heading), [])
                if not text:
                    text = section_title  # keep empty heading sections searchable

            page_url = response.url
            url = f"{page_url}#{anchor}" if anchor else page_url
            doc_id = hashlib.md5(url.encode("utf-8")).hexdigest()

            yield {
                "id": doc_id,
                "url": url,
                "page_url": page_url,
                "title": title,
                "section_title": section_title,
                "level": level,
                "section_path": path,
                "content": text,
            }
