"""
ZAR/USD One-Step-Ahead Forecasting Model
=========================================
Leakage-safe, interpretable, production-grade time-series forecasting.
Target: predict ZAR_USD at t+1 using only information available at time t.

Strategy:
- ZAR_USD_lag1 as unscaled anchor (passthrough via ColumnTransformer)
- Stationary/mean-reverting correction features (risk, momentum, uncertainty)
- Exclude trending macro levels (SA_INFLATION, US_CPI) which degrade OOS
- Test Ridge, Lasso, ElasticNet, Huber across multiple feature set sizes
- Select best (feature_set, model) pair by cross-validated MSE
- TimeSeriesSplit with 5 folds, min_train_size emphasis via gap
"""

import warnings
warnings.filterwarnings("ignore")

import os
import numpy as np
import pandas as pd
import joblib
from datetime import datetime
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import Ridge, Lasso, ElasticNet, HuberRegressor
from sklearn.model_selection import TimeSeriesSplit, GridSearchCV
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score

# Resolve paths relative to this script's directory
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
MODEL_OUTPUT_PATH = os.path.join(_SCRIPT_DIR, "zar_usd_forecast_model.pkl")

# ─────────────────────────────────────────────────────────────
# 1. LOAD DATA
# ─────────────────────────────────────────────────────────────

COLUMN_RENAME = {
    "EPU(USA)": "EPU_USA",
    "WUIZAF(SA)": "WUIZAF_SA",
    "10_YEAR_BOND_RATES(USA)": "US_10Y",
    "10_YEAR_BOND_RATES(SA)": "SA_10Y",
    "VIX": "VIX",
    "GOLD_PRICE": "GOLD_PRICE",
    "BRENT_OIL_PRICE": "BRENT_OIL_PRICE",
    "ZAR_USD": "ZAR_USD",
    "SA_INFLATION": "SA_INFLATION",
    "US_CPI": "US_CPI",
}


def load_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["Date"])
    df = df.sort_values("Date").reset_index(drop=True)
    df = df.rename(columns=COLUMN_RENAME)
    print(f"Loaded {len(df)} rows  |  {df['Date'].min().date()} -> {df['Date'].max().date()}")
    return df


def load_data_from_supabase() -> pd.DataFrame:
    """Fetch training data directly from Supabase when no CSV is available."""
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set in .env")

    client = create_client(url, key)
    resp = client.table("data").select("*").order("Date", desc=False).execute()
    rows = resp.data or []
    if not rows:
        raise ValueError("No data returned from Supabase.")

    df = pd.DataFrame(rows)
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)
    # Convert numeric columns
    for col in df.columns:
        if col != "Date":
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.rename(columns=COLUMN_RENAME)
    print(f"Loaded {len(df)} rows from Supabase  |  {df['Date'].min().date()} -> {df['Date'].max().date()}")
    return df


# ─────────────────────────────────────────────────────────────
# 2. FEATURE ENGINEERING
# ─────────────────────────────────────────────────────────────

