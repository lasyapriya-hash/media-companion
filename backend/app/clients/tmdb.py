"""TMDb client: movie/series search, details, and watch providers (spec §7, §10).

Region for watch providers is fixed to India (spec §5.4).
"""
from __future__ import annotations

import httpx

from app.clients.base import DEFAULT_TIMEOUT, request_json
from app.schemas.media import NormalizedMedia, WatchAvailability
from app.services.normalization import length_bucket

TMDB_BASE = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
DEFAULT_REGION = "IN"

# TMDb media path <-> our media type
_TMDB_PATH = {"movie": "movie", "series": "tv"}


def _year_from(*dates: str | None) -> int | None:
    for d in dates:
        if d and d[:4].isdigit():
            return int(d[:4])
    return None


def _num(x: object) -> float | None:
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def _poster(path: str | None) -> str | None:
    return f"{IMAGE_BASE}{path}" if path else None


# --------------------------------------------------------------------------- #
# Pure normalization (no I/O) — unit-tested directly.
# --------------------------------------------------------------------------- #
def normalize_tmdb_search(
    result: dict, kind: str, genre_map: dict[int, str]
) -> NormalizedMedia:
    """Normalize one `/search/multi` result. `kind` is 'movie' or 'series'."""
    genres = [genre_map[g] for g in result.get("genre_ids", []) if g in genre_map]
    return NormalizedMedia(
        source="tmdb",
        source_id=str(result["id"]),
        type=kind,
        title=result.get("title") or result.get("name") or "",
        description=result.get("overview") or None,
        genres=genres,
        language=result.get("original_language"),
        year=_year_from(result.get("release_date"), result.get("first_air_date")),
        external_rating=_num(result.get("vote_average")),
        artwork_url=_poster(result.get("poster_path")),
        raw_metadata=result,
    )


def normalize_tmdb_details(payload: dict, media_type: str) -> NormalizedMedia:
    """Normalize a `/movie/{id}` or `/tv/{id}` details payload."""
    genres = [g["name"] for g in payload.get("genres", []) if g.get("name")]
    common = dict(
        source="tmdb",
        source_id=str(payload["id"]),
        type=media_type,
        title=payload.get("title") or payload.get("name") or "",
        description=payload.get("overview") or None,
        genres=genres,
        language=payload.get("original_language"),
        year=_year_from(
            payload.get("release_date"), payload.get("first_air_date")
        ),
        external_rating=_num(payload.get("vote_average")),
        artwork_url=_poster(payload.get("poster_path")),
        raw_metadata=payload,
    )

    if media_type == "movie":
        runtime = payload.get("runtime") or None
        media = NormalizedMedia(**common, runtime_minutes=runtime)
        media.length_bucket = length_bucket("movie", runtime_minutes=runtime)
        return media

    ep_runtimes = payload.get("episode_run_time") or []
    ep_runtime = ep_runtimes[0] if ep_runtimes else None
    media = NormalizedMedia(
        **common,
        seasons=payload.get("number_of_seasons"),
        episodes=payload.get("number_of_episodes"),
        episode_runtime_minutes=ep_runtime,
    )
    media.length_bucket = length_bucket(
        "series", episode_runtime_minutes=ep_runtime
    )
    return media


def parse_watch_providers(
    results: dict, region: str = DEFAULT_REGION
) -> WatchAvailability:
    """Turn `/watch/providers` `.results` into a per-region summary.

    Missing region or no offers -> status 'unknown' (spec §5.4).
    """
    entry = results.get(region)
    if not entry:
        return WatchAvailability(region=region, status="unknown")

    def names(key: str) -> list[str]:
        return [p["provider_name"] for p in entry.get(key, []) if p.get("provider_name")]

    flatrate, rent, buy = names("flatrate"), names("rent"), names("buy")
    status = "available" if (flatrate or rent or buy) else "unknown"
    return WatchAvailability(
        region=region,
        status=status,
        flatrate=flatrate,
        rent=rent,
        buy=buy,
        link=entry.get("link"),
    )


