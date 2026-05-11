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


def build_movies_json():
    ratings = read_ratings()
    movies = []

    with gzip.open(DATA_DIR / "title.basics.tsv.gz", "rt", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")

        for row in reader:
            if row.get("titleType") != "movie":
                continue

            runtime_raw = row.get("runtimeMinutes", "")
            if runtime_raw == r"\N":
                continue

            try:
                runtime = int(runtime_raw)
            except (TypeError, ValueError):
                continue

            if runtime < 40:
                continue

            tconst = row["tconst"]

            movies.append({
                "id": tconst,
                "title": row.get("primaryTitle", ""),
                "originalTitle": row.get("originalTitle", ""),
                "year": row.get("startYear", ""),
                "runtime": runtime_raw,
                "genres": row.get("genres", ""),
                "rating": ratings.get(tconst, {}).get("rating", ""),
                "votes": ratings.get(tconst, {}).get("votes", ""),
                "playUrl": f"https://streamimdb.me/embed/movie/{tconst}/",
                "imdbUrl": f"https://www.imdb.com/title/{tconst}/",
            })

    json_path = OUT_DIR / "movies.json"
    gz_path = OUT_DIR / "movies.json.gz"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(movies, f, ensure_ascii=False)

    with gzip.open(gz_path, "wt", encoding="utf-8") as f:
        json.dump(movies, f, ensure_ascii=False)

    print(f"Saved {len(movies)} movies to {json_path}")
    print(f"Saved compressed copy to {gz_path}")


if __name__ == "__main__":
    download(FILES["basics"], DATA_DIR / "title.basics.tsv.gz")
    download(FILES["ratings"], DATA_DIR / "title.ratings.tsv.gz")
    build_movies_json()
    print("Done.")