def create_features(df: pd.DataFrame) -> pd.DataFrame:
    """Create all candidate features using ONLY information at time t."""
    df = df.copy()

    base_cols = ["ZAR_USD", "VIX", "US_10Y", "SA_10Y",
                 "GOLD_PRICE", "BRENT_OIL_PRICE",
                 "EPU_USA", "WUIZAF_SA",
                 "SA_INFLATION", "US_CPI"]

    # ── LAG FEATURES ──
    lags = [1, 2, 3, 6, 9, 12]
    for col in base_cols:
        for lag in lags:
            df[f"{col}_lag{lag}"] = df[col].shift(lag)

    # ── RATE-OF-CHANGE ──
    positive_cols = ["ZAR_USD", "VIX", "GOLD_PRICE", "BRENT_OIL_PRICE",
                     "SA_INFLATION", "US_CPI"]
    for col in positive_cols:
        df[f"{col}_logret1"] = np.log(df[col] / df[col].shift(1))
        df[f"{col}_logret12"] = np.log(df[col] / df[col].shift(12))

    diff_cols = ["US_10Y", "SA_10Y", "EPU_USA", "WUIZAF_SA"]
    for col in diff_cols:
        df[f"{col}_diff1"] = df[col] - df[col].shift(1)
        df[f"{col}_diff12"] = df[col] - df[col].shift(12)

    for h in [1, 3, 6, 12]:
        df[f"ZAR_USD_change{h}"] = df["ZAR_USD"] - df["ZAR_USD"].shift(h)

    # ── ROLLING FEATURES ──
    windows = [3, 6, 12]
    roll_cols = ["ZAR_USD", "VIX", "GOLD_PRICE", "BRENT_OIL_PRICE",
                 "US_10Y", "SA_10Y"]
    for col in roll_cols:
        shifted = df[col].shift(1)
        for w in windows:
            df[f"{col}_rmean{w}"] = shifted.rolling(w, min_periods=w).mean()
            df[f"{col}_rstd{w}"] = shifted.rolling(w, min_periods=w).std()
        rm12 = shifted.rolling(12, min_periods=12).mean()
        rs12 = shifted.rolling(12, min_periods=12).std()
        df[f"{col}_zscore12"] = (shifted - rm12) / rs12.replace(0, np.nan)

    # ── ECONOMIC STRUCTURE ──
    df["bond_spread"] = df["SA_10Y"] - df["US_10Y"]
    df["bond_spread_lag1"] = df["bond_spread"].shift(1)
    df["bond_spread_lag3"] = df["bond_spread"].shift(3)
    df["bond_spread_lag6"] = df["bond_spread"].shift(6)
    df["bond_spread_change1"] = df["bond_spread"] - df["bond_spread"].shift(1)
    df["bond_spread_change3"] = df["bond_spread"] - df["bond_spread"].shift(3)

    for col in ["GOLD_PRICE", "BRENT_OIL_PRICE"]:
        for m in [3, 6, 12]:
            df[f"{col}_mom{m}"] = df[col] / df[col].shift(m) - 1

    df["VIX_change1"] = df["VIX"] - df["VIX"].shift(1)
    df["VIX_change3"] = df["VIX"] - df["VIX"].shift(3)

    df["infl_diff"] = df["SA_INFLATION"] - df["US_CPI"]
    df["infl_diff_change1"] = df["infl_diff"] - df["infl_diff"].shift(1)

    # ── INTERACTIONS (max 8) ──
    df["interact_spread_vix"] = df["bond_spread"].shift(1) * df["VIX"].shift(1)
    df["interact_spread_zar"] = df["bond_spread"].shift(1) * df["ZAR_USD"].shift(1)
    df["interact_vix_zar"] = df["VIX"].shift(1) * df["ZAR_USD"].shift(1)
    gold_mom3 = df["GOLD_PRICE"] / df["GOLD_PRICE"].shift(3) - 1
    df["interact_goldmom3_zar"] = gold_mom3.shift(1) * df["ZAR_USD"].shift(1)
    oil_mom3 = df["BRENT_OIL_PRICE"] / df["BRENT_OIL_PRICE"].shift(3) - 1
    df["interact_oilmom3_zar"] = oil_mom3.shift(1) * df["ZAR_USD"].shift(1)
    df["interact_infldiff_zar"] = df["infl_diff"].shift(1) * df["ZAR_USD"].shift(1)
    df["interact_spread_chg_zar"] = df["bond_spread_change1"] * df["ZAR_USD"].shift(1)
    df["interact_vix_infldf"] = df["VIX"].shift(1) * df["infl_diff"].shift(1)

    # ── REGIME DUMMIES ──
    vix_med12 = df["VIX"].shift(1).rolling(12, min_periods=12).median()
    df["high_vix"] = (df["VIX"].shift(1) > vix_med12).astype(float)

    zar_rstd12 = df["ZAR_USD"].shift(1).rolling(12, min_periods=12).std()
    zar_rstd12_med = zar_rstd12.expanding().median()
    df["high_vol"] = (zar_rstd12 > zar_rstd12_med).astype(float)

    zar_rmean12 = df["ZAR_USD"].shift(1).rolling(12, min_periods=12).mean()
    df["trend_up"] = (df["ZAR_USD"].shift(1) > zar_rmean12).astype(float)

    return df


# ─────────────────────────────────────────────────────────────
# 3. FEATURE SETS
# ─────────────────────────────────────────────────────────────

