"""Shared pagination helper for DRF endpoints."""
import requests


def paginate(session: requests.Session, url: str, params: dict | None = None) -> list[dict]:
    """Walk all pages of a DRF ListAPIView and return every result as a flat list."""
    results: list[dict] = []
    next_url: str | None = url
    first = True

    while next_url:
        resp = session.get(next_url, params=params if first else None, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        if isinstance(data, list):
            results.extend(data)
            break

        results.extend(data.get("results", []))
        next_url = data.get("next")
        first = False

    return results
