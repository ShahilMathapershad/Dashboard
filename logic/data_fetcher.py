import pandas as pd
from fredapi import Fred
import yfinance as yf
import os
import ssl
import time
import json
import urllib.request
import urllib.parse
import logging
from collections.abc import Mapping
from logic.supabase_client import supabase
try:
    from econdatapy import read as econdata_read
except Exception:
    econdata_read = None

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DataFetcher")

# Bypass SSL verification for FRED API calls if needed
ssl._create_default_https_context = ssl._create_unverified_context

# Series Configuration
# Unified names to be used throughout the app
SERIES_CONFIG = {
    'EPU(USA)': {'source': 'FRED', 'id': 'USEPUINDXM', 'label': 'Economic Policy Uncertainty Index for USA'},
    'WUIZAF(SA)': {'source': 'FRED', 'id': 'WUIZAF', 'label': 'World Uncertainty Index for South Africa'},
    '10_YEAR_BOND_RATES(USA)': {'source': 'FRED', 'id': 'GS10', 'label': '10-Year Treasury Constant Maturity Rate (USA)'},
    '10_YEAR_BOND_RATES(SA)': {'source': 'FRED', 'id': 'IRLTLT01ZAM156N', 'label': '10-Year Bond Rate (South Africa)'},
    'USA_CPI': {'source': 'FRED', 'id': 'CPALTT01USM659N', 'label': 'CPI for All Items for USA'},
    'SA_CPI_FRED': {'source': 'FRED', 'id': 'CPALTT01ZAM659N', 'label': 'CPI for All Items for South Africa (FRED)'},
    'BUSINESS_CYCLES': {'source': 'ECONDATA', 'id': 'BUSINESS_CYCLES', 'label': 'Business Cycles (EconData)'},
    'SA_CPI_ECON': {'source': 'ECONDATA', 'id': 'SARB_6006K', 'label': 'CPI for South Africa (EconData)'},
    'VIX': {'source': 'FRED', 'id': 'VIXCLS', 'label': 'CBOE Volatility Index (VIX)'},
    'GOLD_PRICE': {'source': 'YAHOO', 'id': 'GLD', 'label': 'SPDR Gold Shares (GLD) Monthly Mean Close (Yahoo Finance)'},
    'BRENT_OIL_PRICE': {'source': 'FRED', 'id': 'POILBREUSDM', 'label': 'Global Price of Brent Crude'},
    'US_CPI': {'source': 'FRED', 'id': 'CPIAUCSL', 'label': 'Consumer Price Index for All Urban Consumers (USA)'},
    'ZAR_USD': {'source': 'FRED', 'id': 'DEXSFUS', 'label': 'South African Rand to U.S. Dollar Exchange Rate'}
}

def get_api_keys():
    """Reads API keys from api_keys.txt."""
    keys = {'FRED': None, 'EconData': None}
    try:
        # Try different paths to find api_keys.txt
        possible_paths = [
            'api_keys.txt',
            os.path.join(os.getcwd(), 'api_keys.txt'),
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'api_keys.txt')
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                with open(path, 'r') as f:
                    for line in f:
                        if '=' in line:
                            key, val = line.split('=', 1)
                            keys[key.strip()] = val.strip()
                break
    except Exception as e:
        logger.error(f"Error reading api_keys.txt: {e}")
    return keys

API_KEYS = get_api_keys()
FRED_API_KEY = os.environ.get('FRED_API_KEY', API_KEYS.get('FRED') or 'e9e60c2ca97eac250d9bdb7d22511d58')
ECONDATA_TOKEN = os.environ.get('ECONDATA_TOKEN', API_KEYS.get('EconData'))

def _extract_dataframes(payload):
    """Extract DataFrames from nested dict/list payloads."""
    if isinstance(payload, pd.DataFrame):
        return [payload]
    if isinstance(payload, Mapping):
        dfs = []
        for value in payload.values():
            dfs.extend(_extract_dataframes(value))
        return dfs
    if isinstance(payload, (list, tuple)):
        dfs = []
        for value in payload:
            dfs.extend(_extract_dataframes(value))
        return dfs
    return []

