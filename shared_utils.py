
import time
import json
import csv
import os
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Dict, List, Any, Optional
import threading
from collections import deque

@dataclass
class TickLog:
    """Represents a single tick event in the system"""
    timestamp_ns: int
    timestamp_human: str
    component: str
    event_type: str
    symbol: Optional[str]
    price: Optional[float]
    quantity: Optional[int]
    order_id: Optional[str]
    client_id: Optional[str]
    latency_us: Optional[float]
    additional_data: Dict[str, Any]

class TickLogger:
    """Centralized tick logging system with CSV and JSON output"""

    def __init__(self, component_name: str, log_dir: str = "logs"):
        self.component_name = component_name
        self.log_dir = log_dir
        self.tick_buffer = deque(maxlen=10000)  # Keep last 10k ticks in memory
        self.csv_file = None
        self.json_file = None
        self.lock = threading.Lock()

        # Create logs directory
        os.makedirs(log_dir, exist_ok=True)

        # Initialize files
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.csv_filename = f"{log_dir}/{component_name}_{timestamp}.csv"
        self.json_filename = f"{log_dir}/{component_name}_{timestamp}.json"

        # Initialize CSV file
        self.init_csv()

        # Start background thread for JSON writing
        self.json_buffer = []
        self.json_thread = threading.Thread(target=self._json_writer, daemon=True)
        self.json_thread.start()

    def init_csv(self):
        """Initialize CSV file with headers"""
        with open(self.csv_filename, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'timestamp_ns', 'timestamp_human', 'component', 'event_type',
                'symbol', 'price', 'quantity', 'order_id', 'client_id', 
                'latency_us', 'additional_data'
            ])

    def log_tick(self, event_type: str, symbol: str = None, price: float = None, 
                 quantity: int = None, order_id: str = None, client_id: str = None,
                 latency_us: float = None, **additional_data):
        """Log a tick event"""

        timestamp_ns = time.time_ns()
        timestamp_human = datetime.now().isoformat()

        tick = TickLog(
            timestamp_ns=timestamp_ns,
            timestamp_human=timestamp_human,
            component=self.component_name,
            event_type=event_type,
            symbol=symbol,
            price=price,
            quantity=quantity,
            order_id=order_id,
            client_id=client_id,
            latency_us=latency_us,
            additional_data=additional_data
        )

        with self.lock:
            # Add to memory buffer
            self.tick_buffer.append(tick)

            # Write to CSV immediately (for real-time analysis)
            self._write_csv_tick(tick)

            # Add to JSON buffer (written periodically)
            self.json_buffer.append(asdict(tick))

    def _write_csv_tick(self, tick: TickLog):
        """Write single tick to CSV file"""
        with open(self.csv_filename, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                tick.timestamp_ns,
                tick.timestamp_human,
                tick.component,
                tick.event_type,
                tick.symbol,
                tick.price,
                tick.quantity,
                tick.order_id,
                tick.client_id,
                tick.latency_us,
                json.dumps(tick.additional_data) if tick.additional_data else ''
            ])

    def _json_writer(self):
        """Background thread to write JSON logs periodically"""
        while True:
            time.sleep(5)  # Write every 5 seconds
            if self.json_buffer:
                with self.lock:
                    buffer_copy = self.json_buffer.copy()
                    self.json_buffer.clear()

                # Append to JSON file
                if os.path.exists(self.json_filename):
                    with open(self.json_filename, 'r') as f:
                        try:
                            existing_data = json.load(f)
                        except:
                            existing_data = []
                else:
                    existing_data = []

                existing_data.extend(buffer_copy)

                with open(self.json_filename, 'w') as f:
                    json.dump(existing_data, f, indent=2)

    def get_recent_ticks(self, count: int = 100) -> List[TickLog]:
        """Get recent ticks from memory buffer"""
        with self.lock:
            return list(self.tick_buffer)[-count:]

    def get_stats(self) -> Dict[str, Any]:
        """Get logging statistics"""
        with self.lock:
            return {
                'component': self.component_name,
                'total_ticks': len(self.tick_buffer),
                'csv_file': self.csv_filename,
                'json_file': self.json_filename,
                'buffer_size': len(self.tick_buffer)
            }

