# FamiFlix

FamiFlix is a lightweight FastAPI service and static site generator for browsing IMDb-based movie and TV series catalogs.

## Features

- Serves poster images and catalog metadata through a FastAPI backend.
- Loads movie/series data from `movies.json(.gz)` and `series.json(.gz)` files.
- Provides filtering, sorting, and search over titles.
- Includes helper scripts for building catalog JSON and caching posters.

## Project Files

- `server.py` — main API server.
- `build_imdb_movies_site.py` / `build_imdb_series_site.py` — build catalog data.
- `cacheposters.py` / `cacheseries.py` — cache poster assets.
- `index.html` — frontend entry page.

## Requirements

Install dependencies:

```bash
pip install -r requirements.txt
```

## Run the API

```bash
uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

Then open:

- API docs: `http://localhost:8000/docs`
- Frontend: `http://localhost:8000/`

## Environment Variables

- `OMDB_API_KEY` — OMDb API key used for metadata lookups (optional; default is set in code).

## Notes

- Ensure catalog files exist (`movies.json`/`movies.json.gz` and `series.json`/`series.json.gz`) before starting the app.
