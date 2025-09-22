import asyncio
import websockets
import json
import time
import threading
from typing import Dict, List
from dataclasses import dataclass
import sys
import os


from shared_utils import (
    TickLogger, NetworkConfig, HighResolutionClock, 
    LatencyTracker, Message, MessageType
)


try:
    from rich.console import Console
    from rich.table import Table
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

@dataclass
class Order:
    order_id: str
    client_id: str
    symbol: str
    side: str
    price: float
    quantity: int
    timestamp_ns: int

class ExchangeServer:
    def __init__(self, config_file: str = "network_config.json"):
        
        self.config = NetworkConfig(config_file)
        server_config = self.config.get_server_config("exchange")

        self.host = server_config.get("bind_host", "localhost")
        self.port = server_config["port"]
        self.advertised_host = server_config.get("advertised_host", self.host)

        
        self.tick_logger = TickLogger("EXCHANGE")
        self.latency_tracker = LatencyTracker()

        
        self.clients = {}
        self.client_info = {}

        
        self.symbols = ["AAPL", "GOOGL", "MSFT", "TSLA", "NVDA"]
        self.order_books = {}
        for symbol in self.symbols:
            self.order_books[symbol] = {"BID": [], "ASK": []}

        self.sequence = 0
        self.stats = {
            'messages_sent': 0,
            'orders_received': 0,
            'trades_executed': 0,
            'active_connections': 0,
            'uptime_start': time.time()
        }

        if RICH_AVAILABLE:
            self.console = Console()

        
        self.tick_logger.log_tick(
            event_type="SERVER_STARTUP",
            deployment_mode=self.config.config["deployment_mode"],
            bind_host=self.host,
            port=self.port,
            symbols_count=len(self.symbols)
        )

        print(f" Exchange Server initialized")
        print(f" Mode: {self.config.config['deployment_mode']}")
        print(f" Binding to: {self.host}:{self.port}")
        print(f" CSV Log: {self.tick_logger.csv_filename}")
        print(f" JSON Log: {self.tick_logger.json_filename}")

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
            'messages_received': 0,
            'orders_sent': 0
        }

        self.stats['active_connections'] = len(self.clients)
        print(f" Client connected: {client_id}")

        
        welcome = Message(
            msg_type=MessageType.SERVER_INFO,
            timestamp_ns=HighResolutionClock.get_timestamp_ns(),
            sequence=self.get_next_sequence(),
            payload={
                'symbols': self.symbols,
                'client_id': client_id,
                'server_time': time.time()
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
        self.stats['active_connections'] = len(self.clients)
        print(f" Client disconnected: {client_id}")

    async def process_message(self, client_id, raw_message):
        receive_time = HighResolutionClock.get_timestamp_ns()

        try:
            msg = Message.from_json(raw_message)

            
            self.tick_logger.log_tick(
                event_type="MESSAGE_RECEIVED",
                client_id=client_id,
                msg_type=msg.msg_type,
                sequence=msg.sequence,
                processing_latency_us=(receive_time - msg.timestamp_ns) / 1000
            )

            
            if client_id in self.client_info:
                self.client_info[client_id]['messages_received'] += 1

            
            if msg.msg_type == MessageType.NEW_ORDER:
                await self.handle_new_order(client_id, msg)
            elif msg.msg_type == MessageType.CANCEL_ORDER:
                await self.handle_cancel_order(client_id, msg)
            elif msg.msg_type == MessageType.HEARTBEAT:
                await self.handle_heartbeat(client_id, msg)
            elif msg.msg_type == MessageType.MARKET_DATA_REQUEST:
                await self.handle_market_data_request(client_id, msg)

            self.stats['orders_received'] += 1

        except Exception as e:
            self.tick_logger.log_tick(
                event_type="MESSAGE_ERROR",
                client_id=client_id,
                error=str(e)
            )

    async def handle_heartbeat(self, client_id, msg):
        response = Message(
            msg_type=MessageType.HEARTBEAT_ACK,
            timestamp_ns=HighResolutionClock.get_timestamp_ns(),
            sequence=self.get_next_sequence(),
            payload={'original_timestamp': msg.timestamp_ns}
        )
        await self.send_to_client(client_id, response)

    async def handle_market_data_request(self, client_id, msg):
        for symbol in self.symbols:
            book = self.order_books[symbol]
            best_bid = max(book["BID"], key=lambda x: x.price) if book["BID"] else None
            best_ask = min(book["ASK"], key=lambda x: x.price) if book["ASK"] else None

            market_data = Message(
                msg_type=MessageType.MARKET_DATA,
                timestamp_ns=HighResolutionClock.get_timestamp_ns(),
                sequence=self.get_next_sequence(),
                payload={
                    'symbol': symbol,
                    'best_bid': {'price': best_bid.price, 'qty': best_bid.quantity} if best_bid else None,
                    'best_ask': {'price': best_ask.price, 'qty': best_ask.quantity} if best_ask else None,
                    'bid_count': len(book["BID"]),
                    'ask_count': len(book["ASK"])
                }
            )
            await self.send_to_client(client_id, market_data)

    async def handle_new_order(self, client_id, msg):
        processing_start = HighResolutionClock.get_timestamp_ns()
        payload = msg.payload

        
        self.tick_logger.log_tick(
            event_type="ORDER_RECEIVED",
            client_id=client_id,
            symbol=payload.get('symbol'),
            side=payload.get('side'),
            price=payload.get('price'),
            quantity=payload.get('quantity')
        )

        
        required = ['symbol', 'side', 'price', 'quantity']
        for field in required:
            if field not in payload:
                await self.send_error(client_id, f"Missing {field}")
                return

        symbol = payload['symbol']
        if symbol not in self.order_books:
            await self.send_error(client_id, f"Unknown symbol: {symbol}")
            return

        
        order = Order(
            order_id=f"ORD{self.sequence:08d}",
            client_id=client_id,
            symbol=symbol,
            side=payload['side'],
            price=float(payload['price']),
            quantity=int(payload['quantity']),
            timestamp_ns=HighResolutionClock.get_timestamp_ns()
        )

        
        self.order_books[symbol][order.side].append(order)

        
        self.tick_logger.log_tick(
            event_type="ORDER_ACCEPTED",
            client_id=client_id,
            order_id=order.order_id,
            symbol=symbol,
            side=order.side,
            price=order.price,
            quantity=order.quantity
        )

        
        ack = Message(
            msg_type=MessageType.ORDER_ACK,
            timestamp_ns=HighResolutionClock.get_timestamp_ns(),
            sequence=self.get_next_sequence(),
            payload={
                'order_id': order.order_id,
                'status': 'ACCEPTED',
                'symbol': symbol,
                'side': order.side,
                'price': order.price,
                'quantity': order.quantity
            }
        )
        await self.send_to_client(client_id, ack)

        
        await self.broadcast_order_add(order)
        matches = await self.match_orders(symbol)

        processing_time = (HighResolutionClock.get_timestamp_ns() - processing_start) / 1000

        
        self.tick_logger.log_tick(
            event_type="ORDER_PROCESSING_COMPLETE",
            order_id=order.order_id,
            processing_time_us=processing_time,
            matches_found=matches
        )

    async def handle_cancel_order(self, client_id, msg):
        order_id = msg.payload.get('order_id')

        
        order_found = False
        for symbol in self.order_books:
            for side in ["BID", "ASK"]:
                for order in self.order_books[symbol][side]:
                    if order.order_id == order_id and order.client_id == client_id:
                        self.order_books[symbol][side].remove(order)
                        order_found = True
                        break
                if order_found:
                    break
            if order_found:
                break

        status = "CANCELLED" if order_found else "NOT_FOUND"

        
        self.tick_logger.log_tick(
            event_type="ORDER_CANCELLED" if order_found else "CANCEL_FAILED",
            client_id=client_id,
            order_id=order_id
        )

        
        response = Message(
            msg_type=MessageType.CANCEL_ACK,
            timestamp_ns=HighResolutionClock.get_timestamp_ns(),
            sequence=self.get_next_sequence(),
            payload={'order_id': order_id, 'status': status}
        )
        await self.send_to_client(client_id, response)

    async def match_orders(self, symbol):
        matching_start = HighResolutionClock.get_timestamp_ns()

        bids = sorted(self.order_books[symbol]["BID"], key=lambda x: x.price, reverse=True)
        asks = sorted(self.order_books[symbol]["ASK"], key=lambda x: x.price)

        matches = 0

        while bids and asks and bids[0].price >= asks[0].price:
            bid, ask = bids[0], asks[0]

            trade_qty = min(bid.quantity, ask.quantity)
            trade_price = ask.price
            trade_id = f"TRD{self.get_next_sequence():08d}"

            
            self.tick_logger.log_tick(
                event_type="TRADE_EXECUTED",
                trade_id=trade_id,
                symbol=symbol,
                price=trade_price,
                quantity=trade_qty,
                bid_order_id=bid.order_id,
                ask_order_id=ask.order_id,
                bid_client=bid.client_id,
                ask_client=ask.client_id,
                trade_value=trade_price * trade_qty
            )

            
            await self.send_fill(bid.client_id, bid.order_id, trade_price, trade_qty, 'BUY')
            await self.send_fill(ask.client_id, ask.order_id, trade_price, trade_qty, 'SELL')

            
            trade_msg = Message(
                msg_type=MessageType.TRADE,
                timestamp_ns=HighResolutionClock.get_timestamp_ns(),
                sequence=self.sequence,
                payload={
                    'trade_id': trade_id,
                    'symbol': symbol,
                    'price': trade_price,
                    'quantity': trade_qty,
                    'bid_order_id': bid.order_id,
                    'ask_order_id': ask.order_id
                }
            )
            await self.broadcast_message(trade_msg)

            
            bid.quantity -= trade_qty
            ask.quantity -= trade_qty

            
            if bid.quantity == 0:
                self.order_books[symbol]["BID"].remove(bid)
                bids.remove(bid)
                self.tick_logger.log_tick(event_type="ORDER_FILLED", order_id=bid.order_id, client_id=bid.client_id)

            if ask.quantity == 0:
                self.order_books[symbol]["ASK"].remove(ask)
                asks.remove(ask)
                self.tick_logger.log_tick(event_type="ORDER_FILLED", order_id=ask.order_id, client_id=ask.client_id)

            matches += 1
            self.stats['trades_executed'] += 1

        if matches > 0:
            matching_time = (HighResolutionClock.get_timestamp_ns() - matching_start) / 1000
            self.tick_logger.log_tick(
                event_type="MATCHING_COMPLETE",
                symbol=symbol,
                matches_found=matches,
                matching_time_us=matching_time
            )

        return matches

    async def send_fill(self, client_id, order_id, price, quantity, side):
        fill = Message(
            msg_type=MessageType.FILL,
            timestamp_ns=HighResolutionClock.get_timestamp_ns(),
            sequence=self.get_next_sequence(),
            payload={
                'order_id': order_id,
                'price': price,
                'quantity': quantity,
                'side': side,
                'fill_value': price * quantity
            }
        )
        await self.send_to_client(client_id, fill)

       
        self.tick_logger.log_tick(
            event_type="FILL_SENT",
            client_id=client_id,
            order_id=order_id,
            price=price,
            quantity=quantity,
            side=side
        )

    async def broadcast_order_add(self, order):
        msg = Message(
            msg_type=MessageType.ORDER_ADD,
            timestamp_ns=HighResolutionClock.get_timestamp_ns(),
            sequence=self.get_next_sequence(),
            payload={
                'symbol': order.symbol,
                'side': order.side,
                'price': order.price,
                'quantity': order.quantity,
                'order_id': order.order_id
            }
        )
        await self.broadcast_message(msg)

    async def broadcast_message(self, msg):
        if not self.clients:
            return

        broadcast_start = HighResolutionClock.get_timestamp_ns()
        sent_count = 0

        disconnected = []
        for client_id, websocket in self.clients.items():
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

        self.stats['messages_sent'] += sent_count

    async def send_to_client(self, client_id, msg):
        if client_id not in self.clients:
            return

        try:
            await self.clients[client_id].send(msg.to_json())
            self.stats['messages_sent'] += 1

            
            if msg.msg_type != MessageType.HEARTBEAT_ACK:
                self.tick_logger.log_tick(
                    event_type="MESSAGE_SENT",
                    client_id=client_id,
                    msg_type=msg.msg_type
                )
        except:
            await self.cleanup_client(client_id)

    async def send_error(self, client_id, error_msg):
        error = Message(
            msg_type=MessageType.ERROR,
            timestamp_ns=HighResolutionClock.get_timestamp_ns(),
            sequence=self.get_next_sequence(),
            payload={'error': error_msg}
        )
        await self.send_to_client(client_id, error)

    def display_stats(self):
        while True:
            if RICH_AVAILABLE:
                os.system('cls' if os.name == 'nt' else 'clear')

                table = Table(title=f"🏦 Exchange Server - {self.config.config['deployment_mode'].title()}")
                table.add_column("Metric", style="cyan")
                table.add_column("Value", style="green")

                uptime = time.time() - self.stats['uptime_start']
                table.add_row("Uptime", f"{uptime:.1f}s")
                table.add_row("Host:Port", f"{self.host}:{self.port}")
                table.add_row("Connections", str(self.stats['active_connections']))
                table.add_row("Messages Sent", str(self.stats['messages_sent']))
                table.add_row("Orders", str(self.stats['orders_received']))
                table.add_row("Trades", str(self.stats['trades_executed']))
                table.add_row("Ticks Logged", str(self.tick_logger.get_stats()['total_ticks']))

                if uptime > 0:
                    table.add_row("Msg Rate", f"{self.stats['messages_sent']/uptime:.1f}/sec")

                self.console.print(table)

                
                book_table = Table(title="📊 Order Books")
                book_table.add_column("Symbol", style="cyan")
                book_table.add_column("Bids", style="green")
                book_table.add_column("Asks", style="red")
                book_table.add_column("Best Bid", style="green")
                book_table.add_column("Best Ask", style="red")

                for symbol in self.symbols:
                    book = self.order_books[symbol]
                    bids = len(book["BID"])
                    asks = len(book["ASK"])

                    best_bid = max(book["BID"], key=lambda x: x.price) if book["BID"] else None
                    best_ask = min(book["ASK"], key=lambda x: x.price) if book["ASK"] else None

                    book_table.add_row(
                        symbol,
                        str(bids),
                        str(asks),
                        f"${best_bid.price:.2f}" if best_bid else "-",
                        f"${best_ask.price:.2f}" if best_ask else "-"
                    )

                self.console.print(book_table)

            else:
                os.system('cls' if os.name == 'nt' else 'clear')
                uptime = time.time() - self.stats['uptime_start']
                print(f" Exchange Server ({self.config.config['deployment_mode']})")
                print(f" {self.host}:{self.port}")
                print(f" Connections: {self.stats['active_connections']}")
                print(f" Messages: {self.stats['messages_sent']}")
                print(f" Orders: {self.stats['orders_received']}")
                print(f" Trades: {self.stats['trades_executed']}")
                print(f" Ticks: {self.tick_logger.get_stats()['total_ticks']}")
                print(f" Uptime: {uptime:.1f}s")

            time.sleep(2)

    def print_startup_info(self):
        print("\n" + "="*60)
        print(" HFT EXCHANGE SERVER v2.0 WITH TICK LOGGING")
        print("="*60)
        print(f" Mode: {self.config.config['deployment_mode'].upper()}")
        print(f" Binding: {self.host}:{self.port}")
        print(f" Symbols: {', '.join(self.symbols)}")
        print(f" Logs:")
        print(f" CSV: {self.tick_logger.csv_filename}")
        print(f"  JSON: {self.tick_logger.json_filename}")
        print("="*60)
        print(" Every tick is being logged for lifecycle analysis!")
        print(" Ready for trading!")
        print("="*60 + "\n")

    async def start(self):
        self.print_startup_info()

        
        stats_thread = threading.Thread(target=self.display_stats, daemon=True)
        stats_thread.start()

        try:
            
            server = await websockets.serve(self.handle_client, self.host, self.port)

            self.tick_logger.log_tick(
                event_type="SERVER_STARTED",
                host=self.host,
                port=self.port
            )

            print(f" Server listening on {self.host}:{self.port}")
            await server.wait_closed()

        except Exception as e:
            print(f" Server error: {e}")
            self.tick_logger.log_tick(event_type="SERVER_ERROR", error=str(e))
        finally:
            self.tick_logger.log_tick(event_type="SERVER_SHUTDOWN")

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="HFT Exchange Server")
    parser.add_argument("--config", default="network_config.json", help="Config file")
    parser.add_argument("--mode", choices=['localhost', 'network'], help="Deployment mode")
    parser.add_argument("--server-ip", help="Server IP for network mode")

    args = parser.parse_args()

    server = ExchangeServer(args.config)

    if args.mode == "network":
        server.config.switch_to_network_mode(args.server_ip)
    elif args.mode == "localhost":
        server.config.switch_to_localhost_mode()

    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        print("\n Server stopped by user")