def _to_monthly(series):
    """Normalize any date-indexed series to month-end frequency."""
    if series.empty:
        return series
    series = series.sort_index()
    try:
        monthly = series.resample('ME').last()
    except ValueError:
        monthly = series.resample('M').last()
    return monthly.dropna()

def _series_from_dataframe(df):
    """Build a date-indexed numeric series from an arbitrary EconData table."""
    if df is None or df.empty:
        return pd.Series(dtype='float64')

    date_col_candidates = ['date', 'period', 'time_period', 'obs_time', 'timestamp']
    value_col_candidates = ['value', 'obs_value', 'observation', 'price', 'index']

    columns_lower = {str(col).lower(): col for col in df.columns}

    date_col = None
    for name in date_col_candidates:
        if name in columns_lower:
            date_col = columns_lower[name]
            break

    if date_col is None:
        return pd.Series(dtype='float64')

    value_col = None
    for name in value_col_candidates:
        if name in columns_lower:
            value_col = columns_lower[name]
            break

    if value_col is None:
        best_col = None
        best_count = 0
        for col in df.columns:
            if col == date_col:
                continue
            numeric_values = pd.to_numeric(df[col], errors='coerce')
            valid_count = int(numeric_values.notna().sum())
            if valid_count > best_count:
                best_count = valid_count
                best_col = col
        value_col = best_col

    if value_col is None:
        return pd.Series(dtype='float64')

    parsed_dates = pd.to_datetime(df[date_col], errors='coerce')
    parsed_values = pd.to_numeric(df[value_col], errors='coerce')
    series_df = pd.DataFrame({'date': parsed_dates, 'value': parsed_values}).dropna(subset=['date', 'value'])
    if series_df.empty:
        return pd.Series(dtype='float64')

    series_df = series_df.sort_values('date')
    series_df.set_index('date', inplace=True)
    return series_df['value']

def _fetch_econdatapy_data(series_id, token):
    """Fetch EconData series via econdatapy, following the Colab workflow."""
    if econdata_read is None:
        return pd.Series(dtype='float64')

    bearer = token if token.startswith('Bearer ') else f"Bearer {token}"
    econdata_read.econdata_token = bearer

    attempts = [(series_id, {})]
    if series_id != 'BUSINESS_CYCLES':
        attempts.append(('BUSINESS_CYCLES', {'series_key': series_id}))

    for dataset_id, params in attempts:
        try:
            logger.info(f"Attempting EconData SDK fetch: dataset={dataset_id}, params={params}")
            raw = econdata_read.dataset(dataset_id, **params)
            dataframes = _extract_dataframes(raw)
            if not dataframes:
                logger.warning(f"EconData SDK returned no tables for dataset={dataset_id}")
                continue

            parsed_series = []
            for table in dataframes:
                series = _series_from_dataframe(table)
                if not series.empty:
                    parsed_series.append(series)

            if not parsed_series:
                logger.warning(f"EconData SDK tables had no parsable date/value series for dataset={dataset_id}")
                continue

            best_series = max(parsed_series, key=len)
            monthly_series = _to_monthly(best_series)
            if not monthly_series.empty:
                logger.info(f"Successfully fetched {series_id} via EconData SDK ({len(monthly_series)} monthly rows).")
                return monthly_series
        except Exception as e:
            logger.warning(f"EconData SDK fetch failed for dataset={dataset_id}: {e}")

    return pd.Series(dtype='float64')

