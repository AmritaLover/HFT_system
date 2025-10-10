# advanced_terminal_with_fib_fixed.py
#
# A High-Performance Quantitative Trading Terminal implementing advanced algorithms.
#
# VERSION 7 - HEAP FIX:
# 1. Resolved the "list index out of range" error within the FibonacciHeap's
#    _consolidate method by using a safer, more robust array size calculation.
# 2. This prevents crashes in the Dijkstra's algorithm during edge cases.

import tkinter as tk
from tkinter import ttk, scrolledtext
import zmq
import json
import time
from collections import deque, defaultdict
from threading import Thread, Lock
from queue import Queue, Empty
import math # Needed for Fibonacci Heap
import numpy as np
import pandas as pd
from sklearn.linear_model import SGDRegressor
from fastdtw import fastdtw
from datetime import datetime
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# --- 1. COMPLEX DATA STRUCTURE: FIBONACCI HEAP ---

class FibonacciHeapNode:
    """ A node for the Fibonacci Heap. """
    def __init__(self, key, value):
        self.key = key
        self.value = value
        self.parent = self.child = None
        self.left = self.right = self
        self.degree = 0
        self.mark = False

class FibonacciHeap:
    """
    A from-scratch implementation of a Fibonacci Heap.
    This structure is theoretically optimal for its fast 'decrease_key' operation,
    making it a sophisticated choice for advanced graph algorithms like Dijkstra's.
    """
    def __init__(self):
        self.min_node = None
        self.total_nodes = 0
        self.node_map = {}

    def is_empty(self):
        return self.total_nodes == 0

    def insert(self, key, value):
        """ Inserts a new key-value pair into the heap. """
        node = FibonacciHeapNode(key, value)
        self.node_map[value] = node
        if self.min_node is None:
            self.min_node = node
        else:
            self._add_to_root_list(node)
            if node.key < self.min_node.key:
                self.min_node = node
        self.total_nodes += 1
        return node

    def extract_min(self):
        """ Extracts the node with the minimum key. """
        z = self.min_node
        if z is not None:
            if z.child:
                child = z.child
                while True:
                    next_child = child.right
                    self._add_to_root_list(child)
                    child.parent = None
                    child = next_child
                    if child == z.child:
                        break
            self._remove_from_root_list(z)
            if z == z.right:
                self.min_node = None
            else:
                self.min_node = z.right
                self._consolidate()
            self.total_nodes -= 1
            if z.value in self.node_map:
                del self.node_map[z.value]
            return z.key, z.value
        return None, None

    def decrease_key(self, value, new_key):
        """ Decreases the key of a given value. This is the key efficient operation. """
        node = self.node_map.get(value)
        if node is None or new_key > node.key:
            return
        node.key = new_key
        parent = node.parent
        if parent is not None and node.key < parent.key:
            self._cut(node, parent)
            self._cascading_cut(parent)
        if node.key < self.min_node.key:
            self.min_node = node

    def _add_to_root_list(self, node):
        node.right = self.min_node.right
        node.left = self.min_node
        self.min_node.right.left = node
        self.min_node.right = node

    def _remove_from_root_list(self, node):
        node.left.right = node.right
        node.right.left = node.left

    def _consolidate(self):
        # FIX: Use a safer, larger array size to prevent index errors.
        # The max degree is always less than the total number of nodes.
        aux = [None] * (self.total_nodes + 1)
        nodes = []
        x = self.min_node
        if x:
            start = x
            while True:
                nodes.append(x)
                x = x.right
                if x == start:
                    break
        for x in nodes:
            d = x.degree
            while aux[d] is not None:
                y = aux[d]
                if x.key > y.key:
                    x, y = y, x
                self._link(y, x)
                aux[d] = None
                d += 1
            aux[d] = x
        self.min_node = None
        for i in range(len(aux)):
            if aux[i] is not None:
                if self.min_node is None:
                    self.min_node = aux[i]
                    aux[i].left = aux[i].right = aux[i]
                else:
                    self._add_to_root_list(aux[i])
                    if aux[i].key < self.min_node.key:
                        self.min_node = aux[i]

    def _link(self, y, x):
        self._remove_from_root_list(y)
        y.parent = x
        if x.child is None:
            x.child = y; y.right = y; y.left = y
        else:
            y.right = x.child.right; y.left = x.child
            x.child.right.left = y; x.child.right = y
        x.degree += 1; y.mark = False

    def _cut(self, x, y):
        if x == x.right: y.child = None
        else:
            x.right.left = x.left; x.left.right = x.right
            if y.child == x: y.child = x.right
        y.degree -= 1
        self._add_to_root_list(x)
        x.parent = None; x.mark = False

    def _cascading_cut(self, y):
        z = y.parent
        if z is not None:
            if not y.mark: y.mark = True
            else: self._cut(y, z); self._cascading_cut(z)

