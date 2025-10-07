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
import sys
import math
import itertools

# --- CONFIGURATION ---
RELAY_IP = '127.0.0.1'
RELAY_PORT = '5556'
INITIAL_CASH = 1000000000.0

# --- STRATEGY CONFIG ---
TRI_ARB_CURRENCIES = ["USDT", "BTC", "ETH", "BNB"]
PAIRS_TRADING_SYMBOLS = ["BTCUSDT", "ETHUSDT"]
LATENCY_ARB_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
ALL_SYMBOLS = list(set(PAIRS_TRADING_SYMBOLS + LATENCY_ARB_SYMBOLS + [f"{c1}{c2}" for c1, c2 in itertools.permutations(TRI_ARB_CURRENCIES, 2)]))
DATA_HISTORY_LEN = 500

# --- ZMQ DATA INGESTION THREAD ---
def zmq_thread_worker(app_instance):
    """Gets data from the network and puts it in a queue for the engine."""
    context = zmq.Context(); socket = context.socket(zmq.SUB)
    socket.connect(f"tcp://{RELAY_IP}:{RELAY_PORT}")
    for symbol in ALL_SYMBOLS:
        socket.setsockopt_string(zmq.SUBSCRIBE, f"TRADE_{symbol}")
        socket.setsockopt_string(zmq.SUBSCRIBE, f"QUOTE_{symbol}")
    print("ZMQ thread connected...")
    while app_instance.is_running:
        try:
            if socket.poll(timeout=100):
                _, payload_bytes = socket.recv_multipart(flags=zmq.NOBLOCK)
                app_instance.data_queue.put(json.loads(payload_bytes))
        except zmq.Again: continue
        except Exception as e:
            if app_instance.is_running: print(f"ZMQ thread error: {e}")
            break
    print("ZMQ thread shut down.")

# --- TRIANGULAR ARBITRAGE ENGINE CLASS ---
class TriangularArbitrageEngine:
    """Encapsulates the graph and Bellman-Ford algorithm for detecting triangular arbitrage."""
    def __init__(self, currencies):
        self.currencies = currencies
        self.currency_map = {name: i for i, name in enumerate(currencies)}
        # --- DATA STRUCTURE: Directed Graph (Adjacency List) ---
        self.graph = defaultdict(dict)
        self.last_check_time = 0

    def _parse_symbol(self, symbol):
        for c in self.currencies:
            if symbol.endswith(c):
                base = symbol[:-len(c)]
                if base in self.currencies: return base, c
        return None, None

    def update_rate(self, symbol, bid, ask):
        """Updates the graph with a new exchange rate using negative logarithms."""
        base, quote = self._parse_symbol(symbol)
        if base and quote:
            if ask > 0: self.graph[quote][base] = -math.log(1 / ask)
            if bid > 0: self.graph[base][quote] = -math.log(bid)

    def find_negative_cycle(self):
        """ALGORITHM: Bellman-Ford to detect negative weight cycles."""
        nodes = list(self.graph.keys())
        if not nodes: return None, 0
        
        distance = {node: float('inf') for node in nodes}
        predecessor = {node: None for node in nodes}
        source = nodes[0]
        distance[source] = 0

        for _ in range(len(nodes) - 1):
            for u in nodes:
                for v, weight in self.graph[u].items():
                    if distance[u] != float('inf') and distance[u] + weight < distance[v]:
                        distance[v] = distance[u] + weight
                        predecessor[v] = u
        
        for u in nodes:
            for v, weight in self.graph[u].items():
                if distance[u] != float('inf') and distance[u] + weight < distance[v]:
                    # Negative cycle found, reconstruct it
                    cycle = []
                    curr = v
                    for _ in range(len(nodes)):
                        if curr is None: return None, 0 # Should not happen
                        cycle.append(curr)
                        curr = predecessor[curr]
                    cycle.reverse()
                    
                    # Find the start of the actual loop
                    start_node = cycle[-1]
                    try:
                        start_index = cycle.index(start_node)
                        arbitrage_path = cycle[start_index:]
                        if arbitrage_path[0] != arbitrage_path[-1]: arbitrage_path.append(arbitrage_path[0])
                        return arbitrage_path, 1 # Simplified vote
                    except ValueError:
                        return None, 0
        return None, 0