def fetch_econdata_data(series_id, token=None):
    """Fetches data from EconData API for a given series_id."""
    if not token:
        token = ECONDATA_TOKEN
    
    if not token:
        logger.error(f"EconData token not found. Skipping {series_id}.")
        return pd.Series(dtype='float64')

    # First try the official EconData SDK flow (same path as user's working script).
    sdk_series = _fetch_econdatapy_data(series_id, token)
    if not sdk_series.empty:
        return sdk_series
    
    # Try multiple common endpoint patterns for EconData
    urls = [
        f"https://www.econdata.co.za/api/series/{series_id}/data",
        f"https://www.econdata.co.za/api/v1/series/{series_id}/data",
    ]
    
    headers = {
        'Authorization': f"Bearer {token}",
        'Content-Type': 'application/json'
    }
    
    for url in urls:
        logger.info(f"Attempting EconData fetch for {series_id} at {url}")
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())
                
                df = None
                # EconData usually returns a list of { "date": "...", "value": ... }
                if isinstance(data, list):
                    df = pd.DataFrame(data)
                elif 'data' in data: # sometimes it's wrapped in a 'data' key
                    df = pd.DataFrame(data['data'])
                
                if df is not None and not df.empty:
                    series = _series_from_dataframe(df)
                    if not series.empty:
                        series = _to_monthly(series)
                        logger.info(f"Successfully fetched {series_id} from EconData HTTP endpoint ({len(series)} monthly rows).")
                        return series
                    logger.warning(f"EconData HTTP returned data but no parsable date/value series for {series_id}")
                else:
                    logger.warning(f"EconData returned empty or unexpected format for {series_id}")
        except Exception as e:
            logger.warning(f"Failed to fetch {series_id} from {url}: {e}")
            
    logger.error(f"All EconData fetch attempts failed for {series_id}.")
    return pd.Series(dtype='float64')

def fetch_fred_data(series_dict, api_key=None, progress_callback=None):
    """Fetches data from FRED for each series in the dictionary."""
    if not api_key:
        api_key = FRED_API_KEY
    
    try:
        logger.info(f"Initializing Fred with API key (length: {len(api_key) if api_key else 0}).")
        fred = Fred(api_key=api_key)
    except Exception as e:
        logger.error(f"Error initializing FRED with provided key: {e}")
        return pd.DataFrame()

    df_list = []
    total = len(series_dict)
    for i, (name, series_id) in enumerate(series_dict.items()):
        # Calculate percentage: i is current index, (i/total)*100 is starting, ((i+1)/total)*100 is finished
        percent_start = int((i / total) * 100)
        try:
            if progress_callback:
                progress_callback(percent_start, f"Fetching {name}...")
            
            logger.info(f"Fetching FRED series: {name} ({series_id})")
            s = fred.get_series(series_id)
            df = s.to_frame(name=name)
            df_list.append(df)
            
            # Successfully fetched, report updated percentage
            percent_done = int(((i + 1) / total) * 100)
            if progress_callback:
                progress_callback(percent_done, f"Fetched {name}")
                
            time.sleep(0.5) # Avoid rate limiting
        except Exception as e:
            logger.error(f"Error fetching {series_id} from FRED: {e}")
            percent_err = int(((i + 1) / total) * 100)
            if progress_callback:
                progress_callback(percent_err, f"Error: {name}")
    
    if progress_callback:
        progress_callback(100, "Processing data...")
    
    if not df_list:
        return pd.DataFrame()
    
    combined_df = pd.concat(df_list, axis=1, sort=True)
    return combined_df

