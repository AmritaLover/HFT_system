import tkinter as tk
from tkinter import ttk, scrolledtext
import zmq
import json
import time
from collections import deque
from threading import Thread
from queue import Queue
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from datetime import datetime
import pandas as pd
import pandas_ta as ta

# --- CONFIGURATION ---
RELAY_IP = '127.0.0.1'
RELAY_PORT = '5556'
SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'ADAUSDT']
INITIAL_CASH = 1000000000.0
TRADE_SIZE_USD = 250000.0
DATA_HISTORY_LEN = 200 

# --- ZMQ BACKGROUND WORKER ---
def zmq_thread_worker(app_instance):
    """The engine: connects to ZMQ, runs strategies, and sends results to the GUI via queues."""
    context = zmq.Context()
    socket = context.socket(zmq.SUB)
    socket.connect(f"tcp://{RELAY_IP}:{RELAY_PORT}")
    
    for symbol in SYMBOLS:
        socket.setsockopt_string(zmq.SUBSCRIBE, f"TRADE_{symbol}")
        socket.setsockopt_string(zmq.SUBSCRIBE, f"QUOTE_{symbol}")
    
    price_history = {s: [] for s in SYMBOLS}
    last_seq_num = 0
    print("ZMQ thread connected and listening...")

    while app_instance.is_running:
        try:
            if socket.poll(timeout=100): 
                topic_bytes, payload_bytes = socket.recv_multipart(flags=zmq.NOBLOCK)
                payload = json.loads(payload_bytes)
                
                current_seq_num = payload.get('seq_num', 0)
                if last_seq_num != 0 and current_seq_num > last_seq_num + 1:
                    app_instance.dropped_messages += current_seq_num - (last_seq_num + 1)
                last_seq_num = current_seq_num
                
                price = payload.get('price') or (payload.get('bid_price', 0) + payload.get('ask_price', 0)) / 2.0
                if price == 0: continue
                
                payload['price'] = price
                symbol = payload['symbol']
                
                history = price_history[symbol]
                history.append(price)
                if len(history) > DATA_HISTORY_LEN:
                    price_history[symbol] = history[-DATA_HISTORY_LEN:]

                params = app_instance.get_params()
                latest_indicators, votes = {}, 0
                
                if len(history) > params.get('long_window', 50):
                    price_series = pd.Series(history)
                    
                    short_sma = price_series.rolling(window=params['short_window']).mean().iloc[-1]
                    long_sma = price_series.rolling(window=params['long_window']).mean().iloc[-1]
                    latest_indicators['short_sma'], latest_indicators['long_sma'] = short_sma, long_sma
                    if params['ma_enabled']: votes += 1 if short_sma > long_sma else -1
                    
                    rsi = ta.rsi(price_series, length=params['rsi_period']).iloc[-1]
                    latest_indicators['rsi'] = rsi
                    if params['rsi_enabled']: votes += 1 if rsi < params['rsi_oversold'] else -1 if rsi > params['rsi_overbought'] else 0
                    
                    bbands = ta.bbands(price_series, length=params['bb_period'], std=params['bb_std'])
                    if bbands is not None and not bbands.empty:
                        latest_indicators['bbl'] = bbands.iloc[-1, 0]
                        latest_indicators['bbu'] = bbands.iloc[-1, 2]
                        if params['bb_enabled']: votes += 1 if price > latest_indicators['bbu'] else -1 if price < latest_indicators['bbl'] else 0
                
                payload['indicators'] = latest_indicators
                payload['votes'] = votes
                app_instance.data_queue.put(payload)
                
                if abs(votes) >= params['vote_threshold']:
                    signal_type = "BUY" if votes > 0 else "SELL"
                    app_instance.signal_queue.put({"type": signal_type, "price": price, "symbol": symbol, "reason": f"Conviction Score: {votes}"})

        except zmq.Again: continue
        except Exception as e:
            if app_instance.is_running: print(f"ZMQ thread error: {e}")
            break
    print("ZMQ thread has shut down.")