class NetworkConfig:
    """Network configuration that works for both localhost and multi-node deployment"""

    def __init__(self, config_file: str = "network_config.json"):
        self.config_file = config_file
        self.load_config()

    def load_config(self):
        """Load network configuration"""
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r') as f:
                self.config = json.load(f)
        else:
            self.create_default_config()

    def create_default_config(self):
        """Create default localhost configuration"""
        self.config = {
            "deployment_mode": "localhost",  # localhost or network
            "servers": {
                "exchange": {
                    "host": "localhost",
                    "port": 8001,
                    "bind_host": "localhost"  # Use localhost for single machine
                },
                "relay": {
                    "host": "localhost", 
                    "port": 8002,
                    "bind_host": "localhost"
                },
                "shared": {
                    "host": "localhost",
                    "port": 8003,
                    "bind_host": "localhost"
                }
            },
            "network_deployment": {
                "auto_detect_ip": True,
                "server_ip": "192.168.1.100",  # Change this for network deployment
                "bind_all_interfaces": False   # Set to true for network deployment
            },
            "logging": {
                "enable_tick_logging": True,
                "log_directory": "logs",
                "log_level": "INFO"
            }
        }
        self.save_config()

    def save_config(self):
        """Save configuration to file"""
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent=2)

    def get_server_config(self, server_name: str) -> Dict[str, Any]:
        """Get configuration for a specific server"""
        server_config = self.config["servers"][server_name].copy()

        # If network deployment mode, update configuration
        if self.config["deployment_mode"] == "network":
            network_config = self.config["network_deployment"]

            if network_config["auto_detect_ip"]:
                server_ip = self.get_local_ip()
            else:
                server_ip = network_config["server_ip"]

            # For servers, bind to appropriate interface
            if network_config["bind_all_interfaces"]:
                server_config["bind_host"] = "0.0.0.0"  # Accept from any IP
                server_config["advertised_host"] = server_ip  # But advertise real IP
            else:
                server_config["bind_host"] = server_ip
                server_config["advertised_host"] = server_ip

            # For clients connecting to servers
            server_config["host"] = server_ip

        return server_config

    def get_local_ip(self) -> str:
        """Get local IP address"""
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except:
            return "localhost"

    def switch_to_network_mode(self, server_ip: str = None):
        """Switch configuration to network deployment mode"""
        self.config["deployment_mode"] = "network"
        self.config["network_deployment"]["bind_all_interfaces"] = True

        if server_ip:
            self.config["network_deployment"]["server_ip"] = server_ip
            self.config["network_deployment"]["auto_detect_ip"] = False

        # Update all server configurations
        for server_name in self.config["servers"]:
            if server_ip:
                self.config["servers"][server_name]["host"] = server_ip
            self.config["servers"][server_name]["bind_host"] = "0.0.0.0"

        self.save_config()
        print(f" Switched to network mode with server IP: {server_ip or 'auto-detect'}")

    def switch_to_localhost_mode(self):
        """Switch configuration back to localhost mode"""
        self.config["deployment_mode"] = "localhost"

        # Update all server configurations
        for server_name in self.config["servers"]:
            self.config["servers"][server_name]["host"] = "localhost"
            self.config["servers"][server_name]["bind_host"] = "localhost"

        self.save_config()
        print(" Switched to localhost mode")

class HighResolutionClock:
    """High-resolution timestamp utilities"""

    @staticmethod
    def get_timestamp_ns() -> int:
        """Get high-resolution timestamp in nanoseconds"""
        return time.time_ns()

    @staticmethod
    def get_timestamp_us() -> float:
        """Get timestamp in microseconds"""
        return time.time() * 1_000_000

    @staticmethod 
    def ns_to_human(timestamp_ns: int) -> str:
        """Convert nanosecond timestamp to human readable"""
        return datetime.fromtimestamp(timestamp_ns / 1_000_000_000).isoformat()

