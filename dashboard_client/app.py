import dash
import dash_mantine_components as dmc
from dash import dcc, html, Input, Output
import plotly.graph_objs as go
from dash_iconify import DashIconify
import zmq
import json
import time
from collections import deque
from threading import Thread
import numpy as np

# --- CONFIGURATION (No changes) ---
RELAY_IP = '127.0.0.1'
RELAY_PORT = '5556'
SUBSCRIPTION_TOPIC = "TRADE_BTCUSDT"
SHORT_WINDOW = 10
LONG_WINDOW = 50

# --- DATA BUFFERS (No changes) ---
TRADE_BUFFER = deque(maxlen=200)
SIGNAL_BUFFER = deque(maxlen=50)
LATENCY_BUFFER = deque(maxlen=100)

# --- MOMENTUM STRATEGY CLASS (No changes) ---
class MomentumStrategy:
    def __init__(self, short_window, long_window):
        self.short_prices = deque(maxlen=short_window)
        self.long_prices = deque(maxlen=long_window)
        self.short_is_above_long = None

    def process_trade(self, trade_price, timestamp):
        self.short_prices.append(trade_price)
        self.long_prices.append(trade_price)
        if len(self.long_prices) < self.long_prices.maxlen: return None
        short_sma = sum(self.short_prices) / len(self.short_prices)
        long_sma = sum(self.long_prices) / len(self.long_prices)
        currently_above = short_sma > long_sma
        if self.short_is_above_long is None:
            self.short_is_above_long = currently_above
            return None
        if currently_above != self.short_is_above_long:
            self.short_is_above_long = currently_above
            signal_type = "BUY" if currently_above else "SELL"
            signal_reason = "Golden Cross" if currently_above else "Death Cross"
            signal_message = f"[{time.strftime('%H:%M:%S')}] {signal_type} SIGNAL ({signal_reason}) at {trade_price:.2f}"
            return {"type": signal_type, "price": trade_price, "timestamp": timestamp, "message": signal_message}
        return None

# --- ZMQ SUBSCRIBER THREAD (No changes) ---
def zmq_subscriber():
    strategy = MomentumStrategy(SHORT_WINDOW, LONG_WINDOW)
    context = zmq.Context()
    socket = context.socket(zmq.SUB)
    socket.connect(f"tcp://{RELAY_IP}:{RELAY_PORT}")
    socket.setsockopt_string(zmq.SUBSCRIBE, SUBSCRIPTION_TOPIC)
    print(f"Dashboard ZMQ thread subscribed to '{SUBSCRIPTION_TOPIC}'")
    while True:
        try:
            _, payload_bytes = socket.recv_multipart()
            arrival_ts = time.perf_counter()
            payload = json.loads(payload_bytes)
            TRADE_BUFFER.append((payload['timestamp'], payload['price']))
            LATENCY_BUFFER.append((arrival_ts - payload['origin_ts']) * 1000)
            signal = strategy.process_trade(payload['price'], payload['timestamp'])
            if signal: SIGNAL_BUFFER.append(signal)
        except Exception as e: print(f"Error in ZMQ thread: {e}"); time.sleep(1)

# --- DASH APP (LAYOUT REBUILT FOR STABILITY) ---
app = dash.Dash(__name__, external_stylesheets=['https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap'])

app.layout = dmc.MantineProvider(
    theme={"colorScheme": "dark"},
    withGlobalStyles=True,
    withNormalizeCSS=True,
    children=[
        # Using a simple Div to contain everything
        html.Div([
            # Header created with a styled Paper component
            dmc.Paper(
                p="md", shadow="xs", withBorder=True,
                children=[dmc.Title("HFT Simulation Dashboard", order=1, align="center")]
            ),
            dmc.Space(h=20),
            # Main content grid
            dmc.Grid(
                children=[
                    dmc.Col(dmc.Card(children=[dmc.Title("Live Price Chart", order=3), dcc.Graph(id='live-price-chart', animate=True)], withBorder=True), span=8),
                    dmc.Col(dmc.Card(children=[dmc.Title("Time & Sales", order=3), html.Div(id='live-tape')], withBorder=True), span=4),
                    dmc.Col(dmc.Card(children=[dmc.Title("Strategy Signal Log", order=3), html.Div(id='signal-log')], withBorder=True), span=8),
                    dmc.Col(dmc.Card(children=[dmc.Title("System Health", order=3), html.Div(id='system-health')], withBorder=True), span=4),
                ],
                gutter="xl",
            ),
            # Non-visual interval component
            dcc.Interval(id='interval-component', interval=500, n_intervals=0)
        ], style={'padding': '10px'})
    ]
)

# --- CALLBACKS (No changes) ---
@app.callback(Output('live-price-chart', 'figure'), Input('interval-component', 'n_intervals'))
def update_chart(n):
    trade_snapshot = list(TRADE_BUFFER); signal_snapshot = list(SIGNAL_BUFFER)
    if not trade_snapshot: return go.Figure(layout=go.Layout(template='plotly_dark', title='Waiting for data...'))
    timestamps = [t[0] for t in trade_snapshot]; prices = [t[1] for t in trade_snapshot]
    fig = go.Figure(layout=go.Layout(template='plotly_dark', margin=dict(t=20, b=0, l=0, r=0)))
    fig.add_trace(go.Scatter(x=timestamps, y=prices, mode='lines', name='Price'))
    buy_signals = [s for s in signal_snapshot if s['type'] == 'BUY']
    sell_signals = [s for s in signal_snapshot if s['type'] == 'SELL']
    fig.add_trace(go.Scatter(x=[s['timestamp'] for s in buy_signals], y=[s['price'] for s in buy_signals], mode='markers', name='Buy Signal', marker=dict(color='#27C281', size=10, symbol='triangle-up')))
    fig.add_trace(go.Scatter(x=[s['timestamp'] for s in sell_signals], y=[s['price'] for s in sell_signals], mode='markers', name='Sell Signal', marker=dict(color='#FF6B6B', size=10, symbol='triangle-down')))
    return fig

@app.callback(Output('signal-log', 'children'), Input('interval-component', 'n_intervals'))
def update_signal_log(n):
    signal_snapshot = list(SIGNAL_BUFFER)
    if not signal_snapshot: return dmc.Text("No signals generated yet.", color="gray", p="md")
    alerts = [dmc.Alert(s['message'], title=f"{s['type']} SIGNAL", color="green" if s['type'] == 'BUY' else "red", 
                        icon=[DashIconify(icon="radix-icons:check-circled")] if s['type'] == 'BUY' else [DashIconify(icon="radix-icons:cross-circled")],
                        withCloseButton=True, m=5)
              for s in reversed(signal_snapshot)]
    return alerts

# Add more callbacks here for the Tape and System Health panels

if __name__ == '__main__':
    zmq_thread = Thread(target=zmq_subscriber, daemon=True)
    zmq_thread.start()
    app.run(debug=True)