from pathlib import Path
import gzip
import json
import os
import re
import threading
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from collections import defaultdict, OrderedDict

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
POSTER_DIR = BASE_DIR / "posters"
INFO_DIR = BASE_DIR / "movie_info"
ASSETS_DIR = BASE_DIR / "assets"

POSTER_DIR.mkdir(exist_ok=True)
INFO_DIR.mkdir(exist_ok=True)
ASSETS_DIR.mkdir(exist_ok=True)

OMDB_API_KEY = os.getenv("OMDB_API_KEY", "80b0d7b7")

PAGE_RESULT_CACHE_LIMIT = 160
TOP_RATING_MIN_VOTES = 10000
POPULAR_MIN_VOTES = 1000

app = FastAPI(title="FamiFlix")
app.mount("/posters", StaticFiles(directory=str(POSTER_DIR)), name="posters")
app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")

_cache_lock = threading.Lock()
_result_cache_lock = threading.Lock()
_catalog_cache: Dict[str, List[dict]] = {}
_genres_cache: Dict[str, List[str]] = {}
_search_index: Dict[str, Dict[str, set]] = {}
_sorted_cache: Dict[Tuple[str, str], List[dict]] = {}
_result_cache: "OrderedDict[str, dict]" = OrderedDict()


def current_year() -> int:
    return datetime.utcnow().year


def valid_tconst(tconst: str) -> bool:
    return bool(re.fullmatch(r"tt\d+", tconst or ""))


def to_int(value, default=0):
    try:
        if value in (None, "", "\\N", "N/A"):
            return default
        return int(str(value).replace(",", ""))
    except Exception:
        return default


def to_float(value, default=0.0):
    try:
        if value in (None, "", "\\N", "N/A"):
            return default
        return float(value)
    except Exception:
        return default


def normalize_text(value: str) -> str:
    value = (value or "").lower()
    value = value.replace("&", " and ")
    value = re.sub(r"[^0-9a-zа-яё]+", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value).strip()
    return value


STOP_WORDS = {"and", "the", "a", "an", "of", "in", "to", "for", "и", "на", "в", "с", "за"}


def search_tokens(query: str):
    return [t for t in normalize_text(query).split() if t and t not in STOP_WORDS]


def read_json_or_gz(stem: str):
    gz_file = BASE_DIR / f"{stem}.json.gz"
    json_file = BASE_DIR / f"{stem}.json"

    if gz_file.exists():
        with gzip.open(gz_file, "rt", encoding="utf-8") as f:
            return json.load(f)

    if json_file.exists():
        with open(json_file, "r", encoding="utf-8") as f:
            return json.load(f)

    raise RuntimeError(f"{stem}.json.gz or {stem}.json not found")


def catalog_stem(section: str) -> str:
    return "series" if section == "series" else "movies"


def rating_quality_score(item):
    votes = max(0, item.get("_votes", 0))
    rating = max(0.0, item.get("_rating", 0.0))
    m = 25000
    c = 6.8
    return ((votes / (votes + m)) * rating) + ((m / (votes + m)) * c) if votes + m else 0


def popularity_score(item):
    """Raw audience popularity used by the default 'Всички' sort.

    'Всички' should show everything ordered by vote count.
    'Топ рейтинг' uses rating_quality_score() instead.
    """
    return max(0, item.get("_votes", 0))


