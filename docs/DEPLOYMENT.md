# Deployment Guide

The application is deployed on [Render](https://render.com/) as a Web Service.

## Render Configuration

### Service Settings

| Setting | Value |
|---------|-------|
| **Runtime** | Python |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `gunicorn app:server -b 0.0.0.0:10000 --workers 1 --threads 4 --worker-class gthread --timeout 120` |
| **Instance Type** | Free or Starter (512MB RAM) |
| **Port** | 10000 |

### Environment Variables

Set these in the Render dashboard under **Environment**:

| Variable | Description | Required |
|----------|-------------|----------|
| `SUPABASE_URL` | Supabase project URL (e.g., `https://xxx.supabase.co`) | Yes |
| `SUPABASE_KEY` | Supabase service role key | Yes |
| `FRED_API_KEY` | FRED API key ([request here](https://fred.stlouisfed.org/docs/api/api_key.html)) | Yes |
| `GOOGLE_API_KEY` | Google Gemini API key (for AI chat) | Yes |
| `SESSION_SECRET` | Long random string (e.g. `openssl rand -hex 32`) used to HMAC session tokens. **Required** when `RENDER` or `FLASK_ENV=production` is set; without it the app refuses to boot in production. | Yes (production) |
| `PORT` | Server port (Render sets this automatically) | No (default: 10000) |

### Procfile

The repository includes a `Procfile` for Render:

```
web: gunicorn app:server -b 0.0.0.0:10000 --workers 1 --threads 4 --worker-class gthread --timeout 120
```

**Key flags:**
- `--workers 1` -- Single worker to stay within 512MB RAM. Multiple workers would each load the model and data into memory.
- `--threads 4` -- Four threads per worker for concurrent request handling.
- `--worker-class gthread` -- Threaded worker class (more memory-efficient than `sync` for I/O-bound work).
- `--timeout 120` -- 2-minute timeout for long-running requests (initial data fetch can take 30-60 seconds).

## Memory Optimization

The 512MB RAM constraint on Render drives several architectural decisions:

### Cache-First Hydrate
The dashboard reads precomputed forecasts/contributions/fit-history/scenario-baseline from the Supabase `predictions` table on `/dashboard` nav (one DB round-trip), instead of running the full pipeline on every page load. Refresh runs opportunistically in a background callback when the cache is stale (>24h). This replaced the older sequential trigger chain that recomputed everything on every load.

### Single-Worker, Single-Flight Refresh
Only one gunicorn worker holds the model + data in memory. `refresh_async()` uses a process-local threading.Lock so concurrent refreshes don't double-fetch. Hard timeouts (FRED 20s, World Bank 25s, Supabase 10s) prevent a hung upstream from wedging the worker.

### Data Limiting
`process_data()` in `data_fetcher.py` limits data to 15 years (from the end date backwards), even if more historical data is available from FRED.

### DiskCache
Background callback state is stored on disk (`.cache/`) rather than in-memory Redis. DiskCache is sized at 128MB for callback state and 32MB for data caching.

### Lazy Imports
Heavy libraries (`pandas`, `numpy`, `scipy`, `sklearn`, `plotly`) are imported inside functions rather than at module level where possible, allowing the process to start with a smaller initial footprint.

### Process Start Method
On Linux (Render), the app uses `fork` instead of `spawn` for background processes, which is faster and more memory-efficient since child processes share the parent's memory via copy-on-write.

## Deployment Steps

### First Deployment

1. Push the repository to GitHub (or connect a Git provider to Render).
2. Create a new **Web Service** on Render.
3. Connect the repository.
4. Set the environment variables listed above (don't forget `SESSION_SECRET`).
5. Render will automatically detect the `Procfile` and `requirements.txt`.
6. Deploy.
7. (One-off) Bootstrap the predictions cache so the first user doesn't pay the cold-start cost. Run via Render Shell or locally with the production env vars:
   ```bash
   python -m logic.predictions_cache.bootstrap
   ```
   This typically takes 30-60 seconds and writes one row to the `predictions` Supabase table. Subsequent stale-refreshes happen automatically via `opportunistic_refresh`.

### Subsequent Deployments

Push to the configured branch (typically `main`). Render auto-deploys on push.

### Manual Data Refresh

If you need to force a data refresh outside the normal monthly cycle:

```bash
# SSH into the Render shell or run locally
python -m logic.data_fetcher

# Or refresh only the gold price
python -m logic.data_fetcher --replace-gold-only
```

## Building Three.js Assets

The Three.js 3D scenes are pre-built and checked into `assets/three-scenes.js`. Render doesn't run the Node build step, so you must rebuild and commit the bundle after modifying `src/three/*.ts`:

```bash
npm install          # first time only
npm run build        # production (minified)
npm run build:dev    # development (with sourcemaps)
npm run watch        # auto-rebuild on save
```

## Health Checks

Render performs health checks on the root URL. The app responds at `/` with the login page, which satisfies the health check.

### Monitoring

- **Supabase Dashboard** -- Monitor database queries, row counts, and API usage.
- **Render Dashboard** -- Monitor memory usage, CPU, and deploy logs.
- **Application Logs** -- The `DataFetcher` and `ModelPredictor` loggers output timestamped messages to stdout, visible in Render's log viewer.

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| App refuses to boot in production | `SESSION_SECRET` not set when `RENDER` or `FLASK_ENV=production` | Set `SESSION_SECRET` to `openssl rand -hex 32` in Render env |
| App killed with OOM | Memory exceeded 512MB | Check for runaway background work; verify only one gunicorn worker is configured |
| Data fetch timeout | FRED or World Bank slow | `refresh_async()` already enforces 20s/25s timeouts and falls back to last-known cache. Check Render logs for `cache.refresh.failed reason=fred_timeout` / `worldbank_timeout` |
| "Supabase client not initialized" | Missing env vars | Verify `SUPABASE_URL` and `SUPABASE_KEY` are set in Render environment |
| `predictions` table empty / 24h+ stale | Bootstrap never ran or refresh failing | Run `python -m logic.predictions_cache.bootstrap` from Render Shell. Check `cache.refresh.failed` logs for the underlying reason |
| Cache shows stale forever after retraining | New model file but `MODEL_VERSION` unchanged | Bump `MODEL_VERSION` in `logic/model/payload.py` so the lookup misses and `opportunistic_refresh` writes a fresh row |
| Model file not found | `models/` missing from deploy | Ensure the directory and `.pkl` file are committed to Git (not in `.gitignore`) |
| Gold price missing | World Bank changed their Excel URL | `_get_world_bank_gold_excel_url()` scrapes the page dynamically; check if the page structure changed |
| Chat returns error | Missing or invalid `GOOGLE_API_KEY` | Set the key in environment variables |
| `KeyError: "Callback function not found"` after deploy | Stale browser POSTing old callback IDs | Already handled — `app.py` swallows these as 204 silently. No action needed; user's next page load picks up fresh IDs |