class LatencyTracker:
    """Track latency between different system events"""

    def __init__(self):
        self.traces = {}
        self.completed_traces = deque(maxlen=1000)

    def start_trace(self, trace_id: str, component: str, event: str):
        """Start tracking a new trace"""
        self.traces[trace_id] = {
            'start_time_ns': time.time_ns(),
            'start_component': component,
            'start_event': event,
            'checkpoints': []
        }

    def add_checkpoint(self, trace_id: str, component: str, event: str):
        """Add a checkpoint to an existing trace"""
        if trace_id in self.traces:
            current_time_ns = time.time_ns()
            start_time = self.traces[trace_id]['start_time_ns']

            checkpoint = {
                'timestamp_ns': current_time_ns,
                'component': component,
                'event': event,
                'elapsed_us': (current_time_ns - start_time) / 1000
            }

            self.traces[trace_id]['checkpoints'].append(checkpoint)

    def end_trace(self, trace_id: str, component: str, event: str) -> float:
        """End a trace and return total latency in microseconds"""
        if trace_id not in self.traces:
            return 0.0

        end_time_ns = time.time_ns()
        start_time_ns = self.traces[trace_id]['start_time_ns']
        total_latency_us = (end_time_ns - start_time_ns) / 1000

        # Add final checkpoint
        self.add_checkpoint(trace_id, component, event)

        # Move to completed traces
        completed_trace = self.traces[trace_id].copy()
        completed_trace['end_time_ns'] = end_time_ns
        completed_trace['total_latency_us'] = total_latency_us

        self.completed_traces.append(completed_trace)
        del self.traces[trace_id]

        return total_latency_us

    def get_statistics(self) -> Dict[str, float]:
        """Get latency statistics from completed traces"""
        if not self.completed_traces:
            return {}

        latencies = [trace['total_latency_us'] for trace in self.completed_traces]
        latencies.sort()

        return {
            'count': len(latencies),
            'min_us': min(latencies),
            'max_us': max(latencies),
            'mean_us': sum(latencies) / len(latencies),
            'p50_us': latencies[len(latencies) // 2],
            'p95_us': latencies[int(len(latencies) * 0.95)],
            'p99_us': latencies[int(len(latencies) * 0.99)]
        }

# Message types and data structures
class MessageType:
    # Order messages
    NEW_ORDER = "NEW_ORDER"
    CANCEL_ORDER = "CANCEL_ORDER"
    ORDER_ACK = "ORDER_ACK"
    ORDER_REJECT = "ORDER_REJECT"
    CANCEL_ACK = "CANCEL_ACK"
    FILL = "FILL"

    # Market data messages
    MARKET_DATA_REQUEST = "MARKET_DATA_REQUEST"
    MARKET_DATA = "MARKET_DATA"
    ORDER_ADD = "ORDER_ADD"
    ORDER_DELETE = "ORDER_DELETE"
    TRADE = "TRADE"

    # System messages
    HEARTBEAT = "HEARTBEAT"
    HEARTBEAT_ACK = "HEARTBEAT_ACK"
    SERVER_INFO = "SERVER_INFO"
    ERROR = "ERROR"

@dataclass
class Message:
    """Standard message format for all components"""
    msg_type: str
    timestamp_ns: int
    sequence: int
    payload: Dict[str, Any]
    trace_id: Optional[str] = None

    def to_json(self) -> str:
        """Serialize message to JSON"""
        return json.dumps({
            'msg_type': self.msg_type,
            'timestamp_ns': self.timestamp_ns,
            'sequence': self.sequence,
            'payload': self.payload,
            'trace_id': self.trace_id
        })

    @classmethod
    def from_json(cls, json_str: str):
        """Deserialize message from JSON"""
        data = json.loads(json_str)
        return cls(
            msg_type=data['msg_type'],
            timestamp_ns=data['timestamp_ns'],
            sequence=data['sequence'],
            payload=data['payload'],
            trace_id=data.get('trace_id')
        )

print(" Created shared utilities module")