def normalize_item(raw: dict, section: str) -> Optional[dict]:
    tconst = raw.get("id") or raw.get("tconst") or raw.get("parentTconst")
    if not valid_tconst(tconst):
        return None

    title = raw.get("title") or raw.get("primaryTitle") or raw.get("name") or "Untitled"
    original_title = raw.get("originalTitle") or title
    year = raw.get("year") or raw.get("startYear") or ""
    end_year = raw.get("endYear") or ""
    runtime = raw.get("runtime") or raw.get("runtimeMinutes") or ""
    genres = raw.get("genres") or ""
    rating = raw.get("rating") or raw.get("averageRating") or ""
    votes = raw.get("votes") or raw.get("numVotes") or "0"

    title_norm = normalize_text(title)
    original_norm = normalize_text(original_title)

    item = {
        "id": tconst,
        "type": section,
        "title": title,
        "originalTitle": original_title,
        "year": year,
        "endYear": end_year,
        "runtime": runtime,
        "genres": genres,
        "rating": rating,
        "votes": votes,
        "seasons": raw.get("seasons") or raw.get("seasonCount") or "",
        "episodeCount": raw.get("episodeCount") or raw.get("episodes") or raw.get("numEpisodes") or "",
        "_votes": to_int(votes),
        "_rating": to_float(rating),
        "_year": to_int(year),
        "_title_lc": title.lower(),
        "_original_lc": original_title.lower(),
        "_title_norm": title_norm,
        "_original_norm": original_norm,
    }
    item["_quality"] = rating_quality_score(item)
    item["_popular"] = popularity_score(item)
    return item


def load_catalog_once(section: str):
    section = "series" if section == "series" else "movies"

    if section in _catalog_cache:
        return _catalog_cache[section]

    with _cache_lock:
        if section in _catalog_cache:
            return _catalog_cache[section]

        raw_items = read_json_or_gz(catalog_stem(section))
        cleaned = []
        genres = set()
        token_index = defaultdict(set)

        for idx, raw in enumerate(raw_items):
            item = normalize_item(raw, section)
            if not item:
                continue

            # Do not show unreleased/future titles anywhere in FamiFlix.
            # current_year() is fixed to 2026 in this setup, so 2027+ titles
            # are excluded from movies and series results.
            if item.get("_year") and item["_year"] > current_year():
                continue

            # Hide low-signal titles globally to keep catalog quality high.
            if item.get("_votes", 0) < POPULAR_MIN_VOTES:
                continue

            real_idx = len(cleaned)
            item_genres = item.get("genres") or ""
            if item_genres and item_genres != "\\N":
                for g in item_genres.split(","):
                    g = g.strip()
                    if g and g.lower() != "adult":
                        genres.add(g)

            for token in set((item["_title_norm"] + " " + item["_original_norm"] + " " + item["id"].lower()).split()):
                if token and len(token) >= 2:
                    token_index[token].add(real_idx)

            cleaned.append(item)

        _catalog_cache[section] = cleaned
        _genres_cache[section] = sorted(genres)
        _search_index[section] = dict(token_index)

        # Pre-sort common no-filter views for instant page jumps.
        _sorted_cache[(section, "reviews")] = sort_items(list(cleaned), "reviews", "")
        _sorted_cache[(section, "rating")] = sort_items(list(cleaned), "rating", "")
        _sorted_cache[(section, "year_desc")] = sort_items(list(cleaned), "year_desc", "")
        _sorted_cache[(section, "year_asc")] = sort_items(list(cleaned), "year_asc", "")
        _sorted_cache[(section, "title")] = sort_items(list(cleaned), "title", "")
        _sorted_cache[(section, "latest")] = sort_items(list(cleaned), "latest", "")

        print(f"Loaded {len(cleaned)} {section} into server memory")
        return cleaned


def public_item(item):
    return {
        "id": item["id"],
        "type": item["type"],
        "title": item["title"],
        "originalTitle": item["originalTitle"],
        "year": item["year"],
        "endYear": item["endYear"],
        "runtime": item["runtime"],
        "genres": item["genres"],
        "rating": item["rating"],
        "votes": item["votes"],
        "seasons": item.get("seasons", ""),
        "episodeCount": item.get("episodeCount", ""),
    }


