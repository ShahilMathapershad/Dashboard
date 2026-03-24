import argparse
import os
import ssl
import time
import re
import urllib.request
import urllib.parse
import logging
import datetime
from logic.supabase_client import get_supabase
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
    'VIX': {'source': 'FRED', 'id': 'VIXCLS', 'label': 'CBOE Volatility Index (VIX)'},
    'GOLD_PRICE': {'source': 'WORLD_BANK', 'id': 'CMO-Historical-Data-Monthly.xlsx', 'label': 'World Bank Commodity Markets Monthly Gold Price'},
    'BRENT_OIL_PRICE': {'source': 'FRED', 'id': 'POILBREUSDM', 'label': 'Global Price of Brent Crude'},
    'US_CPI': {'source': 'FRED', 'id': 'CPIAUCSL', 'label': 'Consumer Price Index for All Urban Consumers (USA)'},
    'SA_INFLATION': {'source': 'HARDCODED', 'id': 'SA_CPI_INDEX', 'label': 'South African Headline CPI Index'},
    'ZAR_USD': {'source': 'FRED', 'id': 'DEXSFUS', 'label': 'ZAR/USD Exchange Rate'}
}

# Load environment variables explicitly for Render
from dotenv import load_dotenv
load_dotenv()

def get_api_keys():
    """Reads API keys from api_keys.txt."""
    keys = {'FRED': None}
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
# Prioritize environment variables, then fallback to api_keys.txt or hardcoded defaults
FRED_API_KEY = os.environ.get('FRED_API_KEY', os.environ.get('FRED_API', API_KEYS.get('FRED') or 'e9e60c2ca97eac250d9bdb7d22511d58'))


def _to_monthly(series):
    """Normalize any date-indexed series to month-end frequency."""
    import pandas as pd
    if series.empty:
        return series
    series = series.sort_index()
    try:
        monthly = series.resample('ME').last()
    except ValueError:
        monthly = series.resample('M').last()
    return monthly.dropna()

def fetch_fred_data(series_dict, api_key=None, start_date='2009-12-31', progress_callback=None):
    """Fetches data from FRED for each series in the dictionary."""
    import pandas as pd
    from fredapi import Fred
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
            
            logger.info(f"Fetching FRED series: {name} ({series_id}) starting from {start_date}")
            s = fred.get_series(series_id, observation_start=start_date)
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

def _get_world_bank_gold_excel_url():
    """Scrape the World Bank commodity markets page for the latest historical data workbook URL."""
    import requests
    page_url = "https://www.worldbank.org/en/research/commodity-markets"
    logger.info("Fetching World Bank commodity markets page for latest gold workbook link.")

    try:
        response = requests.get(page_url, timeout=30)
        response.raise_for_status()
        html_content = response.text
    except Exception as e:
        logger.error(f"Failed to load World Bank commodity markets page: {e}")
        return None

    match = re.search(
        r'href=["\']([^"\']*CMO-Historical-Data-Monthly\.xlsx(?:\?[^"\']*)?)["\']',
        html_content,
        flags=re.IGNORECASE
    )
    if not match:
        logger.error("Could not find the live CMO-Historical-Data-Monthly.xlsx link on World Bank page.")
        return None

    live_url = match.group(1).strip()
    if live_url.startswith("//"):
        live_url = f"https:{live_url}"
    elif not live_url.startswith("http"):
        if live_url.startswith("/"):
            live_url = f"https://thedocs.worldbank.org{live_url}"
        else:
            live_url = urllib.parse.urljoin(page_url, live_url)

    logger.info(f"Resolved World Bank workbook URL: {live_url}")
    return live_url


