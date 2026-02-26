import pandas as pd
from fredapi import Fred
import os
import ssl
import time
from logic.supabase_client import supabase

# Bypass SSL verification for FRED API calls if needed
ssl._create_default_https_context = ssl._create_unverified_context

FRED_API_KEY = os.environ.get('FRED_API_KEY', 'e9e60c2ca97eac250d9bdb7d22511d58')

def fetch_fred_data(series_dict, api_key=None, progress_callback=None):
    """Fetches data from FRED for each series in the dictionary."""
    if not api_key:
        api_key = FRED_API_KEY
    
    try:
        print(f"DEBUG: Initializing Fred with API key (length: {len(api_key) if api_key else 0})...")
        fred = Fred(api_key=api_key)
        print("DEBUG: Fred initialized successfully.")
    except Exception as e:
        print(f"DEBUG Error initializing FRED with provided key: {e}")
        return pd.DataFrame()

    df_list = []
    total = len(series_dict)
    for i, (name, series_id) in enumerate(series_dict.items()):
        # Calculate percentage: i is current index, (i/total)*100 is starting, ((i+1)/total)*100 is finished
        percent_start = int((i / total) * 100)
        try:
            if progress_callback:
                progress_callback(percent_start, f"Fetching {name}...")
            
            print(f"Fetching FRED series: {name} ({series_id})")
            s = fred.get_series(series_id)
            df = s.to_frame(name=name)
            df_list.append(df)
            
            # Successfully fetched, report updated percentage
            percent_done = int(((i + 1) / total) * 100)
            if progress_callback:
                progress_callback(percent_done, f"Fetched {name}")
                
            time.sleep(0.5) # Avoid rate limiting
        except Exception as e:
            print(f"Error fetching {series_id} from FRED: {e}")
            percent_err = int(((i + 1) / total) * 100)
            if progress_callback:
                progress_callback(percent_err, f"Error: {name}")
    
    if progress_callback:
        progress_callback(100, "Processing data...")
    
    if not df_list:
        return pd.DataFrame()
    
    combined_df = pd.concat(df_list, axis=1, sort=True)
    return combined_df

def process_data(final_df, start_date='2000-01-01', end_date='2026-12-31'):
    """Processes the raw FRED data (sorting, resampling, filling, etc.)."""
    # Sort index
    final_df = final_df.sort_index()
    
    # Filter by date range if provided
    final_df = final_df.loc[start_date:end_date]
    
    # Resample to monthly (End of Month) and take the last value
    # 'ME' is for Month End in newer pandas, older used 'M'
    try:
        final_df_monthly = final_df.resample('ME').last()
    except ValueError:
        final_df_monthly = final_df.resample('M').last()
    
    # Forward fill missing values
    final_df_monthly = final_df_monthly.ffill()
    
    # Calculate Inflation Difference
    if 'SA_INFLATION' in final_df_monthly.columns and 'USA_INFLATION' in final_df_monthly.columns:
        final_df_monthly['INFLATION_DIFFERENCES'] = final_df_monthly['SA_INFLATION'] - final_df_monthly['USA_INFLATION']
    
    # Keep only requested columns in the specified order
    columns_to_keep = [
        'EPU(USA)', 
        'WUIZAF(SA)', 
        '10_YEAR_BOND_RATES(USA)', 
        '10_YEAR_BOND_RATES(SA)', 
        'INFLATION_DIFFERENCES', 
        'VIX', 
        'GOLD_PRICE', 
        'BRENT_OIL_PRICE', 
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
        print("No data to save.")
        return
    
    # Reset index to make Date a column
    df_to_save = df.reset_index()
    
    # Convert Date to string (ISO format) for JSON serialization
    df_to_save['Date'] = df_to_save['Date'].dt.strftime('%Y-%m-%d')
    
    # Replace NaN with None for JSON/Supabase
    # Using a more robust method to replace NaNs
    df_to_save = df_to_save.where(pd.notnull(df_to_save), None)
    records = df_to_save.to_dict('records')
    
    # Ensure all NaNs are None (sometimes replace doesn't catch everything depending on dtype)
    for record in records:
        for key, value in record.items():
            if pd.isna(value):
                record[key] = None
    
    print(f"Saving {len(records)} records to Supabase 'data' table...")
    
    if not supabase:
        print("Error: Supabase client not initialized.")
        return None
        
    try:
        # Clear the 'data' table before adding new data
        print("Clearing the 'data' table in Supabase...")
        # Using a filter that matches all rows (all dates are >= 1900-01-01)
        supabase.table('data').delete().gte('Date', '1900-01-01').execute()
        print("Successfully cleared the table.")

        # Using upsert requires a unique constraint on 'Date' in the 'data' table
        response = supabase.table('data').upsert(records).execute()
        print("Successfully saved data to Supabase.")
        return response
    except Exception as e:
        print(f"Error saving to Supabase: {e}")
        return None

def fetch_and_save_data():
    """Main function to run the fetch, process, and save workflow."""
    fred_series = {
        'EPU(USA)': 'USEPUINDXM',
        'WUIZAF(SA)': 'WUIZAF',
        '10_YEAR_BOND_RATES(USA)': 'GS10',
        '10_YEAR_BOND_RATES(SA)': 'IRLTLT01ZAM156N',
        'SA_INFLATION': 'CPALTT01ZAM659N',
        'USA_INFLATION': 'CPALTT01USM659N',
        'VIX': 'VIXCLS',
        'GOLD_PRICE': 'PCU2122212122210',
        'BRENT_OIL_PRICE': 'POILBREUSDM',
        'ZAR_USD': 'DEXSFUS'
    }
    
    print("Fetching data from FRED...")
    raw_df = fetch_fred_data(fred_series)
    
    if raw_df.empty:
        print("Failed to fetch any data.")
        return
    
    print("Processing data...")
    processed_df = process_data(raw_df)
    
    print(f"\nSuccessfully processed data with {len(processed_df.columns)} factors.")
    print(f"Columns included: {processed_df.columns.tolist()}")
    print(f"Date range: {processed_df.index.min()} to {processed_df.index.max()}")
    
    print("Saving to Supabase...")
    return save_to_supabase(processed_df)

if __name__ == "__main__":
    fetch_and_save_data()