def score_item(item, query: str):
    q_norm = normalize_text(query)
    tokens = search_tokens(query)
    if not q_norm and not tokens:
        return 0

    title = item["_title_norm"]
    original = item["_original_norm"]
    tconst = item["id"].lower()

    if title == q_norm:
        return 1600
    if original == q_norm:
        return 1550
    if tconst == q_norm:
        return 1500
    if title.startswith(q_norm):
        return 1300
    if original.startswith(q_norm):
        return 1250
    if q_norm and q_norm in title:
        return 1100
    if q_norm and q_norm in original:
        return 1050

    if tokens and all(t in title for t in tokens):
        return 950 + min(len(tokens), 10)
    if tokens and all(t in original for t in tokens):
        return 920 + min(len(tokens), 10)
    if q_norm and q_norm in tconst:
        return 850

    if len(tokens) >= 2:
        title_hits = sum(1 for t in tokens if t in title)
        original_hits = sum(1 for t in tokens if t in original)
        needed = max(2, len(tokens) - 1)
        if title_hits >= needed:
            return 700 + title_hits
        if original_hits >= needed:
            return 670 + original_hits

    return 0


def get_search_candidates(section: str, query: str) -> Optional[List[dict]]:
    tokens = search_tokens(query)
    if not tokens:
        return None

    load_catalog_once(section)
    index = _search_index.get(section, {})
    catalog = _catalog_cache[section]

    sets = []
    for token in tokens:
        if token in index:
            sets.append(index[token])
        else:
            # Prefix fallback, still cheaper than full scoring for normal searches.
            union = set()
            for indexed_token, ids in index.items():
                if indexed_token.startswith(token):
                    union.update(ids)
            if union:
                sets.append(union)

    if not sets:
        return []

    # Prefer intersection for multi-word searches. If too restrictive, use union.
    ids = set.intersection(*sets) if len(sets) > 1 else set(sets[0])
    if not ids and len(sets) > 1:
        ids = set().union(*sets)

    return [catalog[i] for i in ids]


def sort_items(items, sort_mode: str, query: str):
    sort_mode = sort_mode or "reviews"

    if sort_mode == "rating":
        items = [m for m in items if m["_votes"] >= TOP_RATING_MIN_VOTES and m["_rating"] > 0]
        if query:
            return sorted(items, key=lambda m: (m.get("_score", 0), m["_quality"], m["_rating"], m["_votes"]), reverse=True)
        return sorted(items, key=lambda m: (m["_quality"], m["_rating"], m["_votes"]), reverse=True)

    if sort_mode == "latest":
        cy = current_year()
        items = [m for m in items if m["_year"] >= cy]
        if query:
            return sorted(items, key=lambda m: (m.get("_score", 0), m["_year"], m["_popular"]), reverse=True)
        return sorted(items, key=lambda m: (m["_year"], m["_popular"]), reverse=True)

    if query:
        if sort_mode == "year_desc":
            return sorted(items, key=lambda m: (m.get("_score", 0), m["_year"], m["_popular"]), reverse=True)
        if sort_mode == "year_asc":
            return sorted(items, key=lambda m: (-m.get("_score", 0), m["_year"] or 9999, -m["_popular"]))
        if sort_mode == "title":
            return sorted(items, key=lambda m: (-m.get("_score", 0), m["_title_lc"]))
        # Default for searches: match quality first, then balanced popularity/rating.
        return sorted(items, key=lambda m: (m.get("_score", 0), m["_popular"], m["_quality"], m["_votes"]), reverse=True)

    if sort_mode == "year_desc":
        return sorted(items, key=lambda m: (m["_year"], m["_popular"]), reverse=True)
    if sort_mode == "year_asc":
        return sorted(items, key=lambda m: (m["_year"] or 9999, -m["_popular"]))
    if sort_mode == "title":
        return sorted(items, key=lambda m: m["_title_lc"])

    # Default "Всички": show all titles, ordered by most votes.
    # This keeps the main catalog predictable and fast.
    return sorted(items, key=lambda m: (m["_votes"], m["_rating"], m["_year"]), reverse=True)


def parse_genres(genres: str):
    if not genres:
        return []
    return [g.strip() for g in genres.split(",") if g.strip() and g.strip().lower() != "adult"]


