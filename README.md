# High-Frequency Trading (HFT) Simulation Platform

This project is a complete, end-to-end simulation platform for developing and testing HFT strategies, created for the 23CSE203 Data Structures and Algorithms course. The system captures live market data, replays it in a realistic, time-synced environment, and runs multiple arbitrage strategies against the feed, visualizing results in a real-time dashboard.

---

## Core Features

-   **Data Ingestion:** Captures live trade and quote data from exchanges using WebSockets.
-   **Market Replay:** Replays captured data from CSV files in a time-accurate simulation.
-   **Strategy Engine:** A multi-threaded engine that runs multiple trading strategies concurrently (e.g., Triangular Arbitrage, Pairs Trading).
-   **Real-Time UI:** A `tkinter`-based dashboard for monitoring strategy signals, portfolio P&L, and system health.
-   **Performance-Optimized:** Utilizes a decoupled architecture with ZeroMQ and efficient data structures (`deque`, graphs) for low-latency processing.

---

## System Architecture

The platform is a decoupled, four-stage data pipeline that separates the concerns of data collection, simulation, and strategy execution.



---

## Sample Market Data

The system processes two main types of data, captured and stored in `.csv` format.

**`quotes.csv` (Order Book Data)**
timestamp,symbol,bid_price,bid_size,ask_price,ask_size
1665207300.123,BTCUSDT,19500.50,2.5,19500.51,1.8
1665207300.456,ETHUSDT,1300.10,10.2,1300.12,8.5

**`trades.csv` (Executed Trades)**
timestamp,symbol,price,size
1665207301.789,BTCUSDT,19500.51,0.05
1665207301.991,ETHUSDT,1300.10,0.20

---

## Technology Stack

-   **Core:** Python 3
-   **Messaging:** ZeroMQ (`pyzmq`)
-   **Data Handling:** Pandas, NumPy
-   **UI & Visualization:** Tkinter, Matplotlib, Seaborn
-   **Graph Algorithms:** NetworkX
-   **Exchange API:** `python-binance`

---

## Setup & Installation

1.  **Clone the repository:**
    ```bash
    git clone [https://github.com/ojasJO/HFT_system.git](https://github.com/ojasJO/HFT_system.git)
    cd HFT_system
    ```
2.  **Create and activate a virtual environment:**
    ```bash
    python -m venv .venv
    # On Windows: .venv\Scripts\activate
    ```
3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
4.  **Install Graphviz (Required for visualizations):**
    * Download and install the Graphviz software from the [official website](https://graphviz.org/download/).
    * **Crucially, ensure you check the box to "Add Graphviz to the system PATH" during installation.**

---

## How to Run the Simulation

The system components must be run in a specific order, each in a **separate terminal**.

1.  **(Optional) Generate Data:**
    ```bash
    python data_recorder/data_recorder.py
    ```
2.  **Start the Market Server:**
    ```bash
    python server/server.py
    ```
3.  **Start the Network Relay:**
    ```bash
    python relay/relay.py
    ```
4.  **Start a Client Application:**
    ```bash
    python clients/dashboard_client.py
    ```