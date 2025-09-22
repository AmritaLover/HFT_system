
import asyncio
import websockets
import json
import time
import threading
from typing import Dict, Any
import sys
import os

from shared_utils import (
    TickLogger, NetworkConfig, HighResolutionClock,
    Message, MessageType
)

try:
    from rich.console import Console
    from rich.table import Table
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

class SharedDataServer:
    """Shared data and configuration server for the HFT system"""

    def __init__(self, config_file: str = "network_config.json"):

        self.config = NetworkConfig(config_file)
        server_config = self.config.get_server_config("shared")

        self.host = server_config.get("bind_host", "localhost")
        self.port = server_config["port"]
        self.advertised_host = server_config.get("advertised_host", self.host)


        self.tick_logger = TickLogger("SHARED_DATA")


        self.clients = {}
        self.client_info = {}
        self.sequence = 0


        self.shared_data = {
            'system_config': {
                'trading_enabled': True,
                'max_order_size': 1000,
                'symbols': ['AAPL', 'GOOGL', 'MSFT', 'TSLA', 'NVDA'],
                'tick_size': 0.01,
                'system_status': 'ACTIVE'
            },
            'risk_parameters': {
                'max_position': 10000,
                'max_daily_loss': 50000.0,
                'position_limits': {
                    'AAPL': 5000,
                    'GOOGL': 3000,
                    'MSFT': 4000,
                    'TSLA': 2000,
                    'NVDA': 3000
                }
            },
            'market_status': {
                'market_open': True,
                'pre_market': False,
                'after_hours': False,
                'trading_halt': False
            },
            'performance_metrics': {
                'total_pnl': 0.0,
                'daily_pnl': 0.0,
                'total_trades': 0,
                'win_rate': 0.0,
                'avg_trade_size': 0.0
            }
        }

        self.stats = {
            'data_requests': 0,
            'data_updates': 0,
            'clients_connected': 0,
            'uptime_start': time.time()
        }

        if RICH_AVAILABLE:
            self.console = Console()


        self.tick_logger.log_tick(
            event_type="SHARED_SERVER_STARTUP",
            deployment_mode=self.config.config["deployment_mode"],
            bind_host=self.host,
            port=self.port,
            data_categories=len(self.shared_data)
        )

        print(f" Shared Data Server initialized")
        print(f" Mode: {self.config.config['deployment_mode']}")
        print(f" Binding to: {self.host}:{self.port}")
        print(f" Logging to: {self.tick_logger.csv_filename}")

    def get_next_sequence(self):
        self.sequence += 1
        return self.sequence

    async def handle_client(self, websocket, path):
        client_address = websocket.remote_address
        client_id = f"{client_address[0]}:{client_address[1]}"

        self.tick_logger.log_tick(
            event_type="CLIENT_CONNECT",
            client_id=client_id,
            client_ip=client_address[0]
        )

        self.clients[client_id] = websocket
        self.client_info[client_id] = {
            'ip': client_address[0],
            'connected_at': time.time(),
            'data_requests': 0,
            'data_updates': 0,
            'last_activity': time.time()
        }

        self.stats['clients_connected'] = len(self.clients)
        print(f" Shared data client connected: {client_id}")


        welcome = Message(
            msg_type="SYSTEM_STATUS",
            timestamp_ns=HighResolutionClock.get_timestamp_ns(),
            sequence=self.get_next_sequence(),
            payload={
                'system_status': self.shared_data['system_config']['system_status'],
                'server_time': time.time(),
                'data_categories': list(self.shared_data.keys())
            }
        )
        await self.send_to_client(client_id, welcome)

        try:
            async for message in websocket:
                await self.process_message(client_id, message)
        except websockets.exceptions.ConnectionClosed:
            self.tick_logger.log_tick(
                event_type="CLIENT_DISCONNECT",
                client_id=client_id,
                session_duration=time.time() - self.client_info[client_id]['connected_at']
            )
        finally:
            await self.cleanup_client(client_id)

    async def cleanup_client(self, client_id):
        if client_id in self.clients:
            del self.clients[client_id]
        if client_id in self.client_info:
            del self.client_info[client_id]

        self.stats['clients_connected'] = len(self.clients)
        print(f" Shared data client disconnected: {client_id}")

    async def process_message(self, client_id, raw_message):
        receive_time = HighResolutionClock.get_timestamp_ns()

        try:
            msg = Message.from_json(raw_message)


            self.tick_logger.log_tick(
                event_type="DATA_REQUEST_RECEIVED",
                client_id=client_id,
                msg_type=msg.msg_type,
                sequence=msg.sequence
            )


            if client_id in self.client_info:
                self.client_info[client_id]['last_activity'] = time.time()


            if msg.msg_type == "GET_SHARED_DATA":
                await self.handle_get_data(client_id, msg)
            elif msg.msg_type == "UPDATE_SHARED_DATA":
                await self.handle_update_data(client_id, msg)
            elif msg.msg_type == "GET_SYSTEM_CONFIG":
                await self.handle_get_config(client_id, msg)
            elif msg.msg_type == "UPDATE_SYSTEM_CONFIG":
                await self.handle_update_config(client_id, msg)
            elif msg.msg_type == "GET_RISK_PARAMS":
                await self.handle_get_risk_params(client_id, msg)
            elif msg.msg_type == "UPDATE_PERFORMANCE":
                await self.handle_update_performance(client_id, msg)
            elif msg.msg_type == MessageType.HEARTBEAT:
                await self.handle_heartbeat(client_id, msg)

        except Exception as e:
            self.tick_logger.log_tick(
                event_type="DATA_REQUEST_ERROR",
                client_id=client_id,
                error=str(e)
            )

    async def handle_get_data(self, client_id, msg):
        category = msg.payload.get('category', 'all')

        if category == 'all':
            data_to_send = self.shared_data
        elif category in self.shared_data:
            data_to_send = {category: self.shared_data[category]}
        else:
            data_to_send = {'error': f'Unknown category: {category}'}

        response = Message(
            msg_type="SHARED_DATA_RESPONSE",
            timestamp_ns=HighResolutionClock.get_timestamp_ns(),
            sequence=self.get_next_sequence(),
            payload={
                'category': category,
                'data': data_to_send,
                'timestamp': time.time()
            }
        )

        await self.send_to_client(client_id, response)

        if client_id in self.client_info:
            self.client_info[client_id]['data_requests'] += 1

        self.tick_logger.log_tick(
            event_type="DATA_SENT",
            client_id=client_id,
            category=category,
            data_size=len(str(data_to_send))
        )

        self.stats['data_requests'] += 1

    async def handle_update_data(self, client_id, msg):
        category = msg.payload.get('category')
        updates = msg.payload.get('updates', {})

        if category not in self.shared_data:
            await self.send_error(client_id, f"Unknown category: {category}")
            return


        old_data = self.shared_data[category].copy()
        for key, value in updates.items():
            if key in self.shared_data[category]:
                self.shared_data[category][key] = value


        response = Message(
            msg_type="UPDATE_CONFIRMATION",
            timestamp_ns=HighResolutionClock.get_timestamp_ns(),
            sequence=self.get_next_sequence(),
            payload={
                'category': category,
                'updates_applied': updates,
                'timestamp': time.time()
            }
        )

        await self.send_to_client(client_id, response)


        await self.broadcast_update(category, updates, exclude=client_id)

        if client_id in self.client_info:
            self.client_info[client_id]['data_updates'] += 1

        self.tick_logger.log_tick(
            event_type="DATA_UPDATED",
            client_id=client_id,
            category=category,
            updates_count=len(updates),
            broadcast_recipients=len(self.clients) - 1
        )

        self.stats['data_updates'] += 1

    async def handle_get_config(self, client_id, msg):
        response = Message(
            msg_type="SYSTEM_CONFIG_RESPONSE",
            timestamp_ns=HighResolutionClock.get_timestamp_ns(),
            sequence=self.get_next_sequence(),
            payload={
                'config': self.shared_data['system_config'],
                'timestamp': time.time()
            }
        )
        await self.send_to_client(client_id, response)

    async def handle_update_config(self, client_id, msg):
        updates = msg.payload.get('updates', {})

        for key, value in updates.items():
            if key in self.shared_data['system_config']:
                old_value = self.shared_data['system_config'][key]
                self.shared_data['system_config'][key] = value

                self.tick_logger.log_tick(
                    event_type="CONFIG_UPDATED",
                    client_id=client_id,
                    config_key=key,
                    old_value=old_value,
                    new_value=value
                )


        await self.broadcast_config_update(updates, exclude=client_id)

    async def handle_get_risk_params(self, client_id, msg):
        response = Message(
            msg_type="RISK_PARAMS_RESPONSE",
            timestamp_ns=HighResolutionClock.get_timestamp_ns(),
            sequence=self.get_next_sequence(),
            payload={
                'risk_params': self.shared_data['risk_parameters'],
                'timestamp': time.time()
            }
        )
        await self.send_to_client(client_id, response)

    async def handle_update_performance(self, client_id, msg):
        metrics = msg.payload.get('metrics', {})

        for key, value in metrics.items():
            if key in self.shared_data['performance_metrics']:
                self.shared_data['performance_metrics'][key] = value

        self.tick_logger.log_tick(
            event_type="PERFORMANCE_UPDATED",
            client_id=client_id,
            metrics_updated=list(metrics.keys()),
            total_pnl=self.shared_data['performance_metrics'].get('total_pnl', 0)
        )

    async def handle_heartbeat(self, client_id, msg):
        response = Message(
            msg_type=MessageType.HEARTBEAT_ACK,
            timestamp_ns=HighResolutionClock.get_timestamp_ns(),
            sequence=self.get_next_sequence(),
            payload={
                'server_time': time.time(),
                'system_status': self.shared_data['system_config']['system_status']
            }
        )
        await self.send_to_client(client_id, response)

    async def broadcast_update(self, category, updates, exclude=None):
        broadcast_msg = Message(
            msg_type="DATA_BROADCAST",
            timestamp_ns=HighResolutionClock.get_timestamp_ns(),
            sequence=self.get_next_sequence(),
            payload={
                'category': category,
                'updates': updates,
                'timestamp': time.time()
            }
        )

        await self.broadcast_to_all(broadcast_msg, exclude)

    async def broadcast_config_update(self, updates, exclude=None):
        broadcast_msg = Message(
            msg_type="CONFIG_BROADCAST",
            timestamp_ns=HighResolutionClock.get_timestamp_ns(),
            sequence=self.get_next_sequence(),
            payload={
                'config_updates': updates,
                'timestamp': time.time()
            }
        )

        await self.broadcast_to_all(broadcast_msg, exclude)

    async def broadcast_to_all(self, msg, exclude=None):
        broadcast_start = HighResolutionClock.get_timestamp_ns()
        sent_count = 0

        disconnected = []
        for client_id, websocket in self.clients.items():
            if client_id == exclude:
                continue

            try:
                await websocket.send(msg.to_json())
                sent_count += 1
            except:
                disconnected.append(client_id)

        
        for client_id in disconnected:
            await self.cleanup_client(client_id)

        broadcast_time = (HighResolutionClock.get_timestamp_ns() - broadcast_start) / 1000

        self.tick_logger.log_tick(
            event_type="BROADCAST_COMPLETE",
            msg_type=msg.msg_type,
            recipients=sent_count,
            broadcast_time_us=broadcast_time
        )

    async def send_to_client(self, client_id, msg):
        if client_id not in self.clients:
            return

        try:
            await self.clients[client_id].send(msg.to_json())
        except:
            await self.cleanup_client(client_id)

    async def send_error(self, client_id, error_msg):
        error = Message(
            msg_type="ERROR",
            timestamp_ns=HighResolutionClock.get_timestamp_ns(),
            sequence=self.get_next_sequence(),
            payload={'error': error_msg}
        )
        await self.send_to_client(client_id, error)

    def display_stats(self):
        while True:
            if RICH_AVAILABLE:
                os.system('cls' if os.name == 'nt' else 'clear')

                table = Table(title=f" Shared Data Server - {self.config.config['deployment_mode'].title()}")
                table.add_column("Metric", style="cyan")
                table.add_column("Value", style="green")

                uptime = time.time() - self.stats['uptime_start']
                table.add_row("Uptime", f"{uptime:.1f}s")
                table.add_row("Host:Port", f"{self.host}:{self.port}")
                table.add_row("Connected Clients", str(self.stats['clients_connected']))
                table.add_row("Data Requests", str(self.stats['data_requests']))
                table.add_row("Data Updates", str(self.stats['data_updates']))
                table.add_row("Data Categories", str(len(self.shared_data)))
                table.add_row("System Status", self.shared_data['system_config']['system_status'])
                table.add_row("Trading Enabled", str(self.shared_data['system_config']['trading_enabled']))
                table.add_row("Total P&L", f"${self.shared_data['performance_metrics']['total_pnl']:.2f}")
                table.add_row("Ticks Logged", str(self.tick_logger.get_stats()['total_ticks']))

                self.console.print(table)

                # Shared data summary
                data_table = Table(title=" Shared Data Categories")
                data_table.add_column("Category", style="cyan")
                data_table.add_column("Keys", style="green")
                data_table.add_column("Last Modified", style="yellow")

                for category, data in self.shared_data.items():
                    data_table.add_row(
                        category,
                        str(len(data)),
                        "Recently"  
                    )

                self.console.print(data_table)

            else:
                os.system('cls' if os.name == 'nt' else 'clear')
                uptime = time.time() - self.stats['uptime_start']
                print(f" Shared Data Server ({self.config.config['deployment_mode']})")
                print(f" {self.host}:{self.port}")
                print(f" Clients: {self.stats['clients_connected']}")
                print(f" Data Requests: {self.stats['data_requests']}")
                print(f" Data Updates: {self.stats['data_updates']}")
                print(f" Categories: {len(self.shared_data)}")
                print(f" P&L: ${self.shared_data['performance_metrics']['total_pnl']:.2f}")
                print(f"⏱ Uptime: {uptime:.1f}s")

            time.sleep(2)

    async def start(self):
        print("\n" + "="*50)
        print(" HFT SHARED DATA SERVER v2.0")
        print("="*50)
        print(f" Mode: {self.config.config['deployment_mode'].upper()}")
        print(f" Binding: {self.host}:{self.port}")
        print(f" CSV Log: {self.tick_logger.csv_filename}")
        print(f" JSON Log: {self.tick_logger.json_filename}")
        print(f" Data Categories: {', '.join(self.shared_data.keys())}")
        print(" Ready to serve shared data!")
        print("="*50 + "\n")

        
        stats_thread = threading.Thread(target=self.display_stats, daemon=True)
        stats_thread.start()

        try:
            server = await websockets.serve(self.handle_client, self.host, self.port)

            self.tick_logger.log_tick(
                event_type="SHARED_SERVER_STARTED",
                host=self.host,
                port=self.port
            )

            print(f" Shared data server listening on {self.host}:{self.port}")
            await server.wait_closed()

        except Exception as e:
            print(f" Shared data server error: {e}")
            self.tick_logger.log_tick(event_type="SHARED_SERVER_ERROR", error=str(e))
        finally:
            self.tick_logger.log_tick(event_type="SHARED_SERVER_SHUTDOWN")

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="HFT Shared Data Server")
    parser.add_argument("--config", default="network_config.json", help="Config file")
    parser.add_argument("--mode", choices=['localhost', 'network'], help="Deployment mode")

    args = parser.parse_args()

    server = SharedDataServer(args.config)

    if args.mode:
        if args.mode == "network":
            server.config.switch_to_network_mode()
        else:
            server.config.switch_to_localhost_mode()

    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        print("\n Shared data server stopped")