def result_cache_get(key: str):
    with _result_cache_lock:
        data = _result_cache.get(key)
        if data is not None:
            _result_cache.move_to_end(key)
        return data


def result_cache_set(key: str, data: dict):
    with _result_cache_lock:
        _result_cache[key] = data
        _result_cache.move_to_end(key)
        while len(_result_cache) > PAGE_RESULT_CACHE_LIMIT:
            _result_cache.popitem(last=False)


def paginated_catalog_response(
    section: str,
    page: int,
    page_size: int,
    q: str,
    genres: str,
    sort: str,
    view: str,
    ids: Optional[str],
    year_min: int,
    year_max: int,
):
    section = "series" if section == "series" else "movies"
    query = (q or "").strip()
    selected_genres = parse_genres(genres)
    sort = (sort or "reviews").strip()
    view = (view or "all").strip()
    year_max = year_max or current_year()

    cache_key = json.dumps({
        "s": section, "p": page, "ps": page_size, "q": query, "g": selected_genres,
        "sort": sort, "view": view, "ids": ids if view == "favorites" else "",
        "y1": year_min, "y2": year_max
    }, sort_keys=True)

    cached = result_cache_get(cache_key)
    if cached is not None:
        return JSONResponse(cached, headers={"Cache-Control": "no-store"})

    all_items = load_catalog_once(section)

    favorite_ids = set()
    if view == "favorites":
        favorite_ids = {x.strip() for x in (ids or "").split(",") if valid_tconst(x.strip())}
        if not favorite_ids:
            payload = {"items": [], "total": 0, "page": 1, "page_size": page_size, "total_pages": 1, "section": section, "current_year": current_year()}
            result_cache_set(cache_key, payload)
            return JSONResponse(payload, headers={"Cache-Control": "no-store"})

    # Fast path: no filters and no search, use pre-sorted list and slice only.
    no_filters = not query and not selected_genres and view != "favorites" and year_min <= 1920 and year_max >= current_year()
    if no_filters and (section, sort) in _sorted_cache:
        result = _sorted_cache[(section, sort)]
    else:
        candidates = get_search_candidates(section, query) if query else all_items
        result = []

        for item in candidates:
            if favorite_ids and item["id"] not in favorite_ids:
                continue

            if year_min and item["_year"] and item["_year"] < year_min:
                continue
            if year_max and item["_year"] and item["_year"] > year_max:
                continue

            if selected_genres:
                item_genres = set(parse_genres(item.get("genres") or ""))
                if not item_genres:
                    continue
                # AND logic: Action + Adventure means title must include both.
                if not all(g in item_genres for g in selected_genres):
                    continue

            if query:
                score = score_item(item, query)
                if score <= 0:
                    continue
                item = dict(item)
                item["_score"] = score

            result.append(item)

        result = sort_items(result, sort, query)

    total = len(result)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(max(1, page), total_pages)
    start = (page - 1) * page_size
    end = start + page_size

    payload = {
        "items": [public_item(item) for item in result[start:end]],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "section": section,
        "current_year": current_year(),
    }
    result_cache_set(cache_key, payload)
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@app.on_event("startup")
def warm_cache():
    for section in ("movies", "series"):
        try:
            load_catalog_once(section)
        except Exception as e:
            print(f"{section} cache warmup failed:", e)


@app.get("/")
def home():
    return FileResponse(BASE_DIR / "index.html")


@app.get("/index.html")
def index():
    return FileResponse(BASE_DIR / "index.html")


def legacy_json(stem: str):
    gz_file = BASE_DIR / f"{stem}.json.gz"
    json_file = BASE_DIR / f"{stem}.json"

    if gz_file.exists():
        return FileResponse(gz_file, media_type="application/json", headers={"Content-Encoding": "gzip", "Cache-Control": "public, max-age=86400"})
    if json_file.exists():
        return FileResponse(json_file, media_type="application/json", headers={"Cache-Control": "public, max-age=86400"})
    raise HTTPException(status_code=404, detail=f"{stem}.json.gz or {stem}.json not found")


