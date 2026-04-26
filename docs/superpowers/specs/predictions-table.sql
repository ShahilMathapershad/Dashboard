-- Single-row-per-model-version cache for pre-computed dashboard payloads.
-- Read path: SELECT * FROM predictions WHERE model_version = $current.
-- Refresh path: INSERT ... ON CONFLICT (model_version) DO UPDATE.
-- No history retained; last write wins per model version.
CREATE TABLE IF NOT EXISTS predictions (
    model_version           text PRIMARY KEY,
    cache_contract_version  integer NOT NULL,
    computed_at             timestamptz NOT NULL,
    data_through            date NOT NULL,
    refresh_status          text NOT NULL,
    forecasts               jsonb NOT NULL,
    feature_contributions   jsonb NOT NULL,
    fit_history             jsonb NOT NULL,
    scenario_baseline       jsonb NOT NULL,
    updated_at              timestamptz NOT NULL DEFAULT now()
);

-- The dashboard hydrate callback runs on every page load — make sure
-- it's a single fast indexed lookup.
CREATE INDEX IF NOT EXISTS predictions_model_version_idx
    ON predictions (model_version);

-- Trigger to bump updated_at on every UPSERT.
CREATE OR REPLACE FUNCTION set_predictions_updated_at()
RETURNS trigger AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS predictions_set_updated_at ON predictions;
CREATE TRIGGER predictions_set_updated_at
    BEFORE INSERT OR UPDATE ON predictions
    FOR EACH ROW EXECUTE FUNCTION set_predictions_updated_at();
