import zmq
import json
import time
from collections import deque
from threading import Thread, Lock
from queue import Queue, Empty
import heapq # The library that implements the Min-Heap algorithm
from datetime import datetime

# --- CONFIGURATION ---
RELAY_IP = '127.0.0.1'
RELAY_PORT = '5556'
# We will focus on one high-volume symbol to demonstrate the concept
SYMBOLS = ["BTCUSDT", "ETHUSDT"] 
# How many events to look back for the "slow" price
SYNTHETIC_LAG = 5 
# How much the price must differ to trigger a signal
PROFIT_THRESHOLD_BPS = 2 # 2 Basis Points = 0.02%

class EventProcessor:
    """
    This class is the core of the new architecture. It uses a Min-Heap
    to ensure events are processed in perfect chronological order.
    """
    def __init__(self, app_instance):
        # --- DATA STRUCTURE: The Min-Heap ---
        # Stores tuples of (timestamp, event_payload). The heap automatically
        # sorts by the first item in the tuple (the timestamp).
        self.event_heap = []
        self.lock = Lock()
        self.app_instance = app_instance
        self.is_running = True

    def add_event(self, event):
        """Adds a new event to the heap. O(log n) complexity."""
        with self.lock:
            # heapq implements a Min-Heap.
            heapq.heappush(self.event_heap, (event['timestamp'], event))

    def run(self):
        """The main loop of the engine thread."""
        print("Event Processor thread started...")
        while self.is_running:
            event = None
            with self.lock:
                if self.event_heap:
                    # Get the next event in chronological order. O(1) to peek, O(log n) to pop.
                    event = heapq.heappop(self.event_heap)[1]
            
            if event:
                self.app_instance.process_event(event)
            else:
                # Sleep briefly if the heap is empty to prevent busy-waiting
                time.sleep(0.001)
        print("Event Processor thread has shut down.")

# --- ZMQ THREAD (Now much simpler) ---
def zmq_thread_worker(event_processor):
    """This thread's ONLY job is to get data and push it into the heap."""
    context = zmq.Context()
    socket = context.socket(zmq.SUB)
    socket.connect(f"tcp://{RELAY_IP}:{RELAY_PORT}")
    for symbol in SYMBOLS:
        socket.setsockopt_string(zmq.SUBSCRIBE, f"TRADE_{symbol}")

    print("ZMQ thread connected...")
    while event_processor.is_running:
        try:
            if socket.poll(timeout=100):
                _, payload_bytes = socket.recv_multipart(flags=zmq.NOBLOCK)
                event_processor.add_event(json.loads(payload_bytes))
        except zmq.Again: continue
        except Exception as e:
            if event_processor.is_running: print(f"ZMQ thread error: {e}")
            break
    print("ZMQ thread has shut down.")

class ArbitrageApp:
    def __init__(self):
        self.is_running = True
        self.processor = EventProcessor(self)
        
        # --- DATA STRUCTURE: Deque for efficient history tracking ---
        self.price_history = deque(maxlen=SYNTHETIC_LAG + 1)
        
        self.zmq_thread = Thread(target=zmq_thread_worker, args=(self.processor,), daemon=True)
        self.engine_thread = Thread(target=self.processor.run, daemon=True)

    def start(self):
        self.zmq_thread.start()
        self.engine_thread.start()
        print("--- High-Performance Event Arbitrage Bot ---")
        print(f"Tracking: {', '.join(SYMBOLS)}")
        print("Press Ctrl+C to stop.")
        try:
            while self.is_running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        print("\nShutdown signal received...")
        self.is_running = False
        self.processor.is_running = False
        # Wait for threads to finish cleanly
        self.zmq_thread.join()
        self.engine_thread.join()
        print("Application shut down gracefully.")

    def process_event(self, event):
        """This is where the strategy logic runs on the perfectly ordered stream."""
        self.price_history.append(event['price'])
        
        if len(self.price_history) < SYNTHETIC_LAG + 1:
            return # Wait for enough history

        # --- ALGORITHM: Synthetic Latency Arbitrage ---
        fast_price = self.price_history[-1]
        slow_price = self.price_history[0] # The oldest price in our deque
        
        price_diff = (fast_price - slow_price) / slow_price * 10000 # Difference in basis points

        if price_diff > PROFIT_THRESHOLD_BPS:
            print(f"[{datetime.fromtimestamp(event['timestamp']).strftime('%H:%M:%S.%f')[:-3]}] "
                  f"BUY ARB on {event['symbol']}: Fast Px: {fast_price:.2f}, Slow Px: {slow_price:.2f} "
                  f"(Diff: {price_diff:.2f} bps)")
        elif price_diff < -PROFIT_THRESHOLD_BPS:
            print(f"[{datetime.fromtimestamp(event['timestamp']).strftime('%H:%M:%S.%f')[:-3]}] "
                  f"SELL ARB on {event['symbol']}: Fast Px: {fast_price:.2f}, Slow Px: {slow_price:.2f} "
                  f"(Diff: {price_diff:.2f} bps)")

if __name__ == "__main__":
    app = ArbitrageApp()
    app.start()