# --- TRADING ENGINE THREAD ---
def trading_engine_worker(app_instance):
    """This thread runs all trading logic, algorithms, and makes trade decisions."""
    print("Trading Engine thread started.")
    best_bid, best_ask, last_trade_price = defaultdict(float), defaultdict(float), defaultdict(float)
    pair_hist = pd.DataFrame()
    tri_arb_engine = TriangularArbitrageEngine(TRI_ARB_CURRENCIES)

    while app_instance.is_running:
        try:
            payload = app_instance.data_queue.get(timeout=0.1)
            symbol = payload['symbol']
            price = payload.get('price') or (payload.get('bid_price', 0) + payload.get('ask_price', 0)) / 2.0
            if price == 0: continue
            
            app_instance.latest_prices[symbol] = price
            params = app_instance.get_params()
            votes = defaultdict(int)

            # 1. Latency Arbitrage
            if params['latency_enabled'] and symbol in LATENCY_ARB_SYMBOLS:
                if payload['type'] == 'TRADE': last_trade_price[symbol] = price
                elif payload['type'] == 'QUOTE':
                    best_bid[symbol], best_ask[symbol] = payload['bid_price'], payload['ask_price']
                if last_trade_price[symbol] > 0 and best_ask[symbol] > 0:
                    if last_trade_price[symbol] > best_ask[symbol] + params['min_profit_usd']: votes['LAT'] = 1
                    if last_trade_price[symbol] < best_bid[symbol] - params['min_profit_usd']: votes['LAT'] = -1
            
            # 2. Statistical Arbitrage (Pairs Trading)
            if params['pairs_enabled'] and symbol in PAIRS_TRADING_SYMBOLS:
                new_row = pd.DataFrame({symbol: [price]}, index=[datetime.fromtimestamp(payload['timestamp'])])
                if pair_hist.empty: pair_hist = new_row
                else: pair_hist = pd.concat([pair_hist, new_row]).sort_index()
                pair_hist = pair_hist.ffill().iloc[-DATA_HISTORY_LEN:]
                s1, s2 = PAIRS_TRADING_SYMBOLS
                if s1 in pair_hist.columns and s2 in pair_hist.columns and len(pair_hist) > params['pairs_window']:
                    ratio = pair_hist[s1] / pair_hist[s2]
                    z_score = (ratio.iloc[-1] - ratio.mean()) / ratio.std()
                    app_instance.pairs_z_score = z_score
                    if z_score > params['pairs_threshold']: votes['PAIRS'] = -1
                    if z_score < -params['pairs_threshold']: votes['PAIRS'] = 1

            # 3. Triangular Arbitrage
            if params['tri_arb_enabled'] and payload['type'] == 'QUOTE':
                tri_arb_engine.update_rate(symbol, payload['bid_price'], payload['ask_price'])
                now = time.time()
                if now - tri_arb_engine.last_check_time > params.get('tri_arb_interval', 0.5):
                    path, profit = tri_arb_engine.find_negative_cycle()
                    if path:
                        app_instance.signal_queue.put({"type": "TRI_ARB", "path": path, "profit": profit})
                        votes['TRI'] = 1 # Simplified vote
                    tri_arb_engine.last_check_time = now
            
            # --- VOTE & EXECUTE ---
            total_votes = sum(votes.values())
            app_instance.latest_votes[symbol] = votes
            if abs(total_votes) >= params['vote_threshold']:
                signal_type = "BUY" if total_votes > 0 else "SELL"
                current_inv_usd = app_instance.inventory.get(symbol, 0) * price
                max_pos = params.get(f'max_pos_{symbol}', 500000.0)
                trade_size = max_pos * 0.1 # Trade 10% of max position
                if not (signal_type == "BUY" and current_inv_usd + trade_size > max_pos):
                    app_instance.signal_queue.put({"type": signal_type, "price": price, "symbol": symbol, "reason": f"Vote: {total_votes}", "size_usd": trade_size})

        except Empty: continue
        except Exception as e:
            if app_instance.is_running: print(f"Trading Engine error: {e}")
    print("Trading Engine thread shut down.")

