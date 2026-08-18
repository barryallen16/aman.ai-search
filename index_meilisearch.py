"""Index the scraped aman.ai sections into Meilisearch.

Every line of aman-ai-sections.jsonl is one document: a page section whose
`url` field contains the anchor (e.g. .../visualization/#review-computer-vision-tasks),
so search results can deep-link straight to the exact section.

This script only ever touches the index named INDEX_NAME below
("aman-ai" by default). Existing indexes such as "yt-ssf" are left alone.

Usage
-----
    MEILISEARCH_KEY=master-key .venv/Scripts/python index_meilisearch.py
    # environment overrides (optional):
    #   MEILISEARCH_URL   default https://adhi.isroot.in
    #   MEILISEARCH_INDEX default aman-ai

Documents are uploaded in small batches (500 each) with retry and backoff,
so a slow link or a busy server can recover automatically.

After indexing, a search-only key scoped to this index is printed; paste it
into frontend/script.js so the public site can search without exposing the
master key.
"""

import json
import os
import sys
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

INDEX_NAME = os.environ.get("MEILISEARCH_INDEX", "aman-ai")
DATA_FILE = "aman-ai-sections.jsonl"

MEILI_URL = os.environ.get("MEILISEARCH_URL", "https://adhi.isroot.in")
MEILI_KEY = os.environ.get("MEILISEARCH_KEY")

BATCH_SIZE = 500
TASK_TIMEOUT_S = 600
MAX_RETRIES = 3

SEARCHABLE_ATTRIBUTES = ["title", "section_title", "section_path", "content"]
FILTERABLE_ATTRIBUTES = ["page_url", "level"]

# Build a session with automatic retries for connection/timeout errors.
_session = requests.Session()
_retry = Retry(
    total=5,
    backoff_factor=2,
    status_forcelist=[502, 503, 504],
    allowed_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
_session.mount("https://", HTTPAdapter(max_retries=_retry))


def api(method: str, path: str, *, body=None, timeout=(30, 600)):
    """Thin requests wrapper: JSON in, JSON out, clear errors."""
    r = _session.request(
        method,
        MEILI_URL + path,
        headers={"Authorization": f"Bearer {MEILI_KEY}"},
        json=body,
        timeout=timeout,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"{method} {path} -> HTTP {r.status_code}: {r.text[:300]}")
    return r.json() if r.text else {}


def wait_for_task(uid: int, timeout: int = TASK_TIMEOUT_S):
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = api("GET", f"/tasks/{uid}")
        if task.get("status") == "succeeded":
            return
        if task.get("status") in ("failed", "canceled"):
            err = task.get("error") or {}
            raise RuntimeError(f"task {uid} {task.get('status')}: {err.get('message', err)}")
        time.sleep(3)
    raise TimeoutError(f"task {uid} still running after {timeout}s")


def main() -> int:
    if not MEILI_KEY:
        print(
            "ERROR: no API key set. Pass the master key via MEILISEARCH_KEY,\n"
            "e.g.  MEILISEARCH_KEY=xxx .venv/Scripts/python index_meilisearch.py",
            file=sys.stderr,
        )
        return 1

    if not os.path.exists(DATA_FILE):
        print(
            f"ERROR: {DATA_FILE} not found. Run the spider first:\n"
            f"  .venv/Scripts/python -m scrapy runspider aman_spider.py -o {DATA_FILE}",
            file=sys.stderr,
        )
        return 1

    docs = []
    with open(DATA_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                docs.append(json.loads(line))
    print(f"Loaded {len(docs)} documents from {DATA_FILE}")

    # 1. Create index if it doesn't exist, then set settings.
    try:
        api("GET", f"/indexes/{INDEX_NAME}")
        print(f"Index '{INDEX_NAME}' already exists.")
    except RuntimeError:
        api("POST", "/indexes", body={"uid": INDEX_NAME, "primaryKey": "id"})
        print(f"Created index '{INDEX_NAME}'.")

    api("PATCH", f"/indexes/{INDEX_NAME}/settings", body={
        "searchableAttributes": SEARCHABLE_ATTRIBUTES,
        "filterableAttributes": FILTERABLE_ATTRIBUTES,
    })
    print("Settings applied.")

    # 2. Wipe this index only, then reload (idempotent re-runs).
    task = api("DELETE", f"/indexes/{INDEX_NAME}/documents")
    wait_for_task(task["taskUid"])
    print(f"Cleared existing documents in '{INDEX_NAME}'.")

    # 3. Upload in small batches with per-batch retries.
    total = len(docs)
    failed_batches = []
    for i in range(0, total, BATCH_SIZE):
        batch = docs[i : i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                task = api("POST", f"/indexes/{INDEX_NAME}/documents", body=batch)
                wait_for_task(task["taskUid"])
                print(f"  batch {batch_num}/{total_batches}: uploaded {len(batch)} docs ({min(i + BATCH_SIZE, total)}/{total} total)")
                break
            except (requests.exceptions.ConnectionError, TimeoutError, RuntimeError) as exc:
                if attempt < MAX_RETRIES:
                    wait = attempt * 10
                    print(f"  batch {batch_num} attempt {attempt} failed ({exc}), retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    print(f"  batch {batch_num} FAILED after {MAX_RETRIES} attempts: {exc}")
                    failed_batches.append((i, batch_num))

    if failed_batches:
        print(f"\nWARNING: {len(failed_batches)} batches failed: {[b[1] for b in failed_batches]}")
        print("Re-run the script to retry failed batches.")

    stats = api("GET", f"/indexes/{INDEX_NAME}/stats")
    doc_count = stats.get("numberOfDocuments", 0)
    print(f"\nIndexed {doc_count} section documents into '{INDEX_NAME}' @ {MEILI_URL}")
    print(f"  searchable: {SEARCHABLE_ATTRIBUTES}")
    print(f"  filterable: {FILTERABLE_ATTRIBUTES}")

    # 4. Search-only key for the public frontend, scoped to this index.
    try:
        key = api("POST", "/keys", body={
            "name": "aman-ai frontend search (public)",
            "actions": ["search"],
            "indexes": [INDEX_NAME],
            "expiresAt": None,
        })
        print("\nFrontend search key (paste into frontend/script.js, SEARCH_KEY constant):")
        print("  " + key["key"])
        print("  This key can ONLY search this index - safe to ship in public code.")
    except RuntimeError as exc:
        print(f"\nNote: could not auto-create a search-only key ({exc}).")
        print("Create one in the Meilisearch dashboard (actions: search, index: " + INDEX_NAME + ").")

    print("\nTry it:")
    print(f"  curl -H 'Authorization: Bearer <search-key>' '{MEILI_URL}/indexes/{INDEX_NAME}/search?q=saliency'")
    print("  Each hit's 'url' field is the deep link to that exact section.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