@app.get("/movies.json")
def movies_json():
    return legacy_json("movies")


@app.get("/series.json")
def series_json():
    return legacy_json("series")


@app.get("/api/genres")
def api_genres(section: str = "movies"):
    section = "series" if section == "series" else "movies"
    load_catalog_once(section)
    return JSONResponse(
        {"genres": _genres_cache.get(section, []), "current_year": current_year()},
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/api/movies")
def api_movies(
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    q: str = "",
    genres: str = "",
    sort: str = "reviews",
    view: str = "all",
    ids: Optional[str] = "",
    year_min: int = Query(1920, ge=1800, le=3000),
    year_max: int = Query(None, ge=1800, le=3000),
):
    return paginated_catalog_response("movies", page, page_size, q, genres, sort, view, ids, year_min, year_max or current_year())


@app.get("/api/series")
def api_series(
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    q: str = "",
    genres: str = "",
    sort: str = "reviews",
    view: str = "all",
    ids: Optional[str] = "",
    year_min: int = Query(1920, ge=1800, le=3000),
    year_max: int = Query(None, ge=1800, le=3000),
):
    return paginated_catalog_response("series", page, page_size, q, genres, sort, view, ids, year_min, year_max or current_year())


@app.get("/title-info/{tconst}")
def title_info(tconst: str):
    return info_response(tconst)


@app.get("/movie-info/{tconst}")
def movie_info(tconst: str):
    return info_response(tconst)


def info_response(tconst: str):
    if not valid_tconst(tconst):
        raise HTTPException(status_code=400, detail="Invalid IMDb title ID")

    info_path = INFO_DIR / f"{tconst}.json"

    if info_path.exists():
        return FileResponse(info_path, media_type="application/json", headers={"Cache-Control": "public, max-age=31536000"})

    try:
        url = f"https://www.omdbapi.com/?apikey={OMDB_API_KEY}&i={tconst}&plot=full"
        response = requests.get(url, timeout=10)
        data = response.json()

        if data.get("Response") != "True":
            return JSONResponse(
                {
                    "Title": "",
                    "Year": "",
                    "Rated": "",
                    "Released": "",
                    "Runtime": "",
                    "Genre": "",
                    "Director": "Unknown",
                    "Writer": "Unknown",
                    "Actors": "Unknown",
                    "Plot": data.get("Error", "No description available."),
                    "Language": "",
                    "Country": "",
                    "Awards": "",
                    "Metascore": "",
                    "imdbRating": "",
                    "imdbVotes": "",
                    "BoxOffice": "",
                    "totalSeasons": "",
                    "Ratings": [],
                },
                status_code=200,
            )

        info = {
            "Title": data.get("Title", ""),
            "Year": data.get("Year", ""),
            "Rated": data.get("Rated", ""),
            "Released": data.get("Released", ""),
            "Runtime": data.get("Runtime", ""),
            "Genre": data.get("Genre", ""),
            "Director": data.get("Director", "Unknown"),
            "Writer": data.get("Writer", "Unknown"),
            "Actors": data.get("Actors", "Unknown"),
            "Plot": data.get("Plot", "No description available."),
            "Language": data.get("Language", ""),
            "Country": data.get("Country", ""),
            "Awards": data.get("Awards", ""),
            "Metascore": data.get("Metascore", ""),
            "imdbRating": data.get("imdbRating", ""),
            "imdbVotes": data.get("imdbVotes", ""),
            "BoxOffice": data.get("BoxOffice", ""),
            "totalSeasons": data.get("totalSeasons", ""),
            "Ratings": data.get("Ratings", []),
        }

        with open(info_path, "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False, indent=2)

        return info

    except Exception as e:
        print("Title info error:", tconst, e)
        return JSONResponse({"Title": "", "Director": "Unknown", "Actors": "Unknown", "Plot": "Title info temporarily unavailable.", "Ratings": []}, status_code=200)
