import tkinter as tk
from tkinter import ttk, scrolledtext
import zmq
import json
import time
from collections import deque, defaultdict
from threading import Thread, Lock
from queue import Queue, Empty
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from datetime import datetime
import pandas as pd
import numpy as np

# --- CONFIGURATION ---
RELAY_IP = '127.0.0.1'
RELAY_PORT = '5556'
INITIAL_CASH = 1000000000.0
# --- PAIRS TRADING CONFIG ---
# Ensure your data files contain these two symbols
PAIRS_TRADING_SYMBOLS = ["BTCUSDT", "ETHUSDT"]
# --- LATENCY ARBITRAGE CONFIG ---
LATENCY_ARB_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT"]
ALL_SYMBOLS = list(set(PAIRS_TRADING_SYMBOLS + LATENCY_ARB_SYMBOLS))
DATA_HISTORY_LEN = 500 # Data points to keep for calculations

# --- ZMQ DATA INGESTION THREAD ---
def zmq_thread_worker(app_instance):
    """This thread's ONLY job is to get data from the network and put it in a queue. It is built for speed."""
    context = zmq.Context()
    socket = context.socket(zmq.SUB)
    socket.connect(f"tcp://{RELAY_IP}:{RELAY_PORT}")
    for symbol in ALL_SYMBOLS:
        socket.setsockopt_string(zmq.SUBSCRIBE, f"TRADE_{symbol}")
        socket.setsockopt_string(zmq.SUBSCRIBE, f"QUOTE_{symbol}")
    
    print("ZMQ thread connected and listening...")
    while app_instance.is_running:
        try:
            if socket.poll(timeout=100):
                topic_bytes, payload_bytes = socket.recv_multipart(flags=zmq.NOBLOCK)
                payload = json.loads(payload_bytes)
                app_instance.data_queue.put(payload)
        except zmq.Again: continue
        except Exception as e:
            if app_instance.is_running: print(f"ZMQ thread error: {e}")
            break
    print("ZMQ thread has shut down.")

# --- TRADING ENGINE THREAD ---
def trading_engine_worker(app_instance):
    """This thread's ONLY job is to run the trading logic. This is the core 'brain' of the bot."""
    print("Trading Engine thread started.")
    
    # --- DATA STRUCTURES ---
    # Latency Arbitrage State: defaultdict is a high-performance dictionary
    best_bid, best_ask, last_trade_price = defaultdict(float), defaultdict(float), defaultdict(float)
    # Pairs Trading State: A pandas DataFrame is perfect for time-series calculations
    pair_hist = pd.DataFrame()

    while app_instance.is_running:
        try:
            payload = app_instance.data_queue.get(timeout=0.1)
            symbol = payload['symbol']
            price = payload.get('price') or (payload.get('bid_price', 0) + payload.get('ask_price', 0)) / 2.0
            if price == 0: continue
            
            app_instance.latest_prices[symbol] = price
            params = app_instance.get_params()
            votes = 0
            
            # --- ALGORITHM 1: LATENCY ARBITRAGE ---
            if params['latency_enabled'] and symbol in LATENCY_ARB_SYMBOLS:
                if payload['type'] == 'TRADE': last_trade_price[symbol] = price
                elif payload['type'] == 'QUOTE':
                    best_bid[symbol], best_ask[symbol] = payload['bid_price'], payload['ask_price']
                
                if last_trade_price[symbol] > 0 and best_bid[symbol] > 0:
                    if last_trade_price[symbol] > best_ask[symbol] + params['min_profit_usd']: votes += 1
                    if last_trade_price[symbol] < best_bid[symbol] - params['min_profit_usd']: votes -= 1
            
            # --- ALGORITHM 2: STATISTICAL ARBITRAGE (PAIRS TRADING) ---
            if params['pairs_enabled'] and symbol in PAIRS_TRADING_SYMBOLS:
                new_row = pd.DataFrame({symbol: [price]}, index=[datetime.fromtimestamp(payload['timestamp'])])
                # --- FIX: Robust DataFrame concatenation ---
                if pair_hist.empty: pair_hist = new_row
                else: pair_hist = pd.concat([pair_hist, new_row]).sort_index()
                pair_hist = pair_hist.ffill().iloc[-DATA_HISTORY_LEN:]
                
                s1, s2 = PAIRS_TRADING_SYMBOLS
                if s1 in pair_hist.columns and s2 in pair_hist.columns and len(pair_hist) > params['pairs_window']:
                    ratio = pair_hist[s1] / pair_hist[s2]
                    z_score = (ratio.iloc[-1] - ratio.mean()) / ratio.std()
                    app_instance.pairs_z_score = z_score
                    if z_score > params['pairs_threshold']: votes -= 1 # Sell the spread (short s1, long s2)
                    if z_score < -params['pairs_threshold']: votes += 1 # Buy the spread (long s1, short s2)

            # --- VOTE & EXECUTE ---
            if abs(votes) >= params['vote_threshold']:
                signal_type = "BUY" if votes > 0 else "SELL"
                app_instance.signal_queue.put({"type": signal_type, "price": price, "symbol": symbol, "reason": f"Vote: {votes}"})
        
        except Empty: continue
        except Exception as e:
            if app_instance.is_running: print(f"Trading Engine error: {e}")
    print("Trading Engine thread has shut down.")

