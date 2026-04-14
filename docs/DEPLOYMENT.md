# Deployment Guide

The application is deployed on [Render](https://render.com/) as a Web Service.

## Render Configuration

### Service Settings

| Setting | Value |
|---------|-------|
| **Runtime** | Python |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `gunicorn app:server -b 0.0.0.0:10000 --workers 1 --threads 4 --worker-class gthread --timeout 120 --preload` |
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
| `PORT` | Server port (Render sets this automatically) | No (default: 10000) |

### Procfile

The repository includes a `Procfile` for Render:

```
web: gunicorn app:server -b 0.0.0.0:10000 --workers 1 --threads 4 --worker-class gthread --timeout 120 --preload
```

**Key flags:**
- `--workers 1` -- Single worker to stay within 512MB RAM. Multiple workers would each load the model and data into memory.
- `--threads 4` -- Four threads per worker for concurrent request handling.
- `--worker-class gthread` -- Threaded worker class (more memory-efficient than `sync` for I/O-bound work).
- `--timeout 120` -- 2-minute timeout for long-running requests (initial data fetch can take 30-60 seconds).
- `--preload` -- Load the app before forking workers to share memory via copy-on-write.

## Memory Optimization

The 512MB RAM constraint on Render drives several architectural decisions:

### Sequential Background Callbacks
Instead of running data fetch, model prediction, and scenario baseline in parallel, they execute sequentially to avoid peak memory spikes. Each step completes and releases memory before the next begins.

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
4. Set the environment variables listed above.
5. Render will automatically detect the `Procfile` and `requirements.txt`.
6. Deploy.

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
| App killed with OOM | Memory exceeded 512MB | Check for parallel background callbacks; ensure sequential chaining is intact |
| Data fetch timeout | FRED API slow or rate-limited | The 120s gunicorn timeout should accommodate this; if not, increase `--timeout` |
| "Supabase client not initialized" | Missing env vars | Verify `SUPABASE_URL` and `SUPABASE_KEY` are set in Render environment |
| Model file not found | `models/` missing from deploy | Ensure the directory and `.pkl` file are committed to Git (not in `.gitignore`) |
| Gold price missing | World Bank changed their Excel URL | `_get_world_bank_gold_excel_url()` scrapes the page dynamically; check if the page structure changed |
| Chat returns error | Missing or invalid `GOOGLE_API_KEY` | Set the key in environment variables |
