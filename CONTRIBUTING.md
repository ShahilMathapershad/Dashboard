# Contributing

Guidelines for working in this codebase.

## Development Setup

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy environment variables
cp .env.example .env
# Fill in your API keys in .env

# Run the app
python app.py
```

For Three.js development:
```bash
npm install
npm run watch   # Auto-rebuild on save
```

## Project Layout

| Directory | Contents | Convention |
|-----------|----------|------------|
| `pages/` | Dash page modules | One file per route. Each file calls `dash.register_page()`. |
| `logic/` | Backend logic | No Dash imports or UI code. Pure data processing and model inference. |
| `assets/` | Static files | Auto-served by Dash. CSS, JS, images, logos. |
| `src/three/` | Three.js TypeScript | Compiled to `assets/three-scenes.js` via esbuild. |
| `frozen models/` | ML artifacts | Read-only. Do not modify without retraining. |

## Code Style

### Python

- **No linter or formatter is configured.** Follow the existing style in each file.
- Use 4-space indentation.
- Use single quotes for strings where practical (the codebase mixes single and double).
- Import heavy libraries (`pandas`, `numpy`, `plotly`, etc.) inside functions when used in `logic/` modules, to reduce startup memory.
- Use `logger.info()` / `logger.error()` for logging in `logic/` modules (configured via Python `logging`).
- Use `print()` for debug output in `pages/` modules (Dash convention).

### Callbacks

- **Server-side callbacks** go in the relevant `pages/*.py` file or `app.py` (for global callbacks).
- **Background callbacks** must use the `background=True` parameter and handle progress via `set_progress`.
- **Clientside callbacks** (JavaScript) go in `app.py` using `app.clientside_callback()`.
- Use `prevent_initial_call=True` on all callbacks unless they need to fire on page load.
- Use `allow_duplicate=True` when multiple callbacks write to the same output.

### CSS

- All styles are in `assets/style.css` (single file, ~3,500 lines).
- CSS custom properties (variables) are defined at `:root` for the dark theme and overridden in `.light-theme` for the light theme.
- Class naming: kebab-case (e.g., `chat-bubble-ai`, `scenario-slider-group`).
- Use `var(--property-name)` for colors and spacing to support theming.

### JavaScript

- `assets/interactions.js` handles client-side interactions (resize, scroll, sidebar).
- `assets/three-scenes.js` is a compiled bundle -- edit `src/three/*.ts` instead.

### TypeScript (Three.js)

- Source in `src/three/`.
- Build target: ES2020, bundled as IIFE with global name `DashScenes`.
- `tsconfig.json` is configured with strict mode.

## Naming Conventions

### Dash Component IDs

- Use kebab-case: `fetch-trigger`, `model-prediction-data`, `chat-send-btn`.
- Stores use descriptive names ending in context: `fetched-data`, `scenario-baseline-data`.
- Triggers end with `-trigger`: `fetch-trigger`, `model-prediction-trigger`.

### Data Columns

- Raw Supabase columns match the source naming: `EPU(USA)`, `WUIZAF(SA)`, `10_YEAR_BOND_RATES(SA)`.
- Engineered features use snake_case: `ZAR_USD_lag1`, `VIX_zscore12`, `bond_spread_change1`.
- The mapping between raw and engineered names is defined in `logic/model.py` (`FEATURE_LIST`, `BASE_FEATURE_NAMES`).

### File Naming

- Python: snake_case (`data_fetcher.py`, `supabase_client.py`).
- TypeScript: PascalCase for classes (`LandingScene.ts`, `CardDepth.ts`), camelCase for utilities (`noise.ts`).
- Assets: kebab-case or descriptive (`three-scenes.js`, `interactions.js`).

## Architecture Constraints

When making changes, keep these constraints in mind:

1. **512MB RAM limit** -- The app runs on Render's starter tier. Avoid loading large datasets into memory simultaneously. Background callbacks must run sequentially (not in parallel).

2. **Single worker** -- Only one gunicorn worker with 4 threads. No inter-process state sharing except via DiskCache or Supabase.

3. **Frozen model** -- The ML model in `frozen models/zar_usd_forecast_model.pkl` is a trained artifact. Changing feature engineering in `logic/model.py` without retraining the model will produce incorrect predictions.

4. **Monthly data refresh** -- Data is fetched from external APIs only on the last day of each month. Don't add polling or frequent refresh logic.

5. **No test suite** -- There are no automated tests. Test changes manually by running the app locally.

## Adding a New Data Variable

1. Add the series configuration to `SERIES_CONFIG` in `logic/data_fetcher.py`.
2. Add the column name to the `valid_columns` set in `save_to_supabase()`.
3. Add the column to the `columns_to_keep` list in `process_data()`.
4. Add the corresponding column to the Supabase `data` table schema.
5. If the variable feeds into the model, update `engineer_features()` in `logic/model.py` and retrain the model.

## Adding a New Dashboard Tab

1. Add the tab navigation link in the `sidebar()` function in `pages/dashboard.py`.
2. Add the tab content layout (similar to existing `data_content`, `model_content`, `scenario_content` sections).
3. Add visibility toggle callbacks.
4. Update `dashboard-tab` store handling.

## Git Workflow

- Main branch: `main`.
- No branch protection or CI/CD is configured.
- Commit messages: brief description of what changed (the codebase uses short messages like "lastest with UIv5").
- The `.gitignore` excludes `.env`, `__pycache__/`, `.venv/`, `.DS_Store`, and `.idea/`.
