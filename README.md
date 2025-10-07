# High-Frequency Trading (HFT) Backtesting & Simulation Platform

A high-performance, multi-threaded platform built in Python for simulating and backtesting low-latency algorithmic trading strategies on real market data.



## Overview

This project provides an end-to-end framework for quantitative trading research. It handles the entire pipeline: from capturing live, high-frequency market data to replaying it in a controlled environment, executing complex trading logic, and visualizing performance in real-time. The system is designed with a focus on modularity and performance, using a decoupled architecture to simulate a realistic, low-latency trading environment.

---

## Core Features

-   **Live Data Ingestion:** Captures real-time trade and Level 1 quote data from crypto exchanges via low-latency WebSockets.
-   **High-Fidelity Market Replay:** Simulates market conditions by replaying captured data in a chronologically accurate event stream.
-   **Concurrent Strategy Engine:** A multi-threaded engine capable of running multiple, independent trading algorithms simultaneously.
-   **Real-Time Dashboard:** A `tkinter`-based GUI for monitoring strategy signals, portfolio P&L, system health, and live market data visualizations.
-   **Performance-Optimized:** Built on a decoupled, message-passing architecture using ZeroMQ to minimize internal latency and ensure high message throughput.

---

## System Architecture

The platform utilizes a four-stage, decoupled data pipeline. Each component is an independent process, communicating via a high-speed ZeroMQ message bus. This design ensures scalability and separation of concerns, which is critical for complex trading systems.



---

## Project Components

The repository is structured into several key components:
```
.
├── clients/                       # Contains the UI dashboard and strategy logic
├── data_recorder/                 # Script to capture live market data
├── relay/                         # Forwards data from the server to clients
├── server/                        # Reads data files and simulates the market
├── HFT_Platform_Analysis.ipynb    # The project analysis and presentation
├── README.md                      # This file
└── requirements.txt               # Project dependencies
```

-   **`data_recorder/`**: A standalone script that connects to the exchange API and saves trade/quote data to local CSV files.
-   **`server/`**: The heart of the simulation. It reads the CSV files, sorts all events by timestamp, and broadcasts them onto the network as if they were happening live.
-   **`relay/`**: A simple but powerful message forwarder. It subscribes to the server's data feed and re-publishes it, allowing multiple client applications to connect without overloading the main server.
-   **`clients/`**: Contains the main front-end application(s). This is where trading logic is executed based on the data feed, and where the UI dashboard visualizes all activity.

---

## Technology Stack

-   **Core Language:** `Python 3`
-   **Messaging Bus:** `ZeroMQ (pyzmq)` for high-throughput, low-latency inter-process communication.
-   **Data Handling & Analysis:** `Pandas` and `NumPy` for efficient data manipulation.
-   **UI & Visualization:** `Tkinter` for the dashboard and `Matplotlib`/`Seaborn` for real-time charting.
-   **Graph Algorithms:** `NetworkX` for modeling and analyzing arbitrage opportunities.

---

## Getting Started

### Prerequisites

-   Python 3.8+
-   Git
-   **Graphviz:** You must install the Graphviz system package for graph visualizations.
    -   Download from the [official website](https://graphviz.org/download/).
    -   **Important:** During installation, ensure you check the box to **"Add Graphviz to the system PATH"**.

### Installation & Setup

1.  **Clone the repository:**
    ```bash
    git clone [https://github.com/ojasJO/HFT_system.git](https://github.com/ojasJO/HFT_system.git)
    cd HFT_system
    ```

2.  **Create and activate a Python virtual environment:**
    ```bash
    python -m venv .venv
    # On Windows:
    .venv\Scripts\activate
    ```

3.  **Install the required dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

---

## Usage: Running the Simulation

The system components must be launched in a specific order, each in its **own separate terminal**.

1.  **Terminal 1: Start the Market Server**
    This process reads the data files and begins broadcasting the market simulation.
    ```bash
    python server/server.py
    ```

2.  **Terminal 2: Start the Network Relay**
    This process subscribes to the server and prepares to forward data to clients.
    ```bash
    python relay/relay.py
    ```

3.  **Terminal 3: Start the Client Dashboard**
    This launches the main GUI application, which will connect to the relay and start processing data.
    ```bash
    python clients/dashboard_client.py
    ```

*(**Optional:** To generate fresh data, first run `python data_recorder/data_recorder.py` before starting the server.)*

---

## Project Presentation

The file `HFT_Platform_Analysis.ipynb` is a Jupyter Notebook containing the detailed analysis, benchmarks, and technical breakdown of this project. To view it, run the following command from your terminal:
```bash
jupyter notebook HFT_Platform_Analysis.ipynb

