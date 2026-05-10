from pathlib import Path
import gzip
import json
import time
import argparse
import requests

BASE_DIR = Path(__file__).resolve().parent
POSTER_DIR = BASE_DIR / "posters"
POSTER_DIR.mkdir(exist_ok=True)

SERIES_FILE = BASE_DIR / "series.json.gz"
CHECKPOINT_FILE = BASE_DIR / "series_poster_cache_checkpoint.json"

# Series poster API key
OMDB_API_KEY = "80b0d7b7"


def load_checkpoint():
    if CHECKPOINT_FILE.exists():
        try:
            with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    return {"last_index": 0}


def save_checkpoint(index):
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_index": index}, f)


def votes_number(item):
    try:
        return int(str(item.get("votes") or item.get("numVotes") or 0).replace(",", ""))
    except ValueError:
        return 0


def get_tconst(item):
    return item.get("id") or item.get("tconst") or item.get("parentTconst")


def get_title(item):
    return item.get("title") or item.get("primaryTitle") or item.get("originalTitle") or ""


def fetch_poster(tconst):
    poster_path = POSTER_DIR / f"{tconst}.jpg"
    missing_path = POSTER_DIR / f"{tconst}.missing"

    if poster_path.exists() or missing_path.exists():
        return "cached"

    try:
        omdb_url = f"https://www.omdbapi.com/?i={tconst}&apikey={OMDB_API_KEY}&type=series"
        omdb = requests.get(omdb_url, timeout=8).json()

        poster_url = omdb.get("Poster")

        if not poster_url or poster_url == "N/A":
            missing_path.write_text("missing", encoding="utf-8")
            return "missing"

        img = requests.get(poster_url, timeout=12)

        if img.status_code != 200:
            missing_path.write_text("missing", encoding="utf-8")
            return "failed"

        poster_path.write_bytes(img.content)
        return "saved"

    except Exception as e:
        return f"error: {e}"


def load_series():
    if not SERIES_FILE.exists():
        raise FileNotFoundError(f"Missing file: {SERIES_FILE}")

    with gzip.open(SERIES_FILE, "rt", encoding="utf-8") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="Cache OMDb posters for series parent IMDb IDs into posters/.")
    parser.add_argument("--limit", type=int, default=500, help="How many series to process this run")
    parser.add_argument("--delay", type=float, default=0.3, help="Delay between requests")
    parser.add_argument("--query", type=str, default="", help="Only process series matching title or ID")
    parser.add_argument("--reset", action="store_true", help="Restart checkpoint from index 0")
    args = parser.parse_args()

    series = load_series()

    if args.query:
        q = args.query.lower()
        series = [
            s for s in series
            if q in get_title(s).lower()
            or q in str(s.get("originalTitle") or "").lower()
            or q in str(get_tconst(s) or "").lower()
        ]

    # Most reviews/votes first, same logic as movies.
    series.sort(key=votes_number, reverse=True)

    if args.reset and CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()

    checkpoint = load_checkpoint()
    start_index = int(checkpoint.get("last_index", 0))
    end_index = min(start_index + args.limit, len(series))

    print(f"Starting from index: {start_index}")
    print(f"Stopping at index: {end_index}")
    print("Sorted by most reviews/votes first")
    print(f"Using posters directory: {POSTER_DIR}")

    index = start_index

    try:
        for index in range(start_index, end_index):
            item = series[index]
            tconst = get_tconst(item)
            title = get_title(item)
            votes = item.get("votes") or item.get("numVotes") or "0"

            if not tconst:
                result = "missing tconst"
            else:
                result = fetch_poster(tconst)

            print(
                f"{index + 1}/{len(series)} "
                f"{tconst} | {votes} votes | {title} -> {result}"
            )

            save_checkpoint(index + 1)
            time.sleep(args.delay)

    except KeyboardInterrupt:
        print("\nInterrupted. Checkpoint saved.")
        save_checkpoint(index)
        return

    print("Done. Checkpoint saved.")


if __name__ == "__main__":
    main()