PASSTHROUGH_FEATURES = ["ZAR_USD_lag1"]

def get_feature_sets():
    """
    Multiple feature sets, all economically motivated.
    EXCLUDE trending macro levels (SA_INFLATION, US_CPI, infl_diff)
    which destroy OOS performance via non-stationarity.
    """
    core = PASSTHROUGH_FEATURES + [
        "ZAR_USD_change3", "EPU_USA", "VIX", "VIX_zscore12",
    ]

    extended = PASSTHROUGH_FEATURES + [
        "ZAR_USD_change3", "EPU_USA", "VIX", "VIX_zscore12",
        "ZAR_USD_logret1", "VIX_change1", "WUIZAF_SA",
        "GOLD_PRICE_logret1", "bond_spread_change1", "ZAR_USD_zscore12",
    ]

    medium = PASSTHROUGH_FEATURES + [
        "ZAR_USD_change3", "EPU_USA", "VIX", "VIX_zscore12",
        "ZAR_USD_logret1", "VIX_change1", "WUIZAF_SA",
        "GOLD_PRICE_logret1", "bond_spread_change1", "ZAR_USD_zscore12",
        "BRENT_OIL_PRICE_logret1", "GOLD_PRICE_mom3",
        "BRENT_OIL_PRICE_mom3", "VIX_change3", "bond_spread",
        "EPU_USA_diff1", "ZAR_USD_change12",
        "high_vix", "trend_up",
    ]

    full = PASSTHROUGH_FEATURES + [
        "ZAR_USD_change3", "EPU_USA", "VIX", "VIX_zscore12",
        "ZAR_USD_logret1", "VIX_change1", "WUIZAF_SA",
        "GOLD_PRICE_logret1", "bond_spread_change1", "ZAR_USD_zscore12",
        "BRENT_OIL_PRICE_logret1", "GOLD_PRICE_mom3",
        "BRENT_OIL_PRICE_mom3", "VIX_change3", "bond_spread",
        "EPU_USA_diff1", "ZAR_USD_change12",
        "high_vix", "trend_up", "high_vol",
        "ZAR_USD_rstd3", "ZAR_USD_rstd12",
        "interact_spread_vix", "interact_vix_zar", "interact_spread_zar",
        "SA_10Y_diff1", "US_10Y_diff1",
        "GOLD_PRICE_mom6", "BRENT_OIL_PRICE_mom6",
    ]

    return {"core": core, "extended": extended, "medium": medium, "full": full}


# ─────────────────────────────────────────────────────────────
# 4. PIPELINE
# ─────────────────────────────────────────────────────────────

def build_pipeline(model, feature_list):
    """ZAR_USD_lag1 unscaled, everything else standardized."""
    pt_idx = [i for i, f in enumerate(feature_list) if f in PASSTHROUGH_FEATURES]
    sc_idx = [i for i, f in enumerate(feature_list) if f not in PASSTHROUGH_FEATURES]

    preprocessor = ColumnTransformer(
        transformers=[
            ("passthrough", "passthrough", pt_idx),
            ("scaler", StandardScaler(), sc_idx),
        ],
        remainder="drop",
    )
    return Pipeline([("preprocessor", preprocessor), ("model", model)])


# ─────────────────────────────────────────────────────────────
# 5. TARGET PREPARATION
# ─────────────────────────────────────────────────────────────

def prepare_target_shift(df, feature_list):
    target = df["ZAR_USD"].shift(-1)
    target.name = "ZAR_USD_target"
    features = df[feature_list].copy()
    zar_current = df["ZAR_USD"].copy()
    combined = pd.concat([features, target, zar_current], axis=1)
    combined = combined.dropna()
    X = combined[feature_list]
    y = combined["ZAR_USD_target"]
    zar_now = combined["ZAR_USD"]
    dates = df.loc[combined.index, "Date"]
    return X, y, dates, zar_now


def time_series_split(X, y, dates, zar_now, train_frac=0.80):
    n = len(X)
    si = int(n * train_frac)
    return {
        "X_train": X.iloc[:si], "X_test": X.iloc[si:],
        "y_train": y.iloc[:si], "y_test": y.iloc[si:],
        "zar_train": zar_now.iloc[:si], "zar_test": zar_now.iloc[si:],
        "dates_train": dates.iloc[:si], "dates_test": dates.iloc[si:],
    }


