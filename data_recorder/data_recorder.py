import asyncio
import csv
import time
from pathlib import Path
from binance import AsyncClient, BinanceSocketManager


SYMBOLS = ['btcusdt', 'ethusdt', 'solusdt', 'bnbusdt', 'xrpusdt', 'adausdt','drepbusd', 'oaxusdt', 'pntusdt', 'vthousdt']
RECORD_DURATION_MINUTES = 10 
DATA_DIR = Path(__file__).parent / 'data'


async def main():
    print("--- HFT Data Recorder (Optimized) ---")
    print(f"Recording {', '.join(SYMBOLS)} for {RECORD_DURATION_MINUTES} minutes.")
    
    DATA_DIR.mkdir(exist_ok=True)
    trade_file_path = DATA_DIR / 'trades.csv'
    quote_file_path = DATA_DIR / 'quotes.csv'
    
    with open(trade_file_path, 'w', newline='') as tf, open(quote_file_path, 'w', newline='') as qf:
        trade_writer = csv.writer(tf)
        quote_writer = csv.writer(qf)
        
        trade_writer.writerow(['timestamp', 'symbol', 'price', 'size'])
        quote_writer.writerow(['timestamp', 'symbol', 'bid_price', 'bid_size', 'ask_price', 'ask_size'])
        
        client = await AsyncClient.create()
        bsm = BinanceSocketManager(client)
        
        trade_streams = [f'{s}@trade' for s in SYMBOLS]
        depth_streams = [f'{s}@depth5@100ms' for s in SYMBOLS] 
        multiplex_socket = bsm.multiplex_socket(trade_streams + depth_streams)
        

        
        start_time = time.time()
        
        async with multiplex_socket as socket:
            while time.time() - start_time < RECORD_DURATION_MINUTES * 60:
                try:
                    msg = await asyncio.wait_for(socket.recv(), timeout=5.0)
                    
                    if msg and 'stream' in msg:
                        if 'trade' in msg['stream']:
                            trade_data = msg['data']
                            ts = float(trade_data['E']) / 1000.0 
                            row = [ts, trade_data['s'], float(trade_data['p']), float(trade_data['q'])]
                            trade_writer.writerow(row)


                        elif 'depth' in msg['stream']:
                            depth_data = msg['data']
                            ts = time.time() 
                            best_bid = depth_data['bids'][0]
                            best_ask = depth_data['asks'][0]
                            symbol = msg['stream'].split('@')[0].upper()
                            row = [ts, symbol, float(best_bid[0]), float(best_bid[1]), float(best_ask[0]), float(best_ask[1])]
                            quote_writer.writerow(row)


                except asyncio.TimeoutError:
                    pass
                except Exception as e:
                    print(f"An error occurred: {e}")
                    break

        await client.close_connection()
        print(f"\n--- Recording Complete ---")
        print(f"Data for {RECORD_DURATION_MINUTES} minutes saved successfully.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nRecording stopped by user.")