# --- 2. DIJKSTRA WITH FIBONACCI HEAP ---

def dijkstra_with_fib_heap(graph, start_node):
    """ Dijkstra's algorithm powered by our custom Fibonacci Heap. """
    distances = {node: float('inf') for node in graph}
    distances[start_node] = 0
    
    pq = FibonacciHeap()
    for node, dist in distances.items():
        pq.insert(dist, node)
        
    while not pq.is_empty():
        dist, current_node = pq.extract_min()
        if current_node is None or dist > distances[current_node]:
            continue
        for neighbor, weight in graph.get(current_node, {}).items():
            distance = dist + weight
            if distance < distances.get(neighbor, float('inf')):
                distances[neighbor] = distance
                pq.decrease_key(neighbor, distance)           
    return distances

# --- CONFIGURATION ---
RELAY_IP = '127.0.0.1'
RELAY_PORT = '5556'
INITIAL_CASH = 1000000.0
SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT']
DATA_HISTORY_LEN = 300

# --- ZMQ DATA INGESTION THREAD ---
def zmq_thread_worker(app_instance):
    context = zmq.Context()
    socket = context.socket(zmq.SUB)
    socket.connect(f"tcp://{RELAY_IP}:{RELAY_PORT}")
    for symbol in SYMBOLS:
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
    """This thread is the core 'brain' of the bot, running all strategies."""
    print("Trading Engine thread started.")
    
    price_history = {s: deque(maxlen=DATA_HISTORY_LEN) for s in SYMBOLS}
    graph_window = {s: deque(maxlen=100) for s in SYMBOLS}
    ml_models = {s: SGDRegressor(learning_rate='constant', eta0=0.001) for s in SYMBOLS}
    is_model_trained = {s: False for s in SYMBOLS}
    dc_state = {s: {'trend': 0, 'extreme': 0, 'threshold': 0.001} for s in SYMBOLS}
    bull_pattern = np.array([0.0, 0.2, 0.1, 0.4, 0.3, 0.6, 0.5, 0.9, 1.0])
    bear_pattern = np.array([1.0, 0.8, 0.9, 0.6, 0.7, 0.4, 0.5, 0.1, 0.0])

    while app_instance.is_running:
        try:
            payload = app_instance.data_queue.get(timeout=0.1)
            symbol = payload['symbol']
            price = payload.get('price') or (payload.get('bid_price', 0) + payload.get('ask_price', 0)) / 2.0
            timestamp = payload['timestamp']
            if price == 0: continue
            
            app_instance.gui_queue.put(payload)
            price_history[symbol].append(price)
            params = app_instance.get_params()
            votes = defaultdict(int)
            current_inventory = app_instance.inventory[symbol]

            # --- Strategy 1: Graph-Based SSSP (Dijkstra with Fibonacci Heap) ---
            if params['graph_enabled'] and len(price_history[symbol]) > 1:
                window = graph_window[symbol]
                window.append((price, timestamp))
                graph = defaultdict(dict)
                nodes = sorted(list(set(p for p, t in window)))
                graph_nodes = {node: {} for node in nodes}

                for i in range(len(window) - 1):
                    p1, t1 = window[i]; p2, t2 = window[i+1]
                    time_delta = max(t2 - t1, 1e-6)
                    weight = time_delta * (1 + abs(p2 - p1) / p1)
                    graph_nodes[p1][p2] = min(graph_nodes[p1].get(p2, float('inf')), weight)

                start_node = window[-1][0]
                if start_node in graph_nodes:
                    # INTEGRATION: Call the new Dijkstra function
                    dist = dijkstra_with_fib_heap(graph_nodes, start_node)
                    
                    # Filter out infinite distances before finding min/max
                    finite_dist = {k: v for k, v in dist.items() if v != float('inf')}
                    if len(finite_dist) > 1:
                        min_dist_node = min(finite_dist, key=finite_dist.get)
                        max_dist_node = max(finite_dist, key=finite_dist.get)
                        
                        if finite_dist[min_dist_node] < finite_dist[max_dist_node] and current_inventory > 0:
                            votes['SELL'] += 1
                        elif finite_dist[max_dist_node] < finite_dist[min_dist_node] and current_inventory == 0:
                            votes['BUY'] += 1

            # ... (Other strategies remain unchanged) ...
            if params['ml_enabled'] and len(price_history[symbol]) >= 50:
                series = pd.Series(list(price_history[symbol]))
                features = np.array([
                    series.rolling(20).std().iloc[-1], series.diff(10).iloc[-1],
                    series.rolling(30).skew().iloc[-1]
                ]).reshape(1, -1)
                
                if not np.isnan(features).any():
                    if is_model_trained[symbol]:
                        prediction = ml_models[symbol].predict(features)[0]
                        if prediction > price and current_inventory == 0:
                            votes['BUY'] += 1
                        elif prediction < price and current_inventory > 0:
                            votes['SELL'] += 1
                    
                    ml_models[symbol].partial_fit(features, [price])
                    is_model_trained[symbol] = True

            if params['dc_enabled']:
                state = dc_state[symbol]; state['threshold'] = params['dc_threshold']
                if state['trend'] == 0: state['trend'], state['extreme'] = 1, price
                elif state['trend'] == 1:
                    if price < state['extreme'] * (1 - state['threshold']):
                        state['trend'], state['extreme'] = -1, price
                        if current_inventory > 0: votes['SELL'] += 1
                    else: state['extreme'] = max(state['extreme'], price)
                elif state['trend'] == -1:
                    if price > state['extreme'] * (1 + state['threshold']):
                        state['trend'], state['extreme'] = 1, price
                        if current_inventory == 0: votes['BUY'] += 1
                    else: state['extreme'] = min(state['extreme'], price)
                app_instance.strategy_states[f"{symbol}_DC"] = "UP" if state['trend'] == 1 else "DOWN"

            if params['dtw_enabled'] and len(price_history[symbol]) >= 50:
                current_pattern = np.array(list(price_history[symbol])[-50:])
                normalized_pattern = (current_pattern - np.min(current_pattern)) / (np.max(current_pattern) - np.min(current_pattern) or 1)
                dist_to_bull, _ = fastdtw(normalized_pattern, bull_pattern)
                dist_to_bear, _ = fastdtw(normalized_pattern, bear_pattern)
                app_instance.strategy_states[f"{symbol}_DTW"] = f"Bull: {dist_to_bull:.2f}|Bear: {dist_to_bear:.2f}"
                
                if dist_to_bull < params['dtw_threshold'] and dist_to_bull < dist_to_bear and current_inventory == 0:
                    votes['BUY'] += 1
                if dist_to_bear < params['dtw_threshold'] and dist_to_bear < dist_to_bull and current_inventory > 0:
                    votes['SELL'] += 1

            if max(votes.values() or [0]) >= params['vote_threshold']:
                signal_type = "BUY" if votes['BUY'] > votes['SELL'] else "SELL"
                reason = f"Votes (B/S): {votes['BUY']}/{votes['SELL']}"
                app_instance.signal_queue.put({"type": signal_type, "price": price, "symbol": symbol, "reason": reason})

        except Empty: continue
        except Exception as e:
            if app_instance.is_running: print(f"Trading Engine error: {e}")
    print("Trading Engine thread has shut down.")