# --------------------------------------------------------------------------- #
# Client (I/O)
# --------------------------------------------------------------------------- #
class TMDbClient:
    def __init__(self, api_key: str):
        self._api_key = api_key
        self._http = httpx.Client(base_url=TMDB_BASE, timeout=DEFAULT_TIMEOUT)
        self._genre_cache: dict[str, dict[int, str]] = {}

    # -- auth: v3 key as query param, v4 JWT as bearer -- #
    def _auth(self) -> tuple[dict, dict]:
        if self._api_key.count(".") == 2:  # looks like a JWT
            return {}, {"Authorization": f"Bearer {self._api_key}"}
        return {"api_key": self._api_key}, {}

    def _get(self, path: str, params: dict | None = None) -> dict:
        query, headers = self._auth()
        return request_json(self._http, path, {**(params or {}), **query}, headers)

    def _genres(self, tmdb_media: str) -> dict[int, str]:
        if tmdb_media not in self._genre_cache:
            data = self._get(f"/genre/{tmdb_media}/list")
            self._genre_cache[tmdb_media] = {
                g["id"]: g["name"] for g in data.get("genres", [])
            }
        return self._genre_cache[tmdb_media]

    def search(
        self, query: str, media_type: str | None = None, limit: int = 10
    ) -> list[NormalizedMedia]:
        """Unified movie+series search via `/search/multi`."""
        data = self._get(
            "/search/multi", {"query": query, "include_adult": "false"}
        )
        out: list[NormalizedMedia] = []
        for result in data.get("results", []):
            tmdb_media = result.get("media_type")
            if tmdb_media == "movie":
                kind = "movie"
            elif tmdb_media == "tv":
                kind = "series"
            else:
                continue
            if media_type and kind != media_type:
                continue
            out.append(
                normalize_tmdb_search(
                    result, kind, self._genres(_TMDB_PATH[kind])
                )
            )
            if len(out) >= limit:
                break
        return out

    def get_details(self, source_id: str, media_type: str) -> NormalizedMedia:
        payload = self._get(f"/{_TMDB_PATH[media_type]}/{source_id}")
        return normalize_tmdb_details(payload, media_type)

    def discover(
        self,
        media_type: str,
        *,
        genres: list[str] | None = None,
        language: str | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
        limit: int = 20,
    ) -> list[NormalizedMedia]:
        """Preference-driven candidate query via `/discover` (spec §8.2).

        Genre *names* are resolved to TMDb ids; unknown names are dropped.
        `sort_by=popularity.desc` only shapes the candidate pool — ranking is
        done downstream and never uses popularity or rating as a sort key
        (spec §9.3).
        """
        tmdb_media = _TMDB_PATH[media_type]
        gmap = self._genres(tmdb_media)
        by_name = {name.lower(): gid for gid, name in gmap.items()}
        genre_ids = [
            str(by_name[g.strip().lower()])
            for g in (genres or [])
            if g.strip().lower() in by_name
        ]

        params: dict[str, object] = {
            "sort_by": "popularity.desc",
            "include_adult": "false",
            "page": 1,
        }
        if genre_ids:
            params["with_genres"] = ",".join(genre_ids)
        if language:
            params["with_original_language"] = language
        date_field = "primary_release_date" if media_type == "movie" else "first_air_date"
        if year_from:
            params[f"{date_field}.gte"] = f"{year_from}-01-01"
        if year_to:
            params[f"{date_field}.lte"] = f"{year_to}-12-31"

        data = self._get(f"/discover/{tmdb_media}", params)
        return [
            normalize_tmdb_search(r, media_type, gmap)
            for r in data.get("results", [])[:limit]
        ]

    def get_watch_providers(
        self, source_id: str, media_type: str, region: str = DEFAULT_REGION
    ) -> WatchAvailability:
        data = self._get(
            f"/{_TMDB_PATH[media_type]}/{source_id}/watch/providers"
        )
        return parse_watch_providers(data.get("results", {}), region)