def fetch_world_bank_gold_data(start_date='2009-12-31', end_date=None):
    """Fetch GOLD_PRICE from World Bank monthly commodity workbook (Monthly Prices > Gold)."""
    import pandas as pd
    import requests
    if end_date is None:
        end_date = pd.Timestamp.now().strftime('%Y-%m-%d')

    live_url = _get_world_bank_gold_excel_url()
    if not live_url:
        return pd.Series(dtype='float64')

    logger.info(f"Loading World Bank monthly prices workbook from {live_url}")
    try:
        df = pd.read_excel(live_url, sheet_name="Monthly Prices", header=4)
    except Exception as e:
        logger.error(f"Failed to parse World Bank monthly workbook: {e}")
        return pd.Series(dtype='float64')

    if df is None or df.empty:
        logger.warning("World Bank workbook returned empty data.")
        return pd.Series(dtype='float64')

    df.columns = df.columns.astype(str).str.strip()
    df.rename(columns={df.columns[0]: 'Date'}, inplace=True)

    gold_col = None
    for col in df.columns:
        if str(col).strip().lower() == 'gold':
            gold_col = col
            break
    if gold_col is None:
        logger.error("Gold column not found in World Bank monthly workbook.")
        return pd.Series(dtype='float64')

    df_gold = df[['Date', gold_col]].copy()
    # Drop the first metadata/unit row and any trailing footnotes.
    df_gold = df_gold.iloc[1:]
    df_gold = df_gold.dropna(subset=[gold_col])
    df_gold['Date'] = df_gold['Date'].astype(str).str.strip().str.replace('M', '-', regex=False)
    df_gold[gold_col] = pd.to_numeric(df_gold[gold_col], errors='coerce')
    df_gold['Date'] = pd.to_datetime(df_gold['Date'], errors='coerce')
    df_gold = df_gold.dropna(subset=['Date', gold_col]).sort_values('Date')

    if df_gold.empty:
        logger.warning("World Bank gold series is empty after cleaning.")
        return pd.Series(dtype='float64')

    monthly_gold = df_gold.set_index('Date')[gold_col]
    monthly_gold = _to_monthly(monthly_gold)
    monthly_gold = monthly_gold.loc[start_date:end_date]
    monthly_gold.name = 'GOLD_PRICE'

    logger.info(f"Fetched {len(monthly_gold)} monthly GOLD_PRICE observations from World Bank.")
    return monthly_gold


def fetch_sa_inflation_hardcoded():
    """Returns the hardcoded SA_INFLATION data as a DataFrame starting from 2009-12-31."""
    import pandas as pd
    import numpy as np
    
    # Official StatsSA Headline CPI (Base: Dec 2024 = 100)
    cpi_values = [
        48.0,  # 2009 Dec
        48.1, 48.4, 48.8, 48.8, 48.9, 48.9, 49.3, 49.3, 49.4, 49.4, 49.5, 49.6,  # 2010
        49.9, 50.1, 50.7, 50.9, 51.2, 51.4, 51.9, 51.9, 52.2, 52.4, 52.5, 52.6,  # 2011
        53.0, 53.2, 53.8, 54.1, 54.1, 54.3, 54.3, 54.5, 55.0, 55.3, 55.5, 55.6,  # 2012
        55.8, 56.3, 57.0, 57.2, 57.0, 57.2, 57.8, 58.0, 58.3, 58.4, 58.5, 58.7,  # 2013
        59.0, 59.7, 60.5, 60.7, 60.8, 61.0, 61.5, 61.8, 61.8, 61.8, 61.8, 61.8,  # 2014
        61.6, 62.0, 62.9, 63.5, 63.7, 63.9, 64.6, 64.6, 64.6, 64.8, 64.8, 64.9,  # 2015
        65.5, 66.3, 66.8, 67.4, 67.5, 67.9, 68.5, 68.4, 68.5, 68.8, 69.1, 69.3,  # 2016
        69.8, 70.5, 71.0, 71.0, 71.2, 71.4, 71.6, 71.7, 72.0, 72.2, 72.3, 72.6,  # 2017
        72.8, 73.4, 73.6, 74.2, 74.3, 74.6, 75.3, 75.2, 75.5, 75.9, 76.0, 75.9,  # 2018
        75.7, 76.3, 77.0, 77.4, 77.7, 78.0, 78.2, 78.5, 78.6, 78.6, 78.7, 78.9,  # 2019
        79.2, 79.9, 80.2, 79.8, 79.2, 79.7, 80.7, 80.9, 81.0, 81.2, 81.2, 81.3,  # 2020
        81.7, 82.2, 82.8, 83.3, 83.4, 83.5, 84.5, 84.8, 85.0, 85.3, 85.6, 86.1,  # 2021
        86.3, 86.8, 87.7, 88.2, 88.8, 89.8, 91.1, 91.3, 91.4, 91.7, 92.0, 92.3,  # 2022
        92.2, 92.9, 93.9, 94.2, 94.4, 94.6, 95.4, 95.7, 96.3, 97.2, 97.1, 97.1,  # 2023
        97.2, 98.1, 98.9, 99.1, 99.3, 99.4, 99.8, 99.9, 100.0, 99.9, 99.9, 100.0  # 2024
    ]
    
    # Generate monthly end-of-month dates from Dec 2009 to Dec 2024
    try:
        dates = pd.date_range(start="2009-12-31", end="2024-12-31", freq="ME")
    except ValueError:
        dates = pd.date_range(start="2009-12-31", end="2024-12-31", freq="M")
    
    # Create the DataFrame with only SA_INFLATION (CPI index)
    df_cpi = pd.DataFrame({'SA_INFLATION': cpi_values}, index=dates)
    df_cpi.index.name = 'Date'
    
    return df_cpi


