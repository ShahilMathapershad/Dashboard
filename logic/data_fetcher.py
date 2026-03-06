import pandas as pd
import numpy as np
from fredapi import Fred
import argparse
import os
import ssl
import time
import json
import re
import urllib.request
import urllib.parse
import logging
import requests
from dotenv import load_dotenv
from logic.supabase_client import supabase
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
    'ZAR_USD': {'source': 'FRED', 'id': 'DEXSFUS', 'label': 'South African Rand to U.S. Dollar Exchange Rate'}
}

# Load environment variables explicitly for Render
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
    if series.empty:
        return series
    series = series.sort_index()
    try:
        monthly = series.resample('ME').last()
    except ValueError:
        monthly = series.resample('M').last()
    return monthly.dropna()

def fetch_fred_data(series_dict, api_key=None, start_date='2018-01-31', progress_callback=None):
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


def fetch_world_bank_gold_data(start_date='2018-01-31', end_date=None):
    """Fetch GOLD_PRICE from World Bank monthly commodity workbook (Monthly Prices > Gold)."""
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
    """Returns the hardcoded SA_INFLATION data as a DataFrame starting from 2018-01-31."""
    # Monthly date range from January 2018 to February 2026
    # freq='ME' or 'M' gives month ends.
    try:
        dates = pd.date_range(start="2018-01-31", end="2026-02-28", freq="ME")
    except ValueError:
        dates = pd.date_range(start="2018-01-31", end="2026-02-28", freq="M")
    
    # Continuous South African Headline CPI Index (Base: December 2021 = 100)
    # Statistically spliced to remove base-year breaks.
    cpi_index_points = [
        # 2018
        84.5, 85.2, 85.5, 86.2, 86.3, 86.6, 87.4, 87.3, 87.7, 88.1, 88.2, 88.1,
        # 2019
        87.9, 88.6, 89.4, 89.9, 90.2, 90.5, 90.8, 91.1, 91.3, 91.3, 91.4, 91.6,
        # 2020
        91.9, 92.8, 93.1, 92.6, 92.0, 92.5, 93.7, 93.9, 94.0, 94.3, 94.3, 94.4,
        # 2021
        94.7, 95.3, 96.0, 96.5, 96.5, 96.7, 97.7, 98.1, 98.4, 98.6, 99.4, 100.0,
        # 2022
        100.1, 100.8, 101.6, 102.2, 102.8, 103.9, 105.4, 105.6, 105.8, 106.1, 106.8, 107.2,
        # 2023
        107.0, 107.9, 108.8, 109.1, 109.3, 109.5, 110.4, 110.7, 111.5, 112.4, 112.7, 112.7,
        # 2024
        112.7, 113.9, 114.6, 114.8, 115.0, 115.1, 115.5, 115.6, 115.7, 115.5, 116.0, 116.1,
        # 2025
        116.3, 117.5, 117.7, 118.0, 118.2, 118.6, 119.5, 119.4, 119.6, 119.7, 120.1, 120.3,
        # 2026
        120.4, np.nan # Feb 2026 pending mid-March Stats SA release
    ]
    df_cpi = pd.DataFrame({
        'Date': dates,
        'SA_INFLATION': cpi_index_points
    })
    df_cpi.set_index('Date', inplace=True)
    return df_cpi


def fetch_yahoo_gold_data(ticker='GLD', start_date='2018-01-31', end_date=None):
    """Backward-compatible alias: GOLD_PRICE now comes from World Bank monthly data."""
    logger.warning("fetch_yahoo_gold_data is deprecated; using World Bank monthly gold data instead.")
    return fetch_world_bank_gold_data(start_date=start_date, end_date=end_date)

def process_data(final_df, start_date='2018-01-31', end_date=None):
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
    if gold_series is None or gold_series.empty:
        logger.warning("No GOLD_PRICE series provided for Supabase replacement.")
        return None

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
    logger.info("Starting main data fetch and save workflow.")
    
    # Prepare FRED series dictionary
    fred_series = {name: cfg['id'] for name, cfg in SERIES_CONFIG.items() if cfg['source'] == 'FRED'}
    
    logger.info(f"Fetching {len(fred_series)} series from FRED.")
    raw_df = fetch_fred_data(fred_series)

    # Fetch GOLD_PRICE from World Bank monthly commodity data.
    wb_gold = fetch_world_bank_gold_data(start_date='2018-01-31')
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

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Data fetch and Supabase sync")
    parser.add_argument(
        "--replace-gold-only",
        action="store_true",
        help="Fetch latest World Bank gold series and replace only GOLD_PRICE in Supabase."
    )
    parser.add_argument(
        "--start-date",
        default="2018-01-31",
        help="Start date for gold replacement mode (YYYY-MM-DD)."
    )
    args = parser.parse_args()

    if args.replace_gold_only:
        gold_series = fetch_world_bank_gold_data(start_date=args.start_date)
        replace_gold_price_column_in_supabase(gold_series)
    else:
        fetch_and_save_data()
