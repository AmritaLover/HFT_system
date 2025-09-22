
import asyncio
import websockets
import json
import time
import threading
from typing import Dict, Set
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

class RelayServer:
    """Market data relay and distribution server"""

    def __init__(self, config_file: str = "network_config.json"):
        # Configuration
        self.config = NetworkConfig(config_file)
        server_config = self.config.get_server_config("relay")

        self.host = server_config.get("bind_host", "localhost")
        self.port = server_config["port"]
        self.advertised_host = server_config.get("advertised_host", self.host)

        # Tick logging
        self.tick_logger = TickLogger("RELAY")

        # Connections
        self.clients = {}
        self.client_info = {}
        self.sequence = 0

        # Market data cache
        self.market_data_cache = {}
        self.trade_history = []

        # Stats
        self.stats = {
            'messages_relayed': 0,
            'clients_connected': 0,
            'market_updates': 0,
            'uptime_start': time.time()
        }

        if RICH_AVAILABLE:
            self.console = Console()

        # Log startup
        self.tick_logger.log_tick(
            event_type="RELAY_STARTUP",
            deployment_mode=self.config.config["deployment_mode"],
            bind_host=self.host,
            port=self.port
        )

        print(f" Relay Server initialized")
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
            'messages_relayed': 0,
            'last_activity': time.time()
        }

        self.stats['clients_connected'] = len(self.clients)
        print(f"🔗 Relay client connected: {client_id}")

        
        await self.send_market_snapshot(client_id)

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
        print(f" Relay client disconnected: {client_id}")

    async def process_message(self, client_id, raw_message):
        receive_time = HighResolutionClock.get_timestamp_ns()

        try:
            msg = Message.from_json(raw_message)

            
            self.tick_logger.log_tick(
                event_type="MESSAGE_RECEIVED",
                client_id=client_id,
                msg_type=msg.msg_type,
                sequence=msg.sequence
            )

            
            if client_id in self.client_info:
                self.client_info[client_id]['last_activity'] = time.time()

           
            if msg.msg_type == MessageType.MARKET_DATA_REQUEST:
                await self.handle_market_data_request(client_id, msg)
            elif msg.msg_type == MessageType.TRADE:
                await self.handle_trade_update(client_id, msg)
            elif msg.msg_type == MessageType.ORDER_ADD:
                await self.handle_order_update(client_id, msg)
            elif msg.msg_type == MessageType.HEARTBEAT:
                await self.handle_heartbeat(client_id, msg)

        except Exception as e:
            self.tick_logger.log_tick(
                event_type="MESSAGE_ERROR",
                client_id=client_id,
                error=str(e)
            )

    async def handle_market_data_request(self, client_id, msg):
       
        await self.send_market_snapshot(client_id)

        self.tick_logger.log_tick(
            event_type="MARKET_DATA_SENT",
            client_id=client_id,
            symbols_sent=len(self.market_data_cache)
        )

    async def handle_trade_update(self, client_id, msg):
        
        trade_data = msg.payload
        self.trade_history.append({
            'timestamp': time.time(),
            'data': trade_data
        })

        
        if len(self.trade_history) > 1000:
            self.trade_history.pop(0)

        
        await self.relay_to_all_clients(msg, exclude=client_id)

        self.tick_logger.log_tick(
            event_type="TRADE_RELAYED",
            symbol=trade_data.get('symbol'),
            price=trade_data.get('price'),
            quantity=trade_data.get('quantity'),
            trade_id=trade_data.get('trade_id'),
            recipients=len(self.clients) - 1
        )

        self.stats['market_updates'] += 1

    async def handle_order_update(self, client_id, msg):
        
        order_data = msg.payload
        symbol = order_data.get('symbol')

        if symbol:
            if symbol not in self.market_data_cache:
                self.market_data_cache[symbol] = {'bids': [], 'asks': [], 'last_update': time.time()}

            self.market_data_cache[symbol]['last_update'] = time.time()

        await self.relay_to_all_clients(msg, exclude=client_id)

        self.tick_logger.log_tick(
            event_type="ORDER_RELAYED",
            symbol=symbol,
            side=order_data.get('side'),
            price=order_data.get('price'),
            quantity=order_data.get('quantity'),
            recipients=len(self.clients) - 1
        )

    async def handle_heartbeat(self, client_id, msg):
        response = Message(
            msg_type=MessageType.HEARTBEAT_ACK,
            timestamp_ns=HighResolutionClock.get_timestamp_ns(),
            sequence=self.get_next_sequence(),
            payload={'relay_time': time.time()}
        )
        await self.send_to_client(client_id, response)

    async def send_market_snapshot(self, client_id):
        
        for symbol, data in self.market_data_cache.items():
            snapshot = Message(
                msg_type=MessageType.MARKET_DATA,
                timestamp_ns=HighResolutionClock.get_timestamp_ns(),
                sequence=self.get_next_sequence(),
                payload={
                    'symbol': symbol,
                    'snapshot': data,
                    'last_update': data['last_update']
                }
            )
            await self.send_to_client(client_id, snapshot)

        
        for trade in self.trade_history[-50:]:  
            trade_msg = Message(
                msg_type=MessageType.TRADE,
                timestamp_ns=HighResolutionClock.get_timestamp_ns(),
                sequence=self.get_next_sequence(),
                payload=trade['data']
            )
            await self.send_to_client(client_id, trade_msg)

    async def relay_to_all_clients(self, msg, exclude=None):
        relay_start = HighResolutionClock.get_timestamp_ns()
        relayed_count = 0

        disconnected = []
        for client_id, websocket in self.clients.items():
            if client_id == exclude:
                continue

            try:
                await websocket.send(msg.to_json())
                relayed_count += 1

                if client_id in self.client_info:
                    self.client_info[client_id]['messages_relayed'] += 1

            except:
                disconnected.append(client_id)

        
        for client_id in disconnected:
            await self.cleanup_client(client_id)

        relay_time = (HighResolutionClock.get_timestamp_ns() - relay_start) / 1000

        self.tick_logger.log_tick(
            event_type="RELAY_COMPLETE",
            msg_type=msg.msg_type,
            recipients=relayed_count,
            relay_time_us=relay_time
        )

        self.stats['messages_relayed'] += relayed_count

    async def send_to_client(self, client_id, msg):
        if client_id not in self.clients:
            return

        try:
            await self.clients[client_id].send(msg.to_json())
        except:
            await self.cleanup_client(client_id)

    def display_stats(self):
        while True:
            if RICH_AVAILABLE:
                os.system('cls' if os.name == 'nt' else 'clear')

                table = Table(title=f"🔀 Relay Server - {self.config.config['deployment_mode'].title()}")
                table.add_column("Metric", style="cyan")
                table.add_column("Value", style="green")

                uptime = time.time() - self.stats['uptime_start']
                table.add_row("Uptime", f"{uptime:.1f}s")
                table.add_row("Host:Port", f"{self.host}:{self.port}")
                table.add_row("Connected Clients", str(self.stats['clients_connected']))
                table.add_row("Messages Relayed", str(self.stats['messages_relayed']))
                table.add_row("Market Updates", str(self.stats['market_updates']))
                table.add_row("Cached Symbols", str(len(self.market_data_cache)))
                table.add_row("Trade History", str(len(self.trade_history)))
                table.add_row("Ticks Logged", str(self.tick_logger.get_stats()['total_ticks']))

                if uptime > 0:
                    table.add_row("Relay Rate", f"{self.stats['messages_relayed']/uptime:.1f}/sec")

                self.console.print(table)

                
                if self.client_info:
                    client_table = Table(title=" Connected Clients")
                    client_table.add_column("Client ID", style="cyan")
                    client_table.add_column("IP", style="yellow")
                    client_table.add_column("Connected", style="green")
                    client_table.add_column("Messages Relayed", style="blue")

                    for client_id, info in self.client_info.items():
                        duration = time.time() - info['connected_at']
                        client_table.add_row(
                            client_id,
                            info['ip'],
                            f"{duration:.0f}s",
                            str(info['messages_relayed'])
                        )

                    self.console.print(client_table)
            else:
                os.system('cls' if os.name == 'nt' else 'clear')
                uptime = time.time() - self.stats['uptime_start']
                print(f" Relay Server ({self.config.config['deployment_mode']})")
                print(f" {self.host}:{self.port}")
                print(f" Clients: {self.stats['clients_connected']}")
                print(f" Messages Relayed: {self.stats['messages_relayed']}")
                print(f" Ticks: {self.tick_logger.get_stats()['total_ticks']}")
                print(f"⏱ Uptime: {uptime:.1f}s")

            time.sleep(2)

    async def start(self):
        print("\n" + "="*50)
        print(" HFT RELAY SERVER v2.0")
        print("="*50)
        print(f" Mode: {self.config.config['deployment_mode'].upper()}")
        print(f" Binding: {self.host}:{self.port}")
        print(f" CSV Log: {self.tick_logger.csv_filename}")
        print(f" JSON Log: {self.tick_logger.json_filename}")
        print(" Ready to relay market data!")
        print("="*50 + "\n")

        
        stats_thread = threading.Thread(target=self.display_stats, daemon=True)
        stats_thread.start()

        try:
            server = await websockets.serve(self.handle_client, self.host, self.port)

            self.tick_logger.log_tick(
                event_type="RELAY_STARTED",
                host=self.host,
                port=self.port
            )

            print(f" Relay server listening on {self.host}:{self.port}")
            await server.wait_closed()

        except Exception as e:
            print(f" Relay server error: {e}")
            self.tick_logger.log_tick(event_type="RELAY_ERROR", error=str(e))
        finally:
            self.tick_logger.log_tick(event_type="RELAY_SHUTDOWN")

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="HFT Relay Server")
    parser.add_argument("--config", default="network_config.json", help="Config file")
    parser.add_argument("--mode", choices=['localhost', 'network'], help="Deployment mode")

    args = parser.parse_args()

    server = RelayServer(args.config)

    if args.mode:
        if args.mode == "network":
            server.config.switch_to_network_mode()
        else:
            server.config.switch_to_localhost_mode()

    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        print("\n Relay server stopped")