def process_data(final_df, start_date='2009-12-31', end_date=None):
    """Processes the raw data (sorting, resampling, filling, etc.)."""
    import pandas as pd
    # If end_date is not provided, use the end of the previous month
    if end_date is None:
        now = pd.Timestamp.now()
        # End of previous month: first day of current month minus one day
        end_of_prev_month = (now.replace(day=1) - pd.Timedelta(days=1))
        end_date = end_of_prev_month.strftime('%Y-%m-%d')
    
    # LIMIT DATA RANGE: To save memory on Render (512MB), we only need 
    # enough data for engineering features (rolling windows, lags).
    # 15 years is more than enough.
    limit_date = (pd.to_datetime(end_date) - pd.DateOffset(years=15)).strftime('%Y-%m-%d')
    if start_date < limit_date:
        start_date = limit_date
        logger.info(f"Limiting start_date to {start_date} for memory efficiency.")

    # Sort index
    final_df = final_df.sort_index()
    final_df = final_df.loc[start_date:]
    
    # Resample to monthly (End of Month) and take the last value
    # Older pandas used 'M', newer use 'ME'
    try:
        final_df_monthly = final_df.resample('ME').last()
    except ValueError:
        final_df_monthly = final_df.resample('M').last()
    
    # Forward fill missing values
    final_df_monthly = final_df_monthly.ffill()
    
    # Backfill any remaining NaN values in the first few rows with the first non-NaN value
    # Use a more robust approach to handle columns that start with NaN
    for column in final_df_monthly.columns:
        # Find the first non-NaN value in the column
        first_valid_idx = final_df_monthly[column].first_valid_index()
        if first_valid_idx is not None:
            first_valid_value = final_df_monthly[column].loc[first_valid_idx]
            # Fill all NaN values before the first valid value with that value
            final_df_monthly.loc[:first_valid_idx, column] = first_valid_value
    
    # Filter by date range if provided
    final_df_monthly = final_df_monthly.loc[start_date:end_date]
    
    # Build explicit inflation columns:
    # US_CPI is already in final_df from FRED
    
    # Keep only requested columns in the specified order
    columns_to_keep = [
        'EPU(USA)', 
        'WUIZAF(SA)', 
        '10_YEAR_BOND_RATES(USA)', 
        '10_YEAR_BOND_RATES(SA)', 
        'VIX', 
        'GOLD_PRICE', 
        'BRENT_OIL_PRICE', 
        'US_CPI',
        'SA_INFLATION',
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
    import pandas as pd
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
        if 'usa_inflation' in record:
            record['US_CPI'] = record.pop('usa_inflation')
    
    logger.info(f"Saving {len(records)} records to Supabase 'data' table...")
    
    supabase = get_supabase()
    if not supabase:
        logger.error("Supabase client not initialized.")
        return None
        
    try:
        valid_columns = {
            'Date', 'EPU(USA)', 'WUIZAF(SA)', '10_YEAR_BOND_RATES(USA)', 
            '10_YEAR_BOND_RATES(SA)', 'VIX', 
            'GOLD_PRICE', 'BRENT_OIL_PRICE', 'US_CPI', 'SA_INFLATION', 'ZAR_USD'
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


def replace_gold_price_column_in_supabase(gold_series):
    """Upsert only Date + GOLD_PRICE into Supabase, replacing GOLD_PRICE for existing dates."""
    import pandas as pd
    if gold_series is None or gold_series.empty:
        logger.warning("No GOLD_PRICE series provided for Supabase replacement.")
        return None

    supabase = get_supabase()
    if not supabase:
        logger.error("Supabase client not initialized.")
        return None

    gold_df = gold_series.dropna().to_frame(name='GOLD_PRICE').reset_index()
    gold_df.rename(columns={gold_df.columns[0]: 'Date'}, inplace=True)
    gold_df['Date'] = pd.to_datetime(gold_df['Date'], errors='coerce')
    gold_df['DateKey'] = gold_df['Date'].dt.strftime('%Y-%m-%d')
    gold_df['Date'] = gold_df['Date'].dt.strftime('%Y-%m-%dT00:00:00+00:00')
    gold_df['GOLD_PRICE'] = pd.to_numeric(gold_df['GOLD_PRICE'], errors='coerce')
    gold_df = gold_df.dropna(subset=['Date', 'DateKey', 'GOLD_PRICE'])

    records = gold_df.to_dict('records')
    if not records:
        logger.warning("No valid GOLD_PRICE records to upsert.")
        return None

    # Keep updates scoped to rows that already exist in the data table.
    try:
        existing_resp = supabase.table('data').select('Date').gte('Date', '1900-01-01').execute()
        existing_rows = existing_resp.data or []
        existing_dates = {
            str(row.get('Date'))[:10]
            for row in existing_rows
            if row.get('Date')
        }
        if existing_dates:
            records = [row for row in records if row['DateKey'] in existing_dates]
    except Exception as e:
        logger.warning(f"Could not prefetch existing dates for GOLD_PRICE replacement: {e}")

    if not records:
        logger.warning("No matching Supabase dates found for GOLD_PRICE replacement.")
        return None

    for row in records:
        row.pop('DateKey', None)

    logger.info(f"Replacing GOLD_PRICE in Supabase for {len(records)} dates.")
    try:
        chunk_size = 500
        for i in range(0, len(records), chunk_size):
            chunk = records[i:i + chunk_size]
            supabase.table('data').upsert(chunk).execute()
        logger.info("Successfully replaced GOLD_PRICE column in Supabase.")
        return {"updated_rows": len(records)}
    except Exception as e:
        logger.error(f"Error replacing GOLD_PRICE in Supabase: {e}")
        return None

def fetch_and_save_data():
    """Main function to run the fetch, process, and save workflow."""
    import pandas as pd
    logger.info("Starting main data fetch and save workflow.")
    
    # Prepare FRED series dictionary
    fred_series = {name: cfg['id'] for name, cfg in SERIES_CONFIG.items() if cfg['source'] == 'FRED'}
    
    logger.info(f"Fetching {len(fred_series)} series from FRED.")
    raw_df = fetch_fred_data(fred_series)

    # Fetch GOLD_PRICE from World Bank monthly commodity data.
    wb_gold = fetch_world_bank_gold_data(start_date='2009-12-31')
    if not wb_gold.empty:
        # Use concat instead of assignment to allow the index to expand to the latest available data.
        raw_df = pd.concat([raw_df, wb_gold.to_frame(name='GOLD_PRICE')], axis=1)
    else:
        logger.warning("GOLD_PRICE could not be loaded from World Bank.")

    # Fetch SA_INFLATION (Hardcoded)
    sa_inflation = fetch_sa_inflation_hardcoded()
    raw_df = pd.concat([raw_df, sa_inflation], axis=1)
    
    if raw_df.empty:
        logger.error("Failed to fetch any data from FRED.")
        return
    
    logger.info("Processing data.")
    processed_df = process_data(raw_df)
    
    logger.info(f"Processed data with {len(processed_df.columns)} factors.")
    logger.info(f"Columns included: {processed_df.columns.tolist()}")
    
    logger.info("Saving to Supabase.")
    save_resp = save_to_supabase(processed_df)

    # Explicitly replace only GOLD_PRICE in Supabase with the latest World Bank series.
    replace_gold_price_column_in_supabase(wb_gold)
    return save_resp

def is_last_day_of_month():
    """Check if today is the last day of the month."""
    today = datetime.date.today()
    next_day = today + datetime.timedelta(days=1)
    return next_day.month != today.month

def should_update_from_api():
    """
    Decide whether to fetch from APIs or pull from Supabase.
    Returns True if today is the last day of the month AND Supabase doesn't have today's month data yet.
    """
    import pandas as pd
    if not is_last_day_of_month():
        logger.info("should_update_from_api: False (not last day of month)")
        return False
    
    supabase = get_supabase()
    if not supabase:
        logger.warning("should_update_from_api: True (no Supabase client)")
        return True
    
    try:
        # Check the latest date in Supabase
        # We only need the Date, and we can limit to 1
        resp = supabase.table('data').select('Date').order('Date', desc=True).limit(1).execute()
        if not resp.data:
            logger.info("should_update_from_api: True (Supabase empty)")
            return True
        
        latest_date_str = resp.data[0]['Date']
        latest_date = pd.to_datetime(latest_date_str)
        
        today = pd.Timestamp.now()
        # If the latest date in Supabase is already from this month or later, don't re-fetch
        if latest_date.year == today.year and latest_date.month == today.month:
            logger.info(f"should_update_from_api: False (Latest date {latest_date.date()} is already from this month)")
            return False
            
        logger.info(f"should_update_from_api: True (Latest date {latest_date.date()} is old)")
        return True
    except Exception as e:
        logger.error(f"Error checking Supabase for latest date: {e}")
        return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Data fetch and Supabase sync")
    parser.add_argument(
        "--replace-gold-only",
        action="store_true",
        help="Fetch latest World Bank gold series and replace only GOLD_PRICE in Supabase."
    )
    parser.add_argument(
        "--start-date",
        default="2009-12-31",
        help="Start date for gold replacement mode (YYYY-MM-DD)."
    )
    args = parser.parse_args()

    if args.replace_gold_only:
        gold_series = fetch_world_bank_gold_data(start_date=args.start_date)
        replace_gold_price_column_in_supabase(gold_series)
    else:
        fetch_and_save_data()
