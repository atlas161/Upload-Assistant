import os
import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional

import requests


@dataclass(frozen=True)
class ProwlarrDupeResult:
    exists: bool
    matched_title: str = ""
    match_score: float = 0.0


def _normalize_title(value: str) -> str:
    value = (value or "").lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    a_set = set(a.split())
    b_set = set(b.split())
    if not a_set or not b_set:
        return 0.0
    return len(a_set & b_set) / len(a_set | b_set)


def _parse_int_list_env(value: str) -> Optional[list[int]]:
    value = (value or "").strip()
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip() != ""]
    result: list[int] = []
    for p in parts:
        try:
            result.append(int(p))
        except ValueError:
            continue
    return result or None


def _get_tracker_env(tracker: str, key: str) -> Optional[str]:
    tracker = (tracker or "").strip().upper()
    candidates = [
        f"{tracker}_{key}",
        f"{tracker}_{key}".replace("-", "_"),
        key,
    ]
    for c in candidates:
        v = os.environ.get(c)
        if v is not None and str(v).strip() != "":
            return str(v).strip()
    return None


def prowlarr_release_exists(
    query: str,
    tracker: Optional[str] = None,
    timeout_s: int = 20,
    min_score: float = 0.88,
) -> ProwlarrDupeResult:
    base_url = _get_tracker_env(tracker or "", "PROWLARR_URL") or os.environ.get("PROWLARR_URL")
    api_key = _get_tracker_env(tracker or "", "PROWLARR_API_KEY") or os.environ.get("PROWLARR_API_KEY")
    if not base_url or not api_key:
        return ProwlarrDupeResult(exists=False)

    base_url = base_url.rstrip("/")
    url = f"{base_url}/api/v1/search"

    search_type = (
        _get_tracker_env(tracker or "", "PROWLARR_SEARCH_TYPE")
        or os.environ.get("PROWLARR_SEARCH_TYPE")
        or "search"
    )
    indexer_ids = _parse_int_list_env(_get_tracker_env(tracker or "", "PROWLARR_INDEXER_IDS") or os.environ.get("PROWLARR_INDEXER_IDS") or "")
    categories = _parse_int_list_env(_get_tracker_env(tracker or "", "PROWLARR_CATEGORIES") or os.environ.get("PROWLARR_CATEGORIES") or "")

    params: dict[str, Any] = {
        "query": query,
        "type": search_type,
        "limit": 100,
        "offset": 0,
    }
    if indexer_ids is not None:
        params["indexerIds"] = ",".join(str(i) for i in indexer_ids)
    if categories is not None:
        params["categories"] = ",".join(str(c) for c in categories)

    headers = {"Accept": "application/json", "X-Api-Key": api_key}

    resp = requests.get(url, params=params, headers=headers, timeout=timeout_s)
    resp.raise_for_status()
    items = resp.json()
    if not isinstance(items, list):
        return ProwlarrDupeResult(exists=False)

    target = _normalize_title(query)
    best_title = ""
    best_score = 0.0
    for it in items:
        if not isinstance(it, dict):
            continue
        title = str(it.get("title") or "")
        if not title:
            continue
        score = _similarity(target, _normalize_title(title))
        if score > best_score:
            best_score = score
            best_title = title

    return ProwlarrDupeResult(exists=best_score >= min_score, matched_title=best_title, match_score=best_score)

