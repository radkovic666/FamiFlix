import csv
import gzip
import json
import urllib.request
from pathlib import Path

DATA_DIR = Path("imdb_data")
OUT_DIR = Path(".")

FILES = {
    "basics": "https://datasets.imdbws.com/title.basics.tsv.gz",
    "ratings": "https://datasets.imdbws.com/title.ratings.tsv.gz",
    "episodes": "https://datasets.imdbws.com/title.episode.tsv.gz",
}

DATA_DIR.mkdir(exist_ok=True)
OUT_DIR.mkdir(exist_ok=True)


def download(url, path):
    if path.exists():
        print(f"Already downloaded: {path}")
        return
    print(f"Downloading {url}")
    urllib.request.urlretrieve(url, path)


def read_ratings():
    ratings = {}
    with gzip.open(DATA_DIR / "title.ratings.tsv.gz", "rt", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            ratings[row["tconst"]] = {
                "rating": row.get("averageRating", ""),
                "votes": row.get("numVotes", ""),
            }
    return ratings


def read_episode_stats():
    """Return episode/season counts keyed by parent TV-series tconst."""
    stats = {}
    path = DATA_DIR / "title.episode.tsv.gz"

    with gzip.open(path, "rt", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            parent = row.get("parentTconst")
            if not parent or parent == r"\N":
                continue

            item = stats.setdefault(parent, {"episodes": 0, "seasons": set()})
            item["episodes"] += 1

            season = row.get("seasonNumber")
            if season and season != r"\N":
                item["seasons"].add(season)

    final = {}
    for parent, item in stats.items():
        final[parent] = {
            "episodes": item["episodes"],
            "seasons": len(item["seasons"]),
        }
    return final


def build_series_json():
    ratings = read_ratings()
    episode_stats = read_episode_stats()
    series = []

    with gzip.open(DATA_DIR / "title.basics.tsv.gz", "rt", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")

        for row in reader:
            if row.get("titleType") not in {"tvSeries", "tvMiniSeries"}:
                continue

            tconst = row["tconst"]
            stats = episode_stats.get(tconst, {"episodes": 0, "seasons": 0})

            # Keep only real parent series that have episode children in title.episode.tsv.gz.
            # This avoids individual episodes like tt0959621 and keeps parents like tt0903747.
            if stats["episodes"] <= 0:
                continue

            series.append({
                "id": tconst,
                "title": row.get("primaryTitle", ""),
                "originalTitle": row.get("originalTitle", ""),
                "year": row.get("startYear", ""),
                "endYear": row.get("endYear", ""),
                "runtime": row.get("runtimeMinutes", ""),
                "genres": row.get("genres", ""),
                "rating": ratings.get(tconst, {}).get("rating", ""),
                "votes": ratings.get(tconst, {}).get("votes", ""),
                "seasons": stats["seasons"],
                "episodes": stats["episodes"],
                "playUrl": f"https://streamimdb.me/embed/tv/{tconst}/",
                "imdbUrl": f"https://www.imdb.com/title/{tconst}/",
            })

    json_path = OUT_DIR / "series.json"
    gz_path = OUT_DIR / "series.json.gz"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(series, f, ensure_ascii=False)

    with gzip.open(gz_path, "wt", encoding="utf-8") as f:
        json.dump(series, f, ensure_ascii=False)

    print(f"Saved {len(series)} parent series to {json_path}")
    print(f"Saved compressed copy to {gz_path}")


if __name__ == "__main__":
    download(FILES["basics"], DATA_DIR / "title.basics.tsv.gz")
    download(FILES["ratings"], DATA_DIR / "title.ratings.tsv.gz")
    download(FILES["episodes"], DATA_DIR / "title.episode.tsv.gz")
    build_series_json()
    print("Done.")