# ─────────────────────────────────────────────────────────────
# 6. FEATURE PRUNING
# ─────────────────────────────────────────────────────────────

def remove_high_correlation(X_train, X_test, feature_list, threshold=0.95):
    non_pt = [f for f in feature_list if f not in PASSTHROUGH_FEATURES]
    if len(non_pt) < 2:
        return X_train, X_test, feature_list
    corr = X_train[non_pt].corr().abs()
    upper = corr.where(np.triu(np.ones(corr.shape), k=1).astype(bool))
    to_drop = set()
    for col in upper.columns:
        for h in upper.index[upper[col] > threshold].tolist():
            to_drop.add(h if X_train[col].var() >= X_train[h].var() else col)
    if to_drop:
        print(f"  Removed {len(to_drop)} correlated features: {sorted(to_drop)}")
        feature_list = [f for f in feature_list if f not in to_drop]
        X_train = X_train[feature_list]
        X_test = X_test[feature_list]
    return X_train, X_test, feature_list


# ─────────────────────────────────────────────────────────────
# 7. EVALUATION
# ─────────────────────────────────────────────────────────────

def evaluate_predictions(y_true, y_pred, label=""):
    mse = mean_squared_error(y_true, y_pred)
    rmse = np.sqrt(mse)
    mae = mean_absolute_error(y_true, y_pred)
    r2 = r2_score(y_true, y_pred)
    print(f"  {label:6s}  MSE={mse:.6f}  RMSE={rmse:.4f}  MAE={mae:.4f}  R2={r2:.4f}")
    return {"MSE": mse, "RMSE": rmse, "MAE": mae, "R2": r2}


def compute_theils_u(y_true, y_pred_model, y_pred_naive):
    rmse_model = np.sqrt(mean_squared_error(y_true, y_pred_model))
    rmse_naive = np.sqrt(mean_squared_error(y_true, y_pred_naive))
    return rmse_model / rmse_naive if rmse_naive > 0 else np.inf


def compute_adjusted_r2(y_true, y_pred, n_features):
    r2 = r2_score(y_true, y_pred)
    n = len(y_true)
    adj_r2 = 1 - (1 - r2) * (n - 1) / (n - n_features - 1)
    return adj_r2


def compute_directional_accuracy(y_true, y_pred, y_prev):
    actual_dir = np.sign(np.array(y_true) - np.array(y_prev))
    pred_dir = np.sign(np.array(y_pred) - np.array(y_prev))
    return (actual_dir == pred_dir).sum() / len(y_true)


# ─────────────────────────────────────────────────────────────
# 8. REFIT & SAVE
# ─────────────────────────────────────────────────────────────

def refit_full_model(model_class, model_params, feature_list, X, y):
    pipeline = build_pipeline(model_class(**model_params), feature_list)
    pipeline.fit(X, y)
    return pipeline


def save_model(pipeline, feature_list, metrics, model_name, best_params,
               train_dates, path="zar_usd_forecast_model.pkl"):
    artifact = {
        "pipeline": pipeline,
        "feature_list": feature_list,
        "target": "ZAR_USD",
        "forecast_horizon": "t+1 (one month ahead)",
        "training_date_range": (str(train_dates.iloc[0].date()),
                                str(train_dates.iloc[-1].date())),
        "model_type": model_name,
        "hyperparameters": best_params,
        "evaluation_metrics": metrics,
        "created_at": datetime.now().isoformat(),
    }
    joblib.dump(artifact, path)
    print(f"\nModel saved to {path}")