# --- TKINTER GUI APPLICATION ---
class TradingApp:
    def __init__(self, root):
        self.root = root
        self.root.title("HFT Simulation Terminal")
        self.root.geometry("1600x900")
        self.is_running, self.dropped_messages = True, 0
        self.data_queue, self.signal_queue = Queue(), Queue()
        self.cash, self.inventory = INITIAL_CASH, {s: 0.0 for s in SYMBOLS}
        self.latest_prices, self.pnl_history = {s: 0.0 for s in SYMBOLS}, deque(maxlen=DATA_HISTORY_LEN * 2)
        self.price_history, self.signal_history = {s: deque(maxlen=DATA_HISTORY_LEN) for s in SYMBOLS}, {s: deque(maxlen=20) for s in SYMBOLS}
        self._build_ui()
        self.zmq_thread = Thread(target=zmq_thread_worker, args=(self,), daemon=True)
        self.zmq_thread.start()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.after(200, self._update_gui)

    def on_closing(self):
        print("Shutdown signal received. Closing application...")
        self.is_running = False
        self.root.after(300, self.root.destroy)

    def get_params(self):
        return {p: v.get() for p, v in self.param_vars.items()}

    def _build_ui(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("Treeview.Heading", font=("Consolas", 10, "bold"))
        style.configure("Treeview", rowheight=25, font=("Consolas", 10))
        
        header_frame = tk.Frame(self.root, padx=10, pady=5)
        header_frame.pack(fill=tk.X)
        self.lbl_pnl = tk.Label(header_frame, text="PnL (MtM): $0.00", font=("Consolas", 14, "bold"))
        self.lbl_pnl.pack(side=tk.LEFT, padx=20)
        self.lbl_cash = tk.Label(header_frame, text=f"Cash: ${self.cash:,.2f}", font=("Consolas", 12))
        self.lbl_cash.pack(side=tk.LEFT, padx=20)
        self.lbl_dropped = tk.Label(header_frame, text="Dropped Msgs: 0", font=("Consolas", 12), fg="orange")
        self.lbl_dropped.pack(side=tk.LEFT, padx=20)

        main_frame = tk.Frame(self.root, padx=10, pady=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        paned_window = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        paned_window.pack(fill=tk.BOTH, expand=True)

        grid_frame, right_panel = tk.Frame(paned_window), tk.Frame(paned_window)
        paned_window.add(grid_frame, weight=3)
        paned_window.add(right_panel, weight=2)

        self.grid_cols = ["Symbol", "Price", "Inventory", "MA Vote", "RSI Vote", "BB Vote", "Total Score"]
        self.tree = ttk.Treeview(grid_frame, columns=self.grid_cols, show="headings")
        for col in self.grid_cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=100, anchor='w')
        for symbol in SYMBOLS:
            self.tree.insert("", "end", iid=symbol, values=[symbol] + ["-"] * (len(self.grid_cols) - 1))
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind('<<TreeviewSelect>>', self._on_symbol_select)

        log_label = tk.Label(grid_frame, text="Trade Log", font=("Arial", 12, "bold"), pady=5)
        log_label.pack(fill=tk.X)
        self.log = scrolledtext.ScrolledText(grid_frame, height=10, font=("Consolas", 9), state='disabled')
        self.log.pack(fill=tk.X, expand=False, pady=(0, 5))
        self.log.tag_config("buy", foreground="green")
        self.log.tag_config("sell", foreground="red")

        notebook = ttk.Notebook(right_panel)
        notebook.pack(fill=tk.BOTH, expand=True)
        tab_charts, tab_admin = ttk.Frame(notebook), ttk.Frame(notebook)
        notebook.add(tab_charts, text="Charts")
        notebook.add(tab_admin, text="Admin Controls")
        
        self.selected_symbol_label = tk.Label(tab_charts, text="<Select a symbol>", font=("Consolas", 12, "bold"))
        self.selected_symbol_label.pack(pady=5)
        self.fig_price, self.ax_price = plt.subplots(tight_layout=True)
        self.canvas_price = FigureCanvasTkAgg(self.fig_price, master=tab_charts)
        self.canvas_price.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.fig_pnl, self.ax_pnl = plt.subplots(tight_layout=True)
        self.canvas_pnl = FigureCanvasTkAgg(self.fig_pnl, master=tab_charts)
        self.canvas_pnl.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        self.param_vars = {}
        admin_frame = ttk.Frame(tab_admin, padding="10")
        admin_frame.pack(fill="both", expand=True)
        
        lf_gen = ttk.LabelFrame(admin_frame, text="General Settings", padding="10"); lf_gen.pack(fill="x", pady=5)
        ttk.Label(lf_gen, text="Vote Threshold:").grid(row=0, column=0, sticky="w"); self.param_vars['vote_threshold'] = tk.IntVar(value=2); ttk.Entry(lf_gen, textvariable=self.param_vars['vote_threshold'], width=5).grid(row=0, column=1, sticky="w")
        
        lf_ma = ttk.LabelFrame(admin_frame, text="MA Crossover", padding="10"); lf_ma.pack(fill="x", pady=5)
        self.param_vars['ma_enabled'] = tk.BooleanVar(value=True); ttk.Checkbutton(lf_ma, text="Enabled", variable=self.param_vars['ma_enabled']).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(lf_ma, text="Short Window:").grid(row=1, column=0, sticky="w"); self.param_vars['short_window'] = tk.IntVar(value=10); ttk.Entry(lf_ma, textvariable=self.param_vars['short_window'], width=5).grid(row=1, column=1, sticky="w")
        ttk.Label(lf_ma, text="Long Window:").grid(row=2, column=0, sticky="w"); self.param_vars['long_window'] = tk.IntVar(value=50); ttk.Entry(lf_ma, textvariable=self.param_vars['long_window'], width=5).grid(row=2, column=1, sticky="w")
        
        lf_rsi = ttk.LabelFrame(admin_frame, text="RSI", padding="10"); lf_rsi.pack(fill="x", pady=5)
        self.param_vars['rsi_enabled'] = tk.BooleanVar(value=True); ttk.Checkbutton(lf_rsi, text="Enabled", variable=self.param_vars['rsi_enabled']).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(lf_rsi, text="Period:").grid(row=1, column=0, sticky="w"); self.param_vars['rsi_period'] = tk.IntVar(value=14); ttk.Entry(lf_rsi, textvariable=self.param_vars['rsi_period'], width=5).grid(row=1, column=1, sticky="w")
        ttk.Label(lf_rsi, text="Overbought:").grid(row=2, column=0, sticky="w"); self.param_vars['rsi_overbought'] = tk.IntVar(value=70); ttk.Entry(lf_rsi, textvariable=self.param_vars['rsi_overbought'], width=5).grid(row=2, column=1, sticky="w")
        ttk.Label(lf_rsi, text="Oversold:").grid(row=3, column=0, sticky="w"); self.param_vars['rsi_oversold'] = tk.IntVar(value=30); ttk.Entry(lf_rsi, textvariable=self.param_vars['rsi_oversold'], width=5).grid(row=3, column=1, sticky="w")
        
        lf_bb = ttk.LabelFrame(admin_frame, text="Bollinger Bands", padding="10"); lf_bb.pack(fill="x", pady=5)
        self.param_vars['bb_enabled'] = tk.BooleanVar(value=True); ttk.Checkbutton(lf_bb, text="Enabled", variable=self.param_vars['bb_enabled']).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(lf_bb, text="Period:").grid(row=1, column=0, sticky="w"); self.param_vars['bb_period'] = tk.IntVar(value=20); ttk.Entry(lf_bb, textvariable=self.param_vars['bb_period'], width=5).grid(row=1, column=1, sticky="w")
        ttk.Label(lf_bb, text="Std Dev:").grid(row=2, column=0, sticky="w"); self.param_vars['bb_std'] = tk.DoubleVar(value=2.0); ttk.Entry(lf_bb, textvariable=self.param_vars['bb_std'], width=5).grid(row=2, column=1, sticky="w")

    def _update_gui(self):
        if not self.is_running: return
        while not self.data_queue.empty():
            self._process_data_update(self.data_queue.get_nowait())
        while not self.signal_queue.empty():
            self._process_signal(self.signal_queue.get_nowait())
        
        self._update_portfolio_display()
        
        selected = self.tree.selection()
        if selected:
            self._update_chart(selected[0])
            
        self.root.after(200, self._update_gui)
    
    def _process_data_update(self, data):
        symbol, price, indicators, votes = data['symbol'], data['price'], data['indicators'], data['votes']
        self.latest_prices[symbol] = price
        self.price_history[symbol].append(price)
        
        if self.tree.exists(symbol):
            p = self.get_params()
            ma_vote = (1 if indicators.get('short_sma', 0) > indicators.get('long_sma', 0) else -1) if p['ma_enabled'] and 'short_sma' in indicators else 0
            rsi = indicators.get('rsi', 50)
            rsi_vote = (1 if rsi < p['rsi_oversold'] else -1 if rsi > p['rsi_overbought'] else 0) if p['rsi_enabled'] else 0
            bb_vote = (1 if price > indicators.get('bbu', price) else -1 if price < indicators.get('bbl', price) else 0) if p['bb_enabled'] and 'bbu' in indicators else 0
            
            values = (symbol, f"{price:.4f}", f"{self.inventory[symbol]:.4f}", f"{ma_vote:+}", f"{rsi_vote:+}", f"{bb_vote:+}", f"{votes:+}")
            self.tree.item(symbol, values=values)

    def _process_signal(self, signal):
        symbol, price, signal_type = signal['symbol'], signal['price'], signal['type']
        log_msg = f"[{time.strftime('%H:%M:%S')}] {symbol}: High Conviction {signal_type} SIGNAL ({signal['reason']})"
        self.log_message(log_msg, tag=signal_type.lower())
        self.signal_history[symbol].append({'time': time.time(), 'price': price, 'type': signal_type})
        
        trade_qty = TRADE_SIZE_USD / price
        if signal_type == "BUY" and self.cash >= TRADE_SIZE_USD:
            self.inventory[symbol] += trade_qty
            self.cash -= TRADE_SIZE_USD
            self.log_message(f"  -> EXECUTED BUY of {trade_qty:.4f} {symbol}", tag="buy")
        elif signal_type == "SELL" and self.inventory[symbol] >= trade_qty:
            self.inventory[symbol] -= trade_qty
            self.cash += TRADE_SIZE_USD
            self.log_message(f"  -> EXECUTED SELL of {trade_qty:.4f} {symbol}", tag="sell")

    def _update_portfolio_display(self):
        inventory_value = sum(self.inventory[s] * self.latest_prices.get(s, 0) for s in SYMBOLS)
        pnl = self.cash + inventory_value - INITIAL_CASH
        self.pnl_history.append({'time': time.time(), 'pnl': pnl})
        
        self.lbl_pnl.config(text=f"PnL (MtM): ${pnl:,.2f}", fg="green" if pnl >= 0 else "red")
        self.lbl_cash.config(text=f"Cash: ${self.cash:,.2f}")
        self.lbl_dropped.config(text=f"Dropped Msgs: {self.dropped_messages}")
        
        self._update_pnl_chart()

    def _on_symbol_select(self, event):
        selected = self.tree.selection()
        if not selected: return
        self.selected_symbol_label.config(text=f"Symbol: {selected[0]}")
        self._update_chart(selected[0])

    def _update_chart(self, symbol):
        self.ax_price.clear()
        prices, signals = list(self.price_history[symbol]), list(self.signal_history[symbol])
        
        if len(prices) > 1:
            price_indices = range(len(prices))
            self.ax_price.plot(price_indices, prices, color='skyblue', label=f'{symbol} Price')
            
            min_p, max_p = min(prices), max(prices)
            p_range = max_p - min_p if max_p > min_p else (max_p * 0.01 or 0.01)
            self.ax_price.set_ylim(min_p - p_range * 0.1, max_p + p_range * 0.1)
            
            buy_signals = [s for s in signals if s['type'] == 'BUY']
            sell_signals = [s for s in signals if s['type'] == 'SELL']
            
            if buy_signals:
                self.ax_price.scatter(len(prices) - 1, buy_signals[-1]['price'], color='green', marker='^', s=100, label='Buy Signal', zorder=5)
            if sell_signals:
                self.ax_price.scatter(len(prices) - 1, sell_signals[-1]['price'], color='red', marker='v', s=100, label='Sell Signal', zorder=5)

        self.ax_price.set_title(f'{symbol} Price Action')
        self.ax_price.grid(True, linestyle='--', alpha=0.6)
        self.ax_price.legend(fontsize='small')
        self.canvas_price.draw()

    def _update_pnl_chart(self):
        self.ax_pnl.clear()
        history = list(self.pnl_history)
        
        if len(history) > 1:
            times = [datetime.fromtimestamp(p['time']) for p in history]
            values = [p['pnl'] for p in history]
            
            self.ax_pnl.plot(times, values, color='cyan')
            self.ax_pnl.fill_between(times, values, 0, where=[v >= 0 for v in values], color='green', alpha=0.3, interpolate=True)
            self.ax_pnl.fill_between(times, values, 0, where=[v < 0 for v in values], color='red', alpha=0.3, interpolate=True)

        self.ax_pnl.set_title("Total P&L Over Time")
        self.ax_pnl.grid(True, linestyle='--', alpha=0.6)
        self.fig_pnl.autofmt_xdate()
        self.canvas_pnl.draw()

    def log_message(self, msg, tag=None):
        self.log.config(state='normal')
        self.log.insert(tk.END, msg + "\n", tag)
        self.log.see(tk.END)
        self.log.config(state='disabled')

if __name__ == '__main__':
    root = tk.Tk()
    app = TradingApp(root)
    root.mainloop()