def fetch_yahoo_gold_data(ticker='GLD', start_date='2010-01-01', end_date=None):
    """Fetches GLD from Yahoo and returns monthly mean of daily close prices."""
    if end_date is None:
        end_date = pd.Timestamp.now().strftime('%Y-%m-%d')

    logger.info(f"Fetching Yahoo Finance data for {ticker} from {start_date} to {end_date}.")
    try:
        data = yf.download(ticker, start=start_date, end=end_date, progress=False, auto_adjust=False)
    except Exception as e:
        logger.error(f"Error fetching Yahoo data for {ticker}: {e}")
        return pd.Series(dtype='float64')

    if data is None or data.empty:
        logger.warning(f"Yahoo returned no data for {ticker}.")
        return pd.Series(dtype='float64')

    close_series = data.get('Close')
    if close_series is None:
        logger.warning(f"Yahoo data for {ticker} is missing Close.")
        return pd.Series(dtype='float64')

    if isinstance(close_series, pd.DataFrame):
        if ticker in close_series.columns:
            close_series = close_series[ticker]
        else:
            close_series = close_series.iloc[:, 0]

    close_series = pd.to_numeric(close_series, errors='coerce').dropna()
    if close_series.empty:
        logger.warning(f"Yahoo Close series is empty for {ticker} after cleaning.")
        return pd.Series(dtype='float64')

    # User requested monthly mean using daily observations.
    try:
        monthly_gold = close_series.resample('ME').mean()
    except ValueError:
        monthly_gold = close_series.resample('M').mean()

    monthly_gold.name = 'GOLD_PRICE'
    logger.info(f"Fetched {len(monthly_gold)} monthly GOLD_PRICE observations from Yahoo ({ticker}).")
    return monthly_gold

def process_data(final_df, start_date='2000-01-01', end_date=None):
    """Processes the raw data (sorting, resampling, filling, etc.)."""
    
    # If end_date is not provided, use the end of the previous month
    if end_date is None:
        now = pd.Timestamp.now()
        # End of previous month: first day of current month minus one day
        end_of_prev_month = (now.replace(day=1) - pd.Timedelta(days=1))
        end_date = end_of_prev_month.strftime('%Y-%m-%d')
    
    # Sort index
    final_df = final_df.sort_index()
    
    # Resample to monthly (End of Month) and take the last value
    # Older pandas used 'M', newer use 'ME'
    try:
        final_df_monthly = final_df.resample('ME').last()
    except ValueError:
        final_df_monthly = final_df.resample('M').last()
    
    # Forward fill missing values
    final_df_monthly = final_df_monthly.ffill()
    
    # Filter by date range if provided
    final_df_monthly = final_df_monthly.loc[start_date:end_date]
    
    # Build explicit inflation columns:
    # SA_INFLATION <- BUSINESS_CYCLES (EconData)
    business_cycles_col = None
    if 'BUSINESS_CYCLES' in final_df_monthly.columns and not final_df_monthly['BUSINESS_CYCLES'].isnull().all():
        business_cycles_col = 'BUSINESS_CYCLES'
    elif 'ECON_BUSINESS_CYCLES' in final_df_monthly.columns and not final_df_monthly['ECON_BUSINESS_CYCLES'].isnull().all():
        business_cycles_col = 'ECON_BUSINESS_CYCLES'
    elif 'ECON_SA_CPI' in final_df_monthly.columns and not final_df_monthly['ECON_SA_CPI'].isnull().all():
        # Backward compatibility with old EconData column naming.
        business_cycles_col = 'ECON_SA_CPI'

    if business_cycles_col:
        final_df_monthly['SA_INFLATION'] = pd.to_numeric(final_df_monthly[business_cycles_col], errors='coerce')
    else:
        logger.warning("Could not set SA_INFLATION: BUSINESS_CYCLES column missing.")
    
    # Keep only requested columns in the specified order
    columns_to_keep = [
        'EPU(USA)', 
        'WUIZAF(SA)', 
        '10_YEAR_BOND_RATES(USA)', 
        '10_YEAR_BOND_RATES(SA)', 
        'SA_INFLATION',
        'VIX', 
        'GOLD_PRICE', 
        'BRENT_OIL_PRICE', 
        'US_CPI',
        'ZAR_USD'
    ]
    
    # Check if all columns exist (in case some failed to fetch)
    existing_columns = [col for col in columns_to_keep if col in final_df_monthly.columns]
    final_df_monthly = final_df_monthly[existing_columns]
    
    # Remove rows with NaN in ZAR_USD (our target)
    if 'ZAR_USD' in final_df_monthly.columns:
        final_df_monthly = final_df_monthly.dropna(subset=['ZAR_USD'])
    
    final_df_monthly.index.name = 'Date'
    return final_df_monthly

