# aman.ai section search

A full-text search over every section of [Aman's AI Journal](https://aman.ai), powered by
[Meilisearch](https://www.meilisearch.com/), with a minimal dark frontend that can be
hosted for free on GitHub Pages.

The crawler visits each URL in `aman-ai-links.txt` and splits every page into sections
(one per heading). Each section becomes its own searchable document whose URL includes the
anchor, so a result for "saliency maps" links straight to
`https://aman.ai/cs231n/visualization/#saliency-maps--grabcut-segmentation-without-supervision`
rather than just to the top of the page.

## How it works

```
aman-ai-links.txt  ->  aman_spider.py (Scrapy)  ->  aman-ai-sections.jsonl
                                                        |
                                                        v
frontend/ (HTML + CSS + JS)  <-  Meilisearch index "aman-ai"  <-  index_meilisearch.py
```

- `aman_spider.py` - Scrapy spider. Reads every link in `aman-ai-links.txt`, extracts the
  page title plus each heading section (h2/h3/h4) with its text and anchor, and writes one
  JSON line per section.
- `aman-ai-sections.jsonl` - the crawl output (20,595 sections across 485 pages).
  Each line is a document with `id`, `url` (deep link with anchor), `page_url`, `title`,
  `section_title`, `level`, `section_path`, and `content`.
- `index_meilisearch.py` - loads the JSONL into a Meilisearch index and creates a
  search-only API key for the frontend. It only touches its own index and never modifies
  any other index on the instance.
- `frontend/` - static search page (HTML, CSS, plain JavaScript, no build step).

## Re-running the crawl

```bash
uv pip install --python .venv/Scripts/python.exe scrapy meilisearch
.venv/Scripts/python -m scrapy runspider aman_spider.py -o aman-ai-sections.jsonl
```

The crawl skips non-HTML links (e.g. PDFs) and keeps the existing `-o` output overwritten
on each run, so re-runs are idempotent.

## Indexing into Meilisearch

Point the script at your instance and pass an API key that can add documents and create
keys (the master key works):

```bash
MEILISEARCH_URL=https://adhi.isroot.in \
MEILISEARCH_KEY=your_master_key \
.venv/Scripts/python index_meilisearch.py
```

Defaults: index name `aman-ai`, host `https://adhi.isroot.in`. Override with the
`MEILISEARCH_INDEX` / `MEILISEARCH_URL` / `MEILISEARCH_KEY` environment variables.

The script:

1. configures searchable attributes (`title`, `section_title`, `section_path`, `content`)
   and filterable attributes (`page_url`, `level`),
2. wipes and reloads only the `aman-ai` index,
3. creates a search-only API key scoped to that index and prints it.

## Configuring the frontend

1. Open `frontend/script.js` and set the search key in the `SEARCH_KEY` constant to the
   key printed by the indexing step. The host and index name are already set to
   `https://adhi.isroot.in` and `aman-ai`.
2. Push the three files in `frontend/` (index.html, style.css, script.js) to a repository.
3. In the repository settings, enable GitHub Pages and deploy from the branch containing
   the files (root folder). The page will be live at `https://<user>.github.io/<repo>/`.

The search key is search-only and scoped to the `aman-ai` index, so it is safe to ship in
public code. The instance must be reachable from the browser and answer CORS requests
(this instance already does).

## Usage

- Type to search as you type. Results show the section title, the page it lives on, a
  breadcrumb of parent sections, and a snippet with matches highlighted.
- `Ctrl+K` (or `Cmd+K` on macOS) focuses the search box from anywhere.
- `Up` / `Down` move through results, `Enter` opens the highlighted result, `Esc` clears.
- Every result opens the exact section on aman.ai via its anchor link.

## Search API example

```bash
curl -H "Authorization: Bearer <search-key>" \
  "https://adhi.isroot.in/indexes/aman-ai/search?q=saliency"
```

Each hit's `url` field is the deep link to the section.