class QuantTerminal:
    def __init__(self, root):
        self.root = root
        self.root.title("Advanced Quantitative Terminal (w/ Fibonacci Heap)")
        self.root.geometry("1800x1000")
        self.is_running = True
        self._shutting_down = False
        self.data_queue, self.gui_queue, self.signal_queue = Queue(maxsize=2000), Queue(), Queue()
        self.cash, self.inventory = INITIAL_CASH, {s: 0.0 for s in SYMBOLS}
        self.latest_prices = {s: 0.0 for s in SYMBOLS}
        self.price_history = {s: deque(maxlen=DATA_HISTORY_LEN) for s in SYMBOLS}
        self.pnl_history = deque(maxlen=DATA_HISTORY_LEN * 2)
        self.strategy_states = {}
        self.param_lock, self.params = Lock(), {}
        self._build_ui()
        self.apply_params()
        self.zmq_thread = Thread(target=zmq_thread_worker, args=(self,), daemon=True); self.zmq_thread.start()
        self.engine_thread = Thread(target=trading_engine_worker, args=(self,), daemon=True); self.engine_thread.start()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.after(100, self._update_gui)

    def on_closing(self):
        if self._shutting_down: return
        self._shutting_down = True
        print("Shutdown signal received...")
        self.is_running = False
        self.root.after(500, self.root.destroy)

    def get_params(self):
        with self.param_lock: return self.params.copy()

    def apply_params(self):
        with self.param_lock: self.params = {p: v.get() for p, v in self.param_vars.items()}
        self.log_message("SYSTEM: Parameters applied to the trading engine.", "system")

    def _build_ui(self):
        style = ttk.Style(); style.theme_use('clam'); style.configure("Treeview.Heading", font=("Consolas", 10, "bold")); style.configure("Treeview", rowheight=25, font=("Consolas", 10))
        header = tk.Frame(self.root, padx=10, pady=5); header.pack(fill=tk.X)
        self.lbl_pnl = tk.Label(header, text="PnL: $0.00", font=("Consolas", 14, "bold")); self.lbl_pnl.pack(side=tk.LEFT, padx=20)
        self.lbl_cash = tk.Label(header, text=f"Cash: ${self.cash:,.2f}", font=("Consolas", 12)); self.lbl_cash.pack(side=tk.LEFT, padx=20)
        main_frame = tk.Frame(self.root, padx=10, pady=10); main_frame.pack(fill=tk.BOTH, expand=True)
        paned = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL); paned.pack(fill=tk.BOTH, expand=True)
        grid_frame, right_panel = tk.Frame(paned), tk.Frame(paned); paned.add(grid_frame, weight=3); paned.add(right_panel, weight=2)
        self.grid_cols = ["Symbol", "Price", "Inventory", "DC Trend", "DTW Match"]; self.tree = ttk.Treeview(grid_frame, columns=self.grid_cols, show="headings")
        for col in self.grid_cols: self.tree.heading(col, text=col); self.tree.column(col, width=150, anchor='w')
        for symbol in SYMBOLS: self.tree.insert("", "end", iid=symbol, values=[symbol] + ["-"] * 4)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind('<<TreeviewSelect>>', self._on_symbol_select)
        self.log = scrolledtext.ScrolledText(grid_frame, height=10, font=("Consolas", 9), state='disabled'); self.log.pack(fill=tk.BOTH, expand=True, pady=5)
        self.log.tag_config("buy", foreground="#27C281"); self.log.tag_config("sell", foreground="#FF6B6B"); self.log.tag_config("system", foreground="#4098FF")
        notebook = ttk.Notebook(right_panel); notebook.pack(fill=tk.BOTH, expand=True)
        tab_charts, tab_admin = ttk.Frame(notebook), ttk.Frame(notebook)
        notebook.add(tab_charts, text="Charts"); notebook.add(tab_admin, text="Admin Controls")
        self.lbl_selected_symbol = tk.Label(tab_charts, text="<Select a symbol>", font=("Consolas", 12, "bold")); self.lbl_selected_symbol.pack(pady=5)
        self.fig_strategy, self.ax_strategy = plt.subplots(tight_layout=True); self.canvas_strategy = FigureCanvasTkAgg(self.fig_strategy, master=tab_charts); self.canvas_strategy.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.fig_pnl, self.ax_pnl = plt.subplots(tight_layout=True); self.canvas_pnl = FigureCanvasTkAgg(self.fig_pnl, master=tab_charts); self.canvas_pnl.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.param_vars = {}; admin_frame = ttk.Frame(tab_admin, padding="10"); admin_frame.pack(fill="both", expand=True)
        lf_gen = ttk.LabelFrame(admin_frame, text="General", padding="10"); lf_gen.pack(fill="x", pady=5); ttk.Label(lf_gen, text="Vote Threshold:").grid(row=0, column=0, sticky='w'); self.param_vars['vote_threshold'] = tk.IntVar(value=2); ttk.Entry(lf_gen, textvariable=self.param_vars['vote_threshold'], width=5).grid(row=0, column=1)
        lf_graph = ttk.LabelFrame(admin_frame, text="Graph SSSP Strategy", padding="10"); lf_graph.pack(fill="x", pady=5); self.param_vars['graph_enabled'] = tk.BooleanVar(value=True); ttk.Checkbutton(lf_graph, text="Enabled", variable=self.param_vars['graph_enabled']).pack(anchor='w')
        lf_ml = ttk.LabelFrame(admin_frame, text="ML Time Series Strategy", padding="10"); lf_ml.pack(fill="x", pady=5); self.param_vars['ml_enabled'] = tk.BooleanVar(value=True); ttk.Checkbutton(lf_ml, text="Enabled", variable=self.param_vars['ml_enabled']).pack(anchor='w')
        lf_dc = ttk.LabelFrame(admin_frame, text="Directional Change (DC)", padding="10"); lf_dc.pack(fill="x", pady=5); self.param_vars['dc_enabled'] = tk.BooleanVar(value=True); ttk.Checkbutton(lf_dc, text="Enabled", variable=self.param_vars['dc_enabled']).grid(row=0, sticky='w'); ttk.Label(lf_dc, text="Threshold (%):").grid(row=1, column=0, sticky='w'); self.param_vars['dc_threshold'] = tk.DoubleVar(value=0.001); ttk.Entry(lf_dc, textvariable=self.param_vars['dc_threshold'], width=7).grid(row=1, column=1)
        lf_dtw = ttk.LabelFrame(admin_frame, text="Dynamic Time Warping (DTW)", padding="10"); lf_dtw.pack(fill="x", pady=5); self.param_vars['dtw_enabled'] = tk.BooleanVar(value=True); ttk.Checkbutton(lf_dtw, text="Enabled", variable=self.param_vars['dtw_enabled']).grid(row=0, sticky='w'); ttk.Label(lf_dtw, text="Match Threshold:").grid(row=1, column=0, sticky='w'); self.param_vars['dtw_threshold'] = tk.DoubleVar(value=3.5); ttk.Entry(lf_dtw, textvariable=self.param_vars['dtw_threshold'], width=7).grid(row=1, column=1)
        ttk.Button(admin_frame, text="Apply All Settings to Engine", command=self.apply_params).pack(fill='x', pady=20)

    def _update_gui(self):
        if not self.is_running: return
        while not self.gui_queue.empty(): self._process_gui_data(self.gui_queue.get_nowait())
        while not self.signal_queue.empty(): self._process_signal(self.signal_queue.get_nowait())
        self._update_portfolio_display()
        selected = self.tree.selection()
        if selected: self._update_strategy_chart(selected[0])
        self.root.after(250, self._update_gui)

    def _process_gui_data(self, payload):
        symbol = payload['symbol']
        price = payload.get('price') or (payload.get('bid_price', 0) + payload.get('ask_price', 0)) / 2.0
        self.latest_prices[symbol] = price
        self.price_history[symbol].append(price)
        if self.tree.exists(symbol):
            self.tree.item(symbol, values=(
                symbol, f"{price:.4f}", f"{self.inventory[symbol]:.4f}",
                self.strategy_states.get(f"{symbol}_DC", "-"), self.strategy_states.get(f"{symbol}_DTW", "-")
            ))
    
    def _process_signal(self, signal):
        symbol, price, sig_type, reason = signal['symbol'], signal['price'], signal['type'], signal['reason']
        trade_size = 25000.0; qty = trade_size / price if price > 0 else 0
        self.log_message(f"SIGNAL: {sig_type} {symbol} ({reason})", "system")
        if sig_type == "BUY" and self.cash >= trade_size:
            self.inventory[symbol] += qty; self.cash -= trade_size; self.log_message(f"  -> EXECUTED BUY {qty:.4f}", "buy")
        elif sig_type == "SELL" and self.inventory[symbol] > 0:
            exec_qty = min(qty, self.inventory[symbol]); self.inventory[symbol] -= exec_qty; self.cash += exec_qty * price; self.log_message(f"  -> EXECUTED SELL {exec_qty:.4f}", "sell")

    def _update_portfolio_display(self):
        inv_value = sum(self.inventory[s] * self.latest_prices.get(s, 0) for s in SYMBOLS)
        pnl = self.cash + inv_value - INITIAL_CASH
        self.pnl_history.append({'time': time.time(), 'pnl': pnl})
        self.lbl_pnl.config(text=f"PnL: ${pnl:,.2f}", fg="#27C281" if pnl >= 0 else "#FF6B6B")
        self.lbl_cash.config(text=f"Cash: ${self.cash:,.2f}")
        self._update_pnl_chart()

    def _on_symbol_select(self, event):
        selected = self.tree.selection()
        if selected: self.lbl_selected_symbol.config(text=f"Chart: {selected[0]}"); self._update_strategy_chart(selected[0])

    def _update_strategy_chart(self, symbol):
        self.ax_strategy.clear()
        prices = list(self.price_history[symbol])
        if len(prices) > 1:
            self.ax_strategy.plot(prices, color='deepskyblue', linewidth=1.5)
        self.ax_strategy.set_title(f'{symbol} Price Action', fontsize=10)
        self.ax_strategy.grid(True, linestyle='--', alpha=0.6)
        self.canvas_strategy.draw()

    def _update_pnl_chart(self):
        self.ax_pnl.clear()
        history = list(self.pnl_history)
        if len(history) > 1:
            times = [datetime.fromtimestamp(p['time']) for p in history]; values = [p['pnl'] for p in history]
            self.ax_pnl.plot(times, values, color='cyan')
            self.ax_pnl.fill_between(times, values, 0, where=[v >= 0 for v in values], color='green', alpha=0.3)
            self.ax_pnl.fill_between(times, values, 0, where=[v < 0 for v in values], color='red', alpha=0.3)
        self.ax_pnl.set_title("Total P&L Over Time", fontsize=10); self.ax_pnl.grid(True, linestyle='--', alpha=0.6)
        self.fig_pnl.autofmt_xdate(); self.canvas_pnl.draw()

    def log_message(self, msg, tag=None):
        self.log.config(state='normal'); self.log.insert(tk.END, f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}\n", tag); self.log.see(tk.END); self.log.config(state='disabled')

if __name__ == '__main__':
    root = tk.Tk()
    app = QuantTerminal(root)
    root.mainloop()