def save_to_supabase(df):
    """Saves the processed DataFrame to the Supabase 'data' table."""
    if df.empty:
        logger.warning("No data to save.")
        return
    
    # Reset index to make Date a column
    df_to_save = df.reset_index()
    
    # Convert Date to string (ISO format) for JSON serialization
    df_to_save['Date'] = df_to_save['Date'].dt.strftime('%Y-%m-%d')
    
    # Replace NaNs with None
    df_to_save = df_to_save.where(pd.notnull(df_to_save), None)
    records = df_to_save.to_dict('records')
    
    for record in records:
        for key, value in record.items():
            if pd.isna(value):
                record[key] = None

        # Map app-level inflation keys to the current Supabase column names.
        if 'sa_inflation' in record:
            record['SA_INFLATION'] = record.pop('sa_inflation')
        if 'usa_inflation' in record:
            record['US_CPI'] = record.pop('usa_inflation')
    
    logger.info(f"Saving {len(records)} records to Supabase 'data' table...")
    
    if not supabase:
        logger.error("Supabase client not initialized.")
        return None
        
    try:
        valid_columns = {
            'Date', 'EPU(USA)', 'WUIZAF(SA)', '10_YEAR_BOND_RATES(USA)', 
            '10_YEAR_BOND_RATES(SA)', 'SA_INFLATION', 'VIX', 
            'GOLD_PRICE', 'BRENT_OIL_PRICE', 'US_CPI', 'ZAR_USD'
        }
        
        filtered_records = []
        for record in records:
            filtered_record = {k: v for k, v in record.items() if k in valid_columns}
            filtered_records.append(filtered_record)

        logger.info("Clearing existing data in Supabase...")
        supabase.table('data').delete().gte('Date', '1900-01-01').execute()

        response = supabase.table('data').upsert(filtered_records).execute()
        logger.info("Successfully saved data to Supabase.")
        return response
    except Exception as e:
        logger.error(f"Error saving to Supabase: {e}")
        return None

def fetch_and_save_data():
    """Main function to run the fetch, process, and save workflow."""
    logger.info("Starting main data fetch and save workflow.")
    
    # Fetch EconData Business Cycles
    logger.info("Fetching BUSINESS_CYCLES from EconData.")
    econ_business_cycles = fetch_econdata_data(SERIES_CONFIG['BUSINESS_CYCLES']['id'])
    
    # If first attempt fails, try legacy series key.
    if econ_business_cycles.empty:
        logger.info("Retrying EconData with legacy series_id 'SARB_6006K'")
        econ_business_cycles = fetch_econdata_data('SARB_6006K')
    
    # Prepare FRED series dictionary
    fred_series = {name: cfg['id'] for name, cfg in SERIES_CONFIG.items() if cfg['source'] == 'FRED'}
    
    logger.info(f"Fetching {len(fred_series)} series from FRED.")
    raw_df = fetch_fred_data(fred_series)

    # Fetch GOLD_PRICE from Yahoo Finance (GLD), monthly mean close.
    yahoo_gold = fetch_yahoo_gold_data(
        ticker=SERIES_CONFIG['GOLD_PRICE']['id'],
        start_date='2010-01-01'
    )
    if not yahoo_gold.empty:
        raw_df['GOLD_PRICE'] = yahoo_gold
    else:
        logger.warning("GOLD_PRICE could not be loaded from Yahoo Finance.")
    
    if not econ_business_cycles.empty:
        raw_df['BUSINESS_CYCLES'] = econ_business_cycles
    
    if raw_df.empty:
        logger.error("Failed to fetch any data from FRED.")
        return
    
    logger.info("Processing data.")
    processed_df = process_data(raw_df)
    
    logger.info(f"Processed data with {len(processed_df.columns)} factors.")
    logger.info(f"Columns included: {processed_df.columns.tolist()}")
    
    logger.info("Saving to Supabase.")
    return save_to_supabase(processed_df)

if __name__ == "__main__":
    fetch_and_save_data()