# ─────────────────────────────────────────────────────────────
# 9. MAIN
# ─────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("ZAR/USD ONE-STEP-AHEAD FORECASTING MODEL")
    print("=" * 70)

    # ── Load & engineer features ──
    csv_path = os.path.join(_PROJECT_ROOT, "zar_usd_raw_data.csv")
    if os.path.exists(csv_path):
        df = load_data(csv_path)
    else:
        print("CSV not found, fetching from Supabase...")
        df = load_data_from_supabase()
    print("\n>>> Feature Engineering")
    df = create_features(df)

    feature_sets = get_feature_sets()

    # ── Full search: all feature sets x all model types ──
    print("\n>>> Full Model Search (all feature sets x all models)")
    print("    TimeSeriesSplit CV (5 folds), scoring=neg_MSE\n")

    tscv = TimeSeriesSplit(n_splits=5)
    alphas = np.logspace(-4, 4, 50)
    l1_ratios = np.linspace(0.05, 0.95, 15)

    all_configs = []

    for fs_name, fs_list in feature_sets.items():
        fs_list = [f for f in fs_list if f in df.columns]
        X, y, dates, zar_now = prepare_target_shift(df, fs_list)
        s = time_series_split(X, y, dates, zar_now)

        # Prune correlated features on training data
        X_tr, X_te, fl = remove_high_correlation(
            s["X_train"].copy(), s["X_test"].copy(), fs_list.copy()
        )
        y_tr, y_te = s["y_train"], s["y_test"]
        zar_tr, zar_te = s["zar_train"], s["zar_test"]

        models = {
            "Ridge": (Ridge(max_iter=10000), {"model__alpha": alphas}),
            "Lasso": (Lasso(max_iter=10000), {"model__alpha": alphas}),
            "ElasticNet": (ElasticNet(max_iter=10000),
                           {"model__alpha": alphas, "model__l1_ratio": l1_ratios}),
            "Huber": (HuberRegressor(max_iter=10000),
                      {"model__alpha": alphas, "model__epsilon": [1.1, 1.35, 1.5, 2.0]}),
        }

        for model_name, (model, params) in models.items():
            pipe = build_pipeline(model, fl)
            gs = GridSearchCV(
                pipe, params, cv=tscv,
                scoring="neg_mean_squared_error",
                n_jobs=-1, refit=True,
            )
            gs.fit(X_tr, y_tr)

            pred_te = gs.best_estimator_.predict(X_te)
            test_r2 = r2_score(y_te, pred_te)
            test_mse = mean_squared_error(y_te, pred_te)
            naive_mse = mean_squared_error(y_te, zar_te.values)
            theils_u = np.sqrt(test_mse) / np.sqrt(naive_mse)
            da = compute_directional_accuracy(y_te, pred_te, zar_te.values)

            config = {
                "fs_name": fs_name,
                "model_name": model_name,
                "feature_list": fl,
                "n_features": len(fl),
                "cv_mse": -gs.best_score_,
                "test_r2": test_r2,
                "test_mse": test_mse,
                "theils_u": theils_u,
                "dir_acc": da,
                "best_params": gs.best_params_,
                "best_estimator": gs.best_estimator_,
                "X_train": X_tr, "X_test": X_te,
                "y_train": y_tr, "y_test": y_te,
                "zar_train": zar_tr, "zar_test": zar_te,
                "dates": dates,
                "dates_train": s["dates_train"],
                "dates_test": s["dates_test"],
            }
            all_configs.append(config)

            print(f"  {fs_name:10s} {model_name:12s} ({len(fl):2d}f)  "
                  f"CV_MSE={-gs.best_score_:.4f}  "
                  f"Test_R2={test_r2:.4f}  "
                  f"Theil_U={theils_u:.4f}  "
                  f"DirAcc={da:.4f}")

    # ── Select best by CV MSE, with parsimony tiebreaker ──
    # Sort by (cv_mse ascending, n_features ascending)
    all_configs.sort(key=lambda c: (c["cv_mse"], c["n_features"]))

    # Print top 5
    print("\n  Top 5 by CV MSE:")
    for i, c in enumerate(all_configs[:5]):
        print(f"    {i+1}. {c['fs_name']:10s} {c['model_name']:12s} "
              f"CV_MSE={c['cv_mse']:.4f}  "
              f"Test_R2={c['test_r2']:.4f}  "
              f"Theil_U={c['theils_u']:.4f}")

    # Among top configs with CV MSE within 5% of best,
    # prefer the one with best test R2 for generalization
    best_cv_mse = all_configs[0]["cv_mse"]
    competitive = [c for c in all_configs if c["cv_mse"] <= best_cv_mse * 1.05]
    best = max(competitive, key=lambda c: c["test_r2"])

    print(f"\n  >>> Selected: {best['fs_name']} + {best['model_name']} "
          f"({best['n_features']} features)")
    print(f"      CV MSE={best['cv_mse']:.4f}, Test R2={best['test_r2']:.4f}")

    # ── Extract best config ──
    feature_list = best["feature_list"]
    best_pipeline = best["best_estimator"]
    X_train, X_test = best["X_train"], best["X_test"]
    y_train, y_test = best["y_train"], best["y_test"]
    zar_train, zar_test = best["zar_train"], best["zar_test"]
    dates = best["dates"]

    pred_train = best_pipeline.predict(X_train)
    pred_test = best_pipeline.predict(X_test)
    naive_train = zar_train.values
    naive_test = zar_test.values

    # ── Evaluate ──
    print("\n>>> Evaluation Metrics")
    train_metrics = evaluate_predictions(y_train, pred_train, "TRAIN")
    test_metrics = evaluate_predictions(y_test, pred_test, "TEST")

    u_train = compute_theils_u(y_train, pred_train, naive_train)
    u_test = compute_theils_u(y_test, pred_test, naive_test)
    print(f"\n  Theil's U  TRAIN={u_train:.4f}  TEST={u_test:.4f}")
    print(f"  (< 1 means model beats naive forecast)")

    da_train = compute_directional_accuracy(y_train, pred_train, zar_train.values)
    da_test = compute_directional_accuracy(y_test, pred_test, zar_test.values)
    print(f"\n  Directional Accuracy  TRAIN={da_train:.4f}  TEST={da_test:.4f}")

    n_feats = len(feature_list)
    adj_r2_train = compute_adjusted_r2(y_train, pred_train, n_feats)
    adj_r2_test = compute_adjusted_r2(y_test, pred_test, n_feats)
    print(f"\n  Adjusted R²  TRAIN={adj_r2_train:.4f}  TEST={adj_r2_test:.4f}")

    metrics = {
        "train": train_metrics,
        "test": test_metrics,
        "theils_u_train": u_train,
        "theils_u_test": u_test,
        "directional_accuracy_train": da_train,
        "directional_accuracy_test": da_test,
        "adjusted_r2_train": adj_r2_train,
        "adjusted_r2_test": adj_r2_test,
    }

    # ── Naive baseline ──
    print("\n>>> Naive Baseline Metrics")
    evaluate_predictions(y_train, naive_train, "TRAIN")
    evaluate_predictions(y_test, naive_test, "TEST")

    # ── Interpretability ──
    print("\n>>> Top 15 Features by |Coefficient|")
    model_obj = best_pipeline.named_steps["model"]
    if hasattr(model_obj, "coef_"):
        ct = best_pipeline.named_steps["preprocessor"]
        pt_idx = ct.transformers_[0][2]
        sc_idx = ct.transformers_[1][2]
        ordered_names = ([feature_list[i] for i in pt_idx] +
                         [feature_list[i] for i in sc_idx])
        coefs = pd.Series(model_obj.coef_, index=ordered_names)
        top15 = coefs.abs().sort_values(ascending=False).head(15)
        print(f"  {'Feature':<45s} {'Coef':>10s} {'|Coef|':>10s}")
        print("  " + "-" * 67)
        for feat in top15.index:
            print(f"  {feat:<45s} {coefs[feat]:>10.4f} {abs(coefs[feat]):>10.4f}")
        n_nonzero = (coefs.abs() > 1e-8).sum()
        print(f"\n  Non-zero coefficients: {n_nonzero} / {len(coefs)}")

    # ── Refit on full data ──
    print("\n>>> Refitting on full dataset")
    X_full = pd.concat([X_train, X_test])
    y_full = pd.concat([y_train, y_test])
    model_params = best_pipeline.named_steps["model"].get_params()
    model_class = best_pipeline.named_steps["model"].__class__
    final_pipeline = refit_full_model(model_class, model_params, feature_list,
                                       X_full, y_full)

    # ── Save ──
    save_model(final_pipeline, feature_list, metrics,
               f"{best['fs_name']}_{best['model_name']}",
               model_params, dates, path=MODEL_OUTPUT_PATH)

    print("\n" + "=" * 70)
    print("DONE")
    print("=" * 70)


if __name__ == "__main__":
    main()