# --- TKINTER GUI APPLICATION ---
class QuantTerminal:
    def __init__(self, root):
        self.root = root; self.root.title("Quantitative Trading Terminal"); self.root.geometry("1600x900")
        self.is_running = True
        self.data_queue, self.signal_queue = Queue(maxsize=1000), Queue()
        self.cash, self.inventory = INITIAL_CASH, {s: 0.0 for s in ALL_SYMBOLS}
        self.latest_prices, self.pnl_history = {s: 0.0 for s in ALL_SYMBOLS}, deque(maxlen=DATA_HISTORY_LEN * 2)
        self.pairs_z_score = 0.0
        self.param_lock = Lock()
        self.params = {} # The engine's private copy of parameters

        self._build_ui()
        self.apply_params() # Apply initial GUI params to the engine
        
        self.zmq_thread = Thread(target=zmq_thread_worker, args=(self,), daemon=True); self.zmq_thread.start()
        self.engine_thread = Thread(target=trading_engine_worker, args=(self,), daemon=True); self.engine_thread.start()
        
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.after(200, self._update_gui)

    def on_closing(self):
        print("Shutdown signal received..."); self.is_running = False
        self.root.after(500, self.root.destroy)

    def get_params(self):
        with self.param_lock: return self.params.copy()

    def apply_params(self):
        with self.param_lock:
            self.params = {p: v.get() for p, v in self.param_vars.items()}
        self.log_message("SYSTEM: Parameters applied to the trading engine.", "system")

    def _build_ui(self):
        style = ttk.Style(); style.theme_use('clam'); style.configure("Treeview.Heading", font=("Consolas", 10, "bold")); style.configure("Treeview", rowheight=25, font=("Consolas", 10))
        header_frame = tk.Frame(self.root, padx=10, pady=5); header_frame.pack(fill=tk.X)
        self.lbl_pnl = tk.Label(header_frame, text="PnL (MtM): $0.00", font=("Consolas", 14, "bold")); self.lbl_pnl.pack(side=tk.LEFT, padx=20)
        self.lbl_cash = tk.Label(header_frame, text=f"Cash: ${self.cash:,.2f}", font=("Consolas", 12)); self.lbl_cash.pack(side=tk.LEFT, padx=20)
        
        main_frame = tk.Frame(self.root, padx=10, pady=10); main_frame.pack(fill=tk.BOTH, expand=True)
        paned_window = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL); paned_window.pack(fill=tk.BOTH, expand=True)
        grid_frame, right_panel = tk.Frame(paned_window), tk.Frame(paned_window)
        paned_window.add(grid_frame, weight=3); paned_window.add(right_panel, weight=2)

        self.grid_cols = ["Symbol", "Price", "Inventory (Units)"]
        self.tree = ttk.Treeview(grid_frame, columns=self.grid_cols, show="headings")
        for col in self.grid_cols: self.tree.heading(col, text=col); self.tree.column(col, width=150, anchor='w')
        for symbol in ALL_SYMBOLS: self.tree.insert("", "end", iid=symbol, values=[symbol, "-", "0.00"])
        self.tree.pack(fill=tk.BOTH, expand=True)

        log_label = tk.Label(grid_frame, text="Execution Log", font=("Arial", 12, "bold")); log_label.pack(fill=tk.X)
        self.log = scrolledtext.ScrolledText(grid_frame, height=10, font=("Consolas", 9), state='disabled'); self.log.pack(fill=tk.X, expand=False, pady=5)
        self.log.tag_config("buy", foreground="#27C281"); self.log.tag_config("sell", foreground="#FF6B6B"); self.log.tag_config("system", foreground="#4098FF")

        notebook = ttk.Notebook(right_panel); notebook.pack(fill=tk.BOTH, expand=True)
        tab_charts, tab_admin = ttk.Frame(notebook), ttk.Frame(notebook)
        notebook.add(tab_charts, text="Charts"); notebook.add(tab_admin, text="Admin Controls")
        
        self.fig_pairs, self.ax_pairs = plt.subplots(tight_layout=True); self.canvas_pairs = FigureCanvasTkAgg(self.fig_pairs, master=tab_charts); self.canvas_pairs.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.fig_pnl, self.ax_pnl = plt.subplots(tight_layout=True); self.canvas_pnl = FigureCanvasTkAgg(self.fig_pnl, master=tab_charts); self.canvas_pnl.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self.param_vars = {}
        admin_frame = ttk.Frame(tab_admin, padding="10"); admin_frame.pack(fill="both", expand=True)
        
        lf_gen = ttk.LabelFrame(admin_frame, text="General", padding="10"); lf_gen.pack(fill="x", pady=5)
        ttk.Label(lf_gen, text="Vote Threshold:").grid(row=0, column=0, sticky='w'); self.param_vars['vote_threshold'] = tk.IntVar(value=1); ttk.Entry(lf_gen, textvariable=self.param_vars['vote_threshold'], width=5).grid(row=0, column=1)
        
        lf_lat = ttk.LabelFrame(admin_frame, text="Latency Arbitrage", padding="10"); lf_lat.pack(fill="x", pady=5)
        self.param_vars['latency_enabled'] = tk.BooleanVar(value=True); ttk.Checkbutton(lf_lat, text="Enabled", variable=self.param_vars['latency_enabled']).grid(row=0, columnspan=2, sticky='w')
        ttk.Label(lf_lat, text="Min Profit ($):").grid(row=1, column=0, sticky='w'); self.param_vars['min_profit_usd'] = tk.DoubleVar(value=0.01); ttk.Entry(lf_lat, textvariable=self.param_vars['min_profit_usd'], width=7).grid(row=1, column=1)

        lf_pairs = ttk.LabelFrame(admin_frame, text="Pairs Trading", padding="10"); lf_pairs.pack(fill="x", pady=5)
        self.param_vars['pairs_enabled'] = tk.BooleanVar(value=True); ttk.Checkbutton(lf_pairs, text="Enabled", variable=self.param_vars['pairs_enabled']).grid(row=0, columnspan=2, sticky='w')
        ttk.Label(lf_pairs, text="Window:").grid(row=1, column=0, sticky='w'); self.param_vars['pairs_window'] = tk.IntVar(value=100); ttk.Entry(lf_pairs, textvariable=self.param_vars['pairs_window'], width=5).grid(row=1, column=1)
        ttk.Label(lf_pairs, text="Z-Score Threshold:").grid(row=2, column=0, sticky='w'); self.param_vars['pairs_threshold'] = tk.DoubleVar(value=2.0); ttk.Entry(lf_pairs, textvariable=self.param_vars['pairs_threshold'], width=5).grid(row=2, column=1)

        apply_btn = ttk.Button(admin_frame, text="Apply Settings to Engine", command=self.apply_params); apply_btn.pack(fill='x', pady=10)

        lf_liq = ttk.LabelFrame(admin_frame, text="Execution Controls", padding="10"); lf_liq.pack(fill="x", pady=10)
        self.liq_aggression = tk.DoubleVar(value=50); ttk.Scale(lf_liq, from_=1, to=100, variable=self.liq_aggression, orient='horizontal').pack(fill='x', pady=(0,5))
        ttk.Label(lf_liq, text="Slow (1) <--- Aggression ---> (100) Fast").pack()
        ttk.Button(lf_liq, text="LIQUIDATE ALL POSITIONS", command=self.liquidate_all).pack(fill='x', pady=5)

    def _update_gui(self):
        if not self.is_running: return
        for symbol, price in self.latest_prices.items():
            if self.tree.exists(symbol):
                self.tree.item(symbol, values=(symbol, f"{price:.4f}", f"{self.inventory[symbol]:.4f}"))
        while not self.signal_queue.empty(): self._process_signal(self.signal_queue.get_nowait())
        self._update_portfolio_display()
        self.root.after(200, self._update_gui)
    
    def _process_signal(self, signal):
        symbol, price, signal_type, reason = signal['symbol'], signal['price'], signal['type'], signal['reason']
        trade_size_usd = 500000.0 # Example large trade size
        trade_qty = trade_size_usd / price
        
        self.log_message(f"SIGNAL: {signal_type} on {symbol} ({reason})", "system")
        if signal_type == "BUY" and self.cash >= trade_size_usd:
            self.inventory[symbol] += trade_qty; self.cash -= trade_size_usd
            self.log_message(f"  -> EXECUTED BUY of {trade_qty:.4f} {symbol}", "buy")
        elif signal_type == "SELL":
            self.inventory[symbol] -= trade_qty; self.cash += trade_size_usd
            self.log_message(f"  -> EXECUTED SELL of {trade_qty:.4f} {symbol}", "sell")

    def _update_portfolio_display(self):
        inventory_value = sum(self.inventory[s] * self.latest_prices.get(s, 0) for s in ALL_SYMBOLS)
        pnl = self.cash + inventory_value - INITIAL_CASH
        self.pnl_history.append({'time': time.time(), 'pnl': pnl})
        self.lbl_pnl.config(text=f"PnL (MtM): ${pnl:,.2f}", fg="#27C281" if pnl >= 0 else "#FF6B6B")
        self.lbl_cash.config(text=f"Cash: ${self.cash:,.2f}")
        self._update_pnl_chart()
        self._update_pairs_chart()

    def _update_pnl_chart(self):
        self.ax_pnl.clear()
        history = list(self.pnl_history)
        if len(history) > 1:
            times = [datetime.fromtimestamp(p['time']) for p in history]; values = [p['pnl'] for p in history]
            self.ax_pnl.plot(times, values, color='cyan')
            self.ax_pnl.fill_between(times, values, 0, where=[v >= 0 for v in values], color='green', alpha=0.3)
            self.ax_pnl.fill_between(times, values, 0, where=[v < 0 for v in values], color='red', alpha=0.3)
        self.ax_pnl.set_title("Total P&L Over Time"); self.ax_pnl.grid(True, linestyle='--', alpha=0.6); self.fig_pnl.autofmt_xdate()
        self.canvas_pnl.draw()
        
    def _update_pairs_chart(self):
        self.ax_pairs.clear()
        params = self.get_params()
        threshold = params.get('pairs_threshold', 2.0)
        self.ax_pairs.axhline(0, color='gray', linestyle='--')
        self.ax_pairs.axhline(threshold, color='red', linestyle=':', label=f'Sell Threshold (+{threshold}σ)')
        self.ax_pairs.axhline(-threshold, color='green', linestyle=':', label=f'Buy Threshold (-{threshold}σ)')
        
        self.ax_pairs.bar(1, [self.pairs_z_score], color='skyblue')
        self.ax_pairs.set_xticks([])
        self.ax_pairs.set_ylabel('Z-Score')
        self.ax_pairs.set_title(f"Pairs Trade Spread ({'/'.join(PAIRS_TRADING_SYMBOLS)})")
        self.ax_pairs.legend()
        self.canvas_pairs.draw()
        
    def liquidate_all(self):
        aggression = self.liq_aggression.get()
        self.log_message(f"--- LIQUIDATE ALL triggered with aggression: {aggression:.0f}% ---", "sell")
        self.cash = INITIAL_CASH
        self.inventory = {s: 0.0 for s in ALL_SYMBOLS}

    def log_message(self, msg, tag=None):
        self.log.config(state='normal'); self.log.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}\n", tag); self.log.see(tk.END); self.log.config(state='disabled')

if __name__ == '__main__':
    root = tk.Tk()
    app = QuantTerminal(root)
    root.mainloop()

