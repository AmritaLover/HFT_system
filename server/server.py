import zmq
import time
import pandas as pd
from pathlib import Path

# --- CONFIGURATION ---
HOST = '127.0.0.1'
PORT = '5555'
REPLAY_SPEED_FACTOR = 1

# --- FILE PATHS ---
SCRIPT_DIR = Path(__file__).parent
TRADES_FILE = SCRIPT_DIR / '../data/trades.csv'
QUOTES_FILE = SCRIPT_DIR / '../data/quotes.csv'

def main():
    print("--- Market Data Server ---")
    
    print("Loading and preparing market data...")
    try:
        trades_df = pd.read_csv(TRADES_FILE)
        quotes_df = pd.read_csv(QUOTES_FILE)
    except FileNotFoundError as e:
        print(f"Error: Data file not found. {e}")
        return
        
    trades_df['type'] = 'TRADE'
    quotes_df['type'] = 'QUOTE'
    market_data_df = pd.concat([trades_df, quotes_df]).sort_values(by='timestamp').reset_index(drop=True)
    print(f"Loaded and sorted {len(market_data_df)} total market events.")

    context = zmq.Context()
    socket = context.socket(zmq.PUB)
    socket.bind(f"tcp://{HOST}:{PORT}")
    print(f"Server broadcasting on tcp://{HOST}:{PORT}")
    
    # Give initial subscribers time to connect
    time.sleep(2) 

    print(f"Starting replay at {REPLAY_SPEED_FACTOR}x speed...")
    last_event_timestamp = None
    sequence_number = 0

    for index, row in market_data_df.iterrows():
        current_event_timestamp = row['timestamp']

        if last_event_timestamp is not None:
            time_diff = current_event_timestamp - last_event_timestamp
            sleep_duration = time_diff / REPLAY_SPEED_FACTOR
            if sleep_duration > 0:
                time.sleep(sleep_duration)
        
        last_event_timestamp = current_event_timestamp
        sequence_number += 1

        if row['type'] == 'TRADE':
            topic = f"TRADE_{row['symbol']}"
            payload = {
                'type': row['type'], 
                'symbol': row['symbol'], 
                'price': row['price'], 
                'size': row['size'], 
                'timestamp': row['timestamp'], 
                'origin_ts': time.perf_counter(), 
                'seq_num': sequence_number
            }
        elif row['type'] == 'QUOTE':
            topic = f"QUOTE_{row['symbol']}"
            payload = {
                'type': row['type'], 
                'symbol': row['symbol'], 
                'bid_price': row['bid_price'], 
                'bid_size': row['bid_size'], 
                'ask_price': row['ask_price'], 
                'ask_size': row['ask_size'], 
                'timestamp': row['timestamp'], 
                'origin_ts': time.perf_counter(), 
                'seq_num': sequence_number
            }
        
        socket.send_string(topic, flags=zmq.SNDMORE)
        socket.send_json(payload)

    print("\n--- End of data file. Server shutting down. ---")
    socket.close()
    context.term()

if __name__ == '__main__':
    main()