# --- TKINTER GUI APPLICATION ---
class QuantTerminal:
    def __init__(self, root):
        self.root = root; self.root.title("Quantitative Trading Terminal"); self.root.geometry("1800x1000")
        self.is_running = True
        self.data_queue, self.signal_queue = Queue(maxsize=2000), Queue()
        self.cash, self.inventory = INITIAL_CASH, defaultdict(float)
        self.latest_prices, self.pnl_history = defaultdict(float), deque(maxlen=DATA_HISTORY_LEN * 2)
        self.pairs_z_score = 0.0
        self.latest_votes = defaultdict(dict)
        self.param_lock, self.params = Lock(), {}
        self._build_ui(); self.apply_params()
        self.zmq_thread = Thread(target=zmq_thread_worker, args=(self,), daemon=True); self.zmq_thread.start()
        self.engine_thread = Thread(target=trading_engine_worker, args=(self,), daemon=True); self.engine_thread.start()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.after(100, self._update_gui)

    def on_closing(self): print("Shutdown signal received..."); self.is_running = False; self.root.after(500, self.root.destroy)
    def get_params(self):
        with self.param_lock: return self.params.copy()
    def apply_params(self):
        with self.param_lock: self.params = {p: v.get() for p, v in self.param_vars.items()}
        self.log_message("SYSTEM: Parameters applied to the trading engine.", "system")

    def _build_ui(self):
        style = ttk.Style(); style.theme_use('clam'); style.configure("TNotebook.Tab", font=("Segoe UI", 10, "bold")); style.configure("Treeview.Heading", font=("Consolas", 10, "bold")); style.configure("Treeview", rowheight=25, font=("Consolas", 10))
        header_frame = tk.Frame(self.root, padx=10, pady=5); header_frame.pack(fill=tk.X)
        self.lbl_pnl = tk.Label(header_frame, text="PnL (MtM): $0.00", font=("Consolas", 14, "bold")); self.lbl_pnl.pack(side=tk.LEFT, padx=20)
        self.lbl_cash = tk.Label(header_frame, text=f"Cash: ${self.cash:,.2f}", font=("Consolas", 12)); self.lbl_cash.pack(side=tk.LEFT, padx=20)
        status_bar = tk.Frame(self.root, padx=10, pady=2, bd=1, relief=tk.SUNKEN); status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.lbl_status = tk.Label(status_bar, text="System Initializing...", font=("Segoe UI", 9)); self.lbl_status.pack(side=tk.LEFT)
        main_frame = tk.Frame(self.root, padx=10, pady=10); main_frame.pack(fill=tk.BOTH, expand=True)
        paned_window = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL); paned_window.pack(fill=tk.BOTH, expand=True)
        grid_frame, right_panel = tk.Frame(paned_window), tk.Frame(paned_window)
        paned_window.add(grid_frame, weight=3); paned_window.add(right_panel, weight=2)
        self.grid_cols = ["Symbol", "Price", "Inventory", "LAT Vote", "PAIRS Vote", "TRI Vote", "Total Score"]
        self.tree = ttk.Treeview(grid_frame, columns=self.grid_cols, show="headings")
        for col in self.grid_cols: self.tree.heading(col, text=col); self.tree.column(col, width=110, anchor='w')
        for symbol in sorted(ALL_SYMBOLS): self.tree.insert("", "end", iid=symbol, values=[symbol] + ["-"] * (len(self.grid_cols) - 1))
        self.tree.pack(fill=tk.BOTH, expand=True)
        log_label = tk.Label(grid_frame, text="Execution Log", font=("Arial", 12, "bold")); log_label.pack(fill=tk.X)
        self.log = scrolledtext.ScrolledText(grid_frame, height=10, font=("Consolas", 9), state='disabled', bg="#1C1C1C", fg="white"); self.log.pack(fill=tk.X, expand=False, pady=5)
        self.log.tag_config("buy", foreground="#27C281"); self.log.tag_config("sell", foreground="#FF6B6B"); self.log.tag_config("system", foreground="#4098FF"); self.log.tag_config("arb", foreground="yellow", font=("Consolas", 9, "bold"))
        notebook = ttk.Notebook(right_panel); notebook.pack(fill=tk.BOTH, expand=True)
        tab_charts, tab_admin = ttk.Frame(notebook), ttk.Frame(notebook)
        notebook.add(tab_charts, text="Charts"); notebook.add(tab_admin, text="Admin Controls")
        self.chart_notebook = ttk.Notebook(tab_charts); self.chart_notebook.pack(fill=tk.BOTH, expand=True)
        self.pnl_chart_frame = ttk.Frame(self.chart_notebook); self.chart_notebook.add(self.pnl_chart_frame, text="P&L")
        self.pairs_chart_frame = ttk.Frame(self.chart_notebook); self.chart_notebook.add(self.pairs_chart_frame, text="Pairs Spread")
        self.fig_pnl, self.ax_pnl = plt.subplots(tight_layout=True); self.canvas_pnl = FigureCanvasTkAgg(self.fig_pnl, master=self.pnl_chart_frame); self.canvas_pnl.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.fig_pairs, self.ax_pairs = plt.subplots(tight_layout=True); self.canvas_pairs = FigureCanvasTkAgg(self.fig_pairs, master=self.pairs_chart_frame); self.canvas_pairs.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.param_vars = {}; admin_frame = ttk.Frame(tab_admin, padding="10"); admin_frame.pack(fill="both", expand=True)
        lf_gen = ttk.LabelFrame(admin_frame, text="General", padding="10"); lf_gen.pack(fill="x", pady=5)
        ttk.Label(lf_gen, text="Vote Threshold:").grid(row=0, column=0, sticky='w'); self.param_vars['vote_threshold'] = tk.IntVar(value=1); ttk.Entry(lf_gen, textvariable=self.param_vars['vote_threshold'], width=5).grid(row=0, column=1)
        lf_lat = ttk.LabelFrame(admin_frame, text="Latency Arbitrage", padding="10"); lf_lat.pack(fill="x", pady=5)
        self.param_vars['latency_enabled'] = tk.BooleanVar(value=True); ttk.Checkbutton(lf_lat, text="Enabled", variable=self.param_vars['latency_enabled']).grid(row=0, columnspan=2, sticky='w')
        ttk.Label(lf_lat, text="Min Profit ($):").grid(row=1, column=0, sticky='w'); self.param_vars['min_profit_usd'] = tk.DoubleVar(value=0.01); ttk.Entry(lf_lat, textvariable=self.param_vars['min_profit_usd'], width=7).grid(row=1, column=1)
        lf_pairs = ttk.LabelFrame(admin_frame, text="Pairs Trading", padding="10"); lf_pairs.pack(fill="x", pady=5)
        self.param_vars['pairs_enabled'] = tk.BooleanVar(value=True); ttk.Checkbutton(lf_pairs, text="Enabled", variable=self.param_vars['pairs_enabled']).grid(row=0, columnspan=2, sticky='w')
        ttk.Label(lf_pairs, text="Window:").grid(row=1, column=0, sticky='w'); self.param_vars['pairs_window'] = tk.IntVar(value=100); ttk.Entry(lf_pairs, textvariable=self.param_vars['pairs_window'], width=5).grid(row=1, column=1)
        ttk.Label(lf_pairs, text="Z-Score Threshold:").grid(row=2, column=0, sticky='w'); self.param_vars['pairs_threshold'] = tk.DoubleVar(value=2.0); ttk.Entry(lf_pairs, textvariable=self.param_vars['pairs_threshold'], width=5).grid(row=2, column=1)
        lf_tri = ttk.LabelFrame(admin_frame, text="Triangular Arbitrage", padding="10"); lf_tri.pack(fill="x", pady=5)
        self.param_vars['tri_arb_enabled'] = tk.BooleanVar(value=True); ttk.Checkbutton(lf_tri, text="Enabled", variable=self.param_vars['tri_arb_enabled']).grid(row=0, columnspan=2, sticky='w')
        ttk.Label(lf_tri, text="Check Interval (s):").grid(row=1, column=0, sticky='w'); self.param_vars['tri_arb_interval'] = tk.DoubleVar(value=0.5); ttk.Entry(lf_tri, textvariable=self.param_vars['tri_arb_interval'], width=5).grid(row=1, column=1)
        lf_inv = ttk.LabelFrame(admin_frame, text="Inventory Management (Max Position $)", padding="10"); lf_inv.pack(fill="x", pady=5)
        for i, symbol in enumerate(sorted(ALL_SYMBOLS)):
            ttk.Label(lf_inv, text=f"{symbol}:").grid(row=i, column=0, sticky='w')
            self.param_vars[f'max_pos_{symbol}'] = tk.DoubleVar(value=1000000.0) # Default $1M position limit
            ttk.Entry(lf_inv, textvariable=self.param_vars[f'max_pos_{symbol}'], width=12).grid(row=i, column=1, sticky='w', padx=5)
        apply_btn = ttk.Button(admin_frame, text="Apply Settings to Engine", command=self.apply_params); apply_btn.pack(fill='x', pady=10)
        lf_liq = ttk.LabelFrame(admin_frame, text="Execution Controls", padding="10"); lf_liq.pack(fill="x", pady=10)
        self.liq_aggression = tk.DoubleVar(value=50); ttk.Scale(lf_liq, from_=1, to=100, variable=self.liq_aggression, orient='horizontal').pack(fill='x', pady=(0,5))
        ttk.Label(lf_liq, text="Slow (1) <--- Aggression ---> (100) Fast").pack(); ttk.Button(lf_liq, text="LIQUIDATE ALL POSITIONS", command=self.liquidate_all).pack(fill='x', pady=5)

    def _update_gui(self):
        if not self.is_running: return
        while not self.data_queue.empty(): self._process_data_update(self.data_queue.get_nowait())
        while not self.signal_queue.empty(): self._process_signal(self.signal_queue.get_nowait())
        self._update_portfolio_display()
        self.root.after(100, self._update_gui)
    
    def _process_data_update(self, data):
        symbol = data['symbol']
        votes = self.latest_votes[symbol]
        lat_vote = votes.get('LAT', 0)
        pairs_vote = votes.get('PAIRS', 0)
        tri_vote = votes.get('TRI', 0)
        total_votes = sum(votes.values())
        if self.tree.exists(symbol):
            self.tree.item(symbol, values=(symbol, f"{self.latest_prices[symbol]:.4f}", f"{self.inventory[symbol]:.4f}", f"{lat_vote:+}", f"{pairs_vote:+}", f"{tri_vote:+}", f"{total_votes:+}"))

    def _process_signal(self, signal):
        if signal.get("type") == "TRI_ARB":
            self.log_message(f"ARBITRAGE DETECTED: {' -> '.join(signal['path'])} | Profit: {signal['profit']:.4%}", "arb")
            return
        
        symbol, price, signal_type, reason, size_usd = signal['symbol'], signal['price'], signal['type'], signal['reason'], signal['size_usd']
        trade_qty = size_usd / price; self.log_message(f"SIGNAL: {signal_type} on {symbol} ({reason})", "system")
        if signal_type == "BUY":
            self.inventory[symbol] += trade_qty; self.cash -= size_usd
            self.log_message(f"  -> EXECUTED BUY of {trade_qty:.4f} {symbol}", "buy")
        elif signal_type == "SELL":
            self.inventory[symbol] -= trade_qty; self.cash += size_usd
            self.log_message(f"  -> EXECUTED SELL of {trade_qty:.4f} {symbol}", "sell")

    def _update_portfolio_display(self):
        inventory_value = sum(self.inventory[s] * self.latest_prices.get(s, 0) for s in ALL_SYMBOLS)
        pnl = self.cash + inventory_value - INITIAL_CASH
        self.pnl_history.append({'time': time.time(), 'pnl': pnl})
        self.lbl_pnl.config(text=f"PnL (MtM): ${pnl:,.2f}", fg="#27C281" if pnl >= 0 else "#FF6B6B")
        self.lbl_cash.config(text=f"Cash: ${self.cash:,.2f}")
        self._update_pnl_chart(); self._update_pairs_chart()

    def _update_pnl_chart(self):
        self.ax_pnl.clear(); history = list(self.pnl_history)
        if len(history) > 1:
            times = [datetime.fromtimestamp(p['time']) for p in history]; values = [p['pnl'] for p in history]
            self.ax_pnl.plot(times, values, color='cyan'); self.ax_pnl.fill_between(times, values, 0, where=[v >= 0 for v in values], color='green', alpha=0.3); self.ax_pnl.fill_between(times, values, 0, where=[v < 0 for v in values], color='red', alpha=0.3)
        self.ax_pnl.set_title("Total P&L Over Time"); self.ax_pnl.grid(True, linestyle='--', alpha=0.6); self.fig_pnl.autofmt_xdate(); self.canvas_pnl.draw()

    def _update_pairs_chart(self):
        self.ax_pairs.clear(); params = self.get_params(); threshold = params.get('pairs_threshold', 2.0)
        self.ax_pairs.axhline(0, color='gray', linestyle='--'); self.ax_pairs.axhline(threshold, color='red', linestyle=':', label=f'Sell Threshold (+{threshold}σ)'); self.ax_pairs.axhline(-threshold, color='green', linestyle=':', label=f'Buy Threshold (-{threshold}σ)')
        self.ax_pairs.bar(1, [self.pairs_z_score], color='skyblue'); self.ax_pairs.set_xticks([]); self.ax_pairs.set_ylabel('Z-Score'); self.ax_pairs.set_title(f"Pairs Trade Spread ({'/'.join(PAIRS_TRADING_SYMBOLS)})"); self.ax_pairs.legend(); self.canvas_pairs.draw()

    def liquidate_all(self):
        aggression = self.liq_aggression.get(); self.log_message(f"--- LIQUIDATE ALL triggered with aggression: {aggression:.0f}% ---", "sell")
        self.cash = INITIAL_CASH; self.inventory = defaultdict(float)

    def log_message(self, msg, tag=None):
        self.log.config(state='normal'); self.log.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}\n", tag); self.log.see(tk.END); self.log.config(state='disabled')

if __name__ == '__main__':
    root = tk.Tk()
    app = QuantTerminal(root)
    root.mainloop()

