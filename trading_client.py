
import asyncio
import websockets
import json
import time
import random
import threading
from typing import Dict, List, Optional
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

class TradingClient:
    """Intelligent trading client with comprehensive logging"""

    def __init__(self, client_name: str = "TRADER1", config_file: str = "network_config.json"):
        self.client_name = client_name
        self.config = NetworkConfig(config_file)

        self.exchange_config = self.config.get_server_config("exchange")
        self.relay_config = self.config.get_server_config("relay")
        self.shared_config = self.config.get_server_config("shared")


        self.tick_logger = TickLogger(f"{client_name}_CLIENT")

        self.exchange_ws = None
        self.relay_ws = None
        self.shared_ws = None

        self.sequence = 0
        self.client_id = f"{client_name}_{int(time.time())}"
        self.connected = False
        self.trading_enabled = False


        self.market_data = {}
        self.order_book_cache = {}
        self.trade_history = []


        self.portfolio = {
            'cash': 100000.0,
            'positions': {},   
            'orders': {},      
            'pnl': 0.0,
            'daily_pnl': 0.0
        }


        self.strategy_params = {
            'symbols': ['AAPL', 'GOOGL', 'MSFT', 'TSLA', 'NVDA'],
            'max_position_size': 1000,
            'max_order_size': 100,
            'min_spread': 0.02,
            'trading_frequency': 5.0, 
            'risk_limit': 10000.0
        }

        self.stats = {
            'orders_sent': 0,
            'orders_filled': 0,
            'trades_completed': 0,
            'messages_received': 0,
            'connection_uptime': 0,
            'start_time': time.time()
        }

        if RICH_AVAILABLE:
            self.console = Console()


        self.tick_logger.log_tick(
            event_type="CLIENT_STARTUP",
            client_name=client_name,
            deployment_mode=self.config.config["deployment_mode"],
            starting_cash=self.portfolio['cash'],
            strategy_symbols=len(self.strategy_params['symbols'])
        )

        print(f" Trading Client {client_name} initialized")
        print(f" Mode: {self.config.config['deployment_mode']}")
        print(f" Starting cash: ${self.portfolio['cash']:,.2f}")
        print(f" Logging to: {self.tick_logger.csv_filename}")

    def get_next_sequence(self):
        self.sequence += 1
        return self.sequence

    async def connect_to_servers(self):
        """Connect to all required servers"""
        try:

            exchange_url = f"ws://{self.exchange_config['host']}:{self.exchange_config['port']}"
            self.tick_logger.log_tick(
                event_type="CONNECTING_TO_EXCHANGE",
                url=exchange_url
            )
            self.exchange_ws = await websockets.connect(exchange_url)
            print(f" Connected to Exchange: {exchange_url}")


            relay_url = f"ws://{self.relay_config['host']}:{self.relay_config['port']}"
            self.tick_logger.log_tick(
                event_type="CONNECTING_TO_RELAY",
                url=relay_url
            )
            self.relay_ws = await websockets.connect(relay_url)
            print(f" Connected to Relay: {relay_url}")


            shared_url = f"ws://{self.shared_config['host']}:{self.shared_config['port']}"
            self.tick_logger.log_tick(
                event_type="CONNECTING_TO_SHARED",
                url=shared_url
            )
            self.shared_ws = await websockets.connect(shared_url)
            print(f" Connected to Shared Data: {shared_url}")

            self.connected = True

            self.tick_logger.log_tick(
                event_type="ALL_CONNECTIONS_ESTABLISHED",
                client_id=self.client_id
            )

            return True

        except Exception as e:
            print(f" Connection error: {e}")
            self.tick_logger.log_tick(
                event_type="CONNECTION_ERROR",
                error=str(e)
            )
            return False

    async def initialize_trading(self):
        """Initialize trading session"""
        try:

            config_request = Message(
                msg_type="GET_SYSTEM_CONFIG",
                timestamp_ns=HighResolutionClock.get_timestamp_ns(),
                sequence=self.get_next_sequence(),
                payload={'client_id': self.client_id}
            )
            await self.shared_ws.send(config_request.to_json())


            market_request = Message(
                msg_type=MessageType.MARKET_DATA_REQUEST,
                timestamp_ns=HighResolutionClock.get_timestamp_ns(),
                sequence=self.get_next_sequence(),
                payload={'symbol': 'ALL', 'client_id': self.client_id}
            )
            await self.exchange_ws.send(market_request.to_json())


            await asyncio.sleep(2)

            self.trading_enabled = True

            self.tick_logger.log_tick(
                event_type="TRADING_INITIALIZED",
                client_id=self.client_id,
                trading_enabled=self.trading_enabled
            )

            print(f" {self.client_name} ready to trade!")

        except Exception as e:
            print(f" Trading initialization error: {e}")
            self.tick_logger.log_tick(
                event_type="TRADING_INIT_ERROR",
                error=str(e)
            )

    async def listen_to_exchange(self):
        """Listen to exchange messages"""
        try:
            async for message in self.exchange_ws:
                await self.process_exchange_message(message)
        except Exception as e:
            print(f" Exchange listener error: {e}")
            self.tick_logger.log_tick(
                event_type="EXCHANGE_LISTENER_ERROR",
                error=str(e)
            )

    async def listen_to_relay(self):
        """Listen to relay messages"""
        try:
            async for message in self.relay_ws:
                await self.process_relay_message(message)
        except Exception as e:
            print(f" Relay listener error: {e}")
            self.tick_logger.log_tick(
                event_type="RELAY_LISTENER_ERROR",
                error=str(e)
            )

    async def listen_to_shared(self):
        """Listen to shared data messages"""
        try:
            async for message in self.shared_ws:
                await self.process_shared_message(message)
        except Exception as e:
            print(f" Shared data listener error: {e}")
            self.tick_logger.log_tick(
                event_type="SHARED_LISTENER_ERROR",
                error=str(e)
            )

    async def process_exchange_message(self, raw_message):
        """Process messages from exchange"""
        try:
            msg = Message.from_json(raw_message)
            self.stats['messages_received'] += 1


            self.tick_logger.log_tick(
                event_type="EXCHANGE_MESSAGE_RECEIVED",
                msg_type=msg.msg_type,
                sequence=msg.sequence
            )

            if msg.msg_type == MessageType.ORDER_ACK:
                await self.handle_order_ack(msg)
            elif msg.msg_type == MessageType.FILL:
                await self.handle_fill(msg)
            elif msg.msg_type == MessageType.ORDER_REJECT:
                await self.handle_order_reject(msg)
            elif msg.msg_type == MessageType.MARKET_DATA:
                await self.handle_market_data(msg)
            elif msg.msg_type == MessageType.TRADE:
                await self.handle_trade_update(msg)

        except Exception as e:
            self.tick_logger.log_tick(
                event_type="EXCHANGE_MESSAGE_ERROR",
                error=str(e)
            )

    async def process_relay_message(self, raw_message):
        """Process messages from relay"""
        try:
            msg = Message.from_json(raw_message)

            self.tick_logger.log_tick(
                event_type="RELAY_MESSAGE_RECEIVED",
                msg_type=msg.msg_type
            )


            if msg.msg_type == MessageType.TRADE:
                await self.handle_trade_update(msg)
            elif msg.msg_type == MessageType.ORDER_ADD:
                await self.handle_order_book_update(msg)

        except Exception as e:
            self.tick_logger.log_tick(
                event_type="RELAY_MESSAGE_ERROR",
                error=str(e)
            )

    async def process_shared_message(self, raw_message):
        """Process messages from shared data server"""
        try:
            msg = Message.from_json(raw_message)

            self.tick_logger.log_tick(
                event_type="SHARED_MESSAGE_RECEIVED",
                msg_type=msg.msg_type
            )

            if msg.msg_type == "SYSTEM_CONFIG_RESPONSE":
                self.handle_system_config(msg)
            elif msg.msg_type == "CONFIG_BROADCAST":
                self.handle_config_update(msg)

        except Exception as e:
            self.tick_logger.log_tick(
                event_type="SHARED_MESSAGE_ERROR",
                error=str(e)
            )

    async def handle_order_ack(self, msg):
        """Handle order acknowledgment"""
        payload = msg.payload
        order_id = payload.get('order_id')

        if order_id:
            self.portfolio['orders'][order_id] = {
                'status': 'ACCEPTED',
                'symbol': payload.get('symbol'),
                'side': payload.get('side'),
                'price': payload.get('price'),
                'quantity': payload.get('quantity'),
                'timestamp': time.time()
            }

        self.tick_logger.log_tick(
            event_type="ORDER_ACKNOWLEDGED",
            order_id=order_id,
            symbol=payload.get('symbol'),
            side=payload.get('side'),
            price=payload.get('price'),
            quantity=payload.get('quantity')
        )

    async def handle_fill(self, msg):
        """Handle order fill"""
        payload = msg.payload
        order_id = payload.get('order_id')
        price = payload.get('price', 0)
        quantity = payload.get('quantity', 0)
        side = payload.get('side')
        fill_value = payload.get('fill_value', price * quantity)


        if order_id in self.portfolio['orders']:
            order = self.portfolio['orders'][order_id]
            symbol = order['symbol']


            if symbol not in self.portfolio['positions']:
                self.portfolio['positions'][symbol] = 0

            if side == 'BUY':
                self.portfolio['positions'][symbol] += quantity
                self.portfolio['cash'] -= fill_value
            else:
                self.portfolio['positions'][symbol] -= quantity
                self.portfolio['cash'] += fill_value


            del self.portfolio['orders'][order_id]

        self.stats['orders_filled'] += 1
        self.stats['trades_completed'] += 1

        self.tick_logger.log_tick(
            event_type="ORDER_FILLED",
            order_id=order_id,
            price=price,
            quantity=quantity,
            side=side,
            fill_value=fill_value,
            remaining_cash=self.portfolio['cash'],
            portfolio_value=self.calculate_portfolio_value()
        )

        print(f" {self.client_name} FILL: {side} {quantity} @ ${price:.2f}")

    async def handle_order_reject(self, msg):
        """Handle order rejection"""
        payload = msg.payload
        order_id = payload.get('order_id')
        error = payload.get('error')

        self.tick_logger.log_tick(
            event_type="ORDER_REJECTED",
            order_id=order_id,
            error=error
        )

        print(f" {self.client_name} ORDER REJECTED: {error}")

    async def handle_market_data(self, msg):
        """Handle market data updates"""
        payload = msg.payload
        symbol = payload.get('symbol')

        if symbol:
            self.market_data[symbol] = {
                'best_bid': payload.get('best_bid'),
                'best_ask': payload.get('best_ask'),
                'bid_count': payload.get('bid_count', 0),
                'ask_count': payload.get('ask_count', 0),
                'spread': payload.get('spread'),
                'timestamp': time.time()
            }

            self.tick_logger.log_tick(
                event_type="MARKET_DATA_UPDATED",
                symbol=symbol,
                best_bid=payload.get('best_bid'),
                best_ask=payload.get('best_ask'),
                spread=payload.get('spread')
            )

    async def handle_trade_update(self, msg):
        """Handle trade updates from market"""
        payload = msg.payload

        trade_info = {
            'timestamp': time.time(),
            'symbol': payload.get('symbol'),
            'price': payload.get('price'),
            'quantity': payload.get('quantity'),
            'trade_id': payload.get('trade_id')
        }

        self.trade_history.append(trade_info)


        if len(self.trade_history) > 1000:
            self.trade_history.pop(0)

        self.tick_logger.log_tick(
            event_type="MARKET_TRADE_OBSERVED",
            symbol=payload.get('symbol'),
            price=payload.get('price'),
            quantity=payload.get('quantity'),
            trade_id=payload.get('trade_id')
        )

    async def handle_order_book_update(self, msg):
        """Handle order book updates"""
        payload = msg.payload
        symbol = payload.get('symbol')

        if symbol not in self.order_book_cache:
            self.order_book_cache[symbol] = {'bids': [], 'asks': []}



        self.tick_logger.log_tick(
            event_type="ORDER_BOOK_UPDATED",
            symbol=symbol,
            side=payload.get('side'),
            price=payload.get('price'),
            quantity=payload.get('quantity')
        )

    def handle_system_config(self, msg):
        """Handle system configuration updates"""
        config = msg.payload.get('config', {})

        if 'trading_enabled' in config:
            self.trading_enabled = config['trading_enabled']

        self.tick_logger.log_tick(
            event_type="SYSTEM_CONFIG_RECEIVED",
            trading_enabled=self.trading_enabled,
            config_keys=list(config.keys())
        )

    def handle_config_update(self, msg):
        """Handle configuration broadcasts"""
        updates = msg.payload.get('config_updates', {})

        if 'trading_enabled' in updates:
            self.trading_enabled = updates['trading_enabled']

            self.tick_logger.log_tick(
                event_type="CONFIG_UPDATED",
                trading_enabled=self.trading_enabled,
                updates=list(updates.keys())
            )

    def calculate_portfolio_value(self):
        """Calculate total portfolio value"""
        total_value = self.portfolio['cash']

        for symbol, quantity in self.portfolio['positions'].items():
            if symbol in self.market_data:
                market_info = self.market_data[symbol]

                if market_info['best_bid'] and market_info['best_ask']:
                    mid_price = (market_info['best_bid']['price'] + market_info['best_ask']['price']) / 2
                    total_value += quantity * mid_price

        return total_value

    async def trading_strategy(self):
        """Main trading strategy loop"""
        while self.connected and self.trading_enabled:
            try:
                await self.execute_trading_logic()
                await asyncio.sleep(self.strategy_params['trading_frequency'])
            except Exception as e:
                print(f" Trading strategy error: {e}")
                self.tick_logger.log_tick(
                    event_type="TRADING_STRATEGY_ERROR",
                    error=str(e)
                )
                await asyncio.sleep(10)  

    async def execute_trading_logic(self):
        """Execute trading logic"""
        if not self.market_data:
            return


        for symbol in self.strategy_params['symbols']:
            if symbol not in self.market_data:
                continue

            market_info = self.market_data[symbol]
            if not market_info['best_bid'] or not market_info['best_ask']:
                continue

            bid_price = market_info['best_bid']['price']
            ask_price = market_info['best_ask']['price']
            spread = ask_price - bid_price


            if spread < self.strategy_params['min_spread']:
                continue


            current_position = self.portfolio['positions'].get(symbol, 0)
            max_position = self.strategy_params['max_position_size']


            if abs(current_position) < max_position:

                if random.random() < 0.3:  
                    side = random.choice(['BUY', 'SELL'])

                    if side == 'BUY' and current_position < max_position:
                        await self.place_order(symbol, 'BID', bid_price + 0.01, 
                                             min(self.strategy_params['max_order_size'], 
                                                 max_position - current_position))
                    elif side == 'SELL' and current_position > -max_position:
                        await self.place_order(symbol, 'ASK', ask_price - 0.01,
                                             min(self.strategy_params['max_order_size'],
                                                 max_position + current_position))

    async def place_order(self, symbol, side, price, quantity):
        """Place an order"""
        if not self.exchange_ws:
            return


        trace_id = f"trade_{self.client_name}_{int(time.time()*1000)}"

        order_msg = Message(
            msg_type=MessageType.NEW_ORDER,
            timestamp_ns=HighResolutionClock.get_timestamp_ns(),
            sequence=self.get_next_sequence(),
            payload={
                'symbol': symbol,
                'side': side,
                'price': price,
                'quantity': quantity,
                'client_order_id': f"{self.client_name}_{self.get_next_sequence()}",
                'client_id': self.client_id
            },
            trace_id=trace_id
        )

        try:
            await self.exchange_ws.send(order_msg.to_json())
            self.stats['orders_sent'] += 1

            self.tick_logger.log_tick(
                event_type="ORDER_SENT",
                symbol=symbol,
                side=side,
                price=price,
                quantity=quantity,
                trace_id=trace_id,
                client_order_id=order_msg.payload['client_order_id']
            )

            print(f"📤 {self.client_name} ORDER: {side} {quantity} {symbol} @ ${price:.2f}")

        except Exception as e:
            self.tick_logger.log_tick(
                event_type="ORDER_SEND_ERROR",
                error=str(e),
                trace_id=trace_id
            )

    async def send_heartbeats(self):
        """Send periodic heartbeats"""
        while self.connected:
            try:
                if self.exchange_ws:
                    heartbeat = Message(
                        msg_type=MessageType.HEARTBEAT,
                        timestamp_ns=HighResolutionClock.get_timestamp_ns(),
                        sequence=self.get_next_sequence(),
                        payload={'client_id': self.client_id, 'timestamp': time.time()}
                    )
                    await self.exchange_ws.send(heartbeat.to_json())

                await asyncio.sleep(30) 

            except Exception as e:
                self.tick_logger.log_tick(
                    event_type="HEARTBEAT_ERROR",
                    error=str(e)
                )
                await asyncio.sleep(30)

    def display_stats(self):
        """Display trading statistics"""
        while True:
            if RICH_AVAILABLE:
                os.system('cls' if os.name == 'nt' else 'clear')


                table = Table(title=f"🤖 {self.client_name} Trading Stats")
                table.add_column("Metric", style="cyan")
                table.add_column("Value", style="green")

                uptime = time.time() - self.stats['start_time']
                portfolio_value = self.calculate_portfolio_value()
                pnl = portfolio_value - 100000.0  

                table.add_row("Status", " CONNECTED" if self.connected else " DISCONNECTED")
                table.add_row("Trading", " ENABLED" if self.trading_enabled else " DISABLED")
                table.add_row("Uptime", f"{uptime:.1f}s")
                table.add_row("Cash", f"${self.portfolio['cash']:,.2f}")
                table.add_row("Portfolio Value", f"${portfolio_value:,.2f}")
                table.add_row("P&L", f"${pnl:,.2f}")
                table.add_row("Orders Sent", str(self.stats['orders_sent']))
                table.add_row("Orders Filled", str(self.stats['orders_filled']))
                table.add_row("Trades Completed", str(self.stats['trades_completed']))
                table.add_row("Messages Received", str(self.stats['messages_received']))
                table.add_row("Ticks Logged", str(self.tick_logger.get_stats()['total_ticks']))

                self.console.print(table)


                if self.portfolio['positions']:
                    position_table = Table(title=" Current Positions")
                    position_table.add_column("Symbol", style="cyan")
                    position_table.add_column("Quantity", style="green")
                    position_table.add_column("Market Price", style="yellow")
                    position_table.add_column("Value", style="blue")

                    for symbol, quantity in self.portfolio['positions'].items():
                        if quantity != 0:
                            market_price = "N/A"
                            value = 0

                            if symbol in self.market_data:
                                market_info = self.market_data[symbol]
                                if market_info['best_bid'] and market_info['best_ask']:
                                    mid_price = (market_info['best_bid']['price'] + market_info['best_ask']['price']) / 2
                                    market_price = f"${mid_price:.2f}"
                                    value = quantity * mid_price

                            position_table.add_row(
                                symbol,
                                str(quantity),
                                market_price,
                                f"${value:.2f}" if value else "N/A"
                            )

                    self.console.print(position_table)


                if self.market_data:
                    market_table = Table(title=" Market Data")
                    market_table.add_column("Symbol", style="cyan")
                    market_table.add_column("Best Bid", style="green")
                    market_table.add_column("Best Ask", style="red")
                    market_table.add_column("Spread", style="yellow")

                    for symbol, data in self.market_data.items():
                        bid = data['best_bid']
                        ask = data['best_ask']

                        bid_str = f"${bid['price']:.2f}" if bid else "N/A"
                        ask_str = f"${ask['price']:.2f}" if ask else "N/A"
                        spread_str = f"${data['spread']:.2f}" if data['spread'] else "N/A"

                        market_table.add_row(symbol, bid_str, ask_str, spread_str)

                    self.console.print(market_table)

            else:
                os.system('cls' if os.name == 'nt' else 'clear')
                uptime = time.time() - self.stats['start_time']
                portfolio_value = self.calculate_portfolio_value()
                pnl = portfolio_value - 100000.0

                print(f"🤖 {self.client_name} Trading Client")
                print(f"Status: {' CONNECTED' if self.connected else ' DISCONNECTED'}")
                print(f"Trading: {' ENABLED' if self.trading_enabled else ' DISABLED'}")
                print(f" Cash: ${self.portfolio['cash']:,.2f}")
                print(f" Portfolio: ${portfolio_value:,.2f}")
                print(f" P&L: ${pnl:,.2f}")
                print(f" Orders Sent: {self.stats['orders_sent']}")
                print(f" Orders Filled: {self.stats['orders_filled']}")
                print(f" Ticks: {self.tick_logger.get_stats()['total_ticks']}")
                print(f"⏱ Uptime: {uptime:.1f}s")

            time.sleep(3)

    async def run(self):
        """Main execution loop"""
        print(f"\n Starting {self.client_name} Trading Client...")

        if not await self.connect_to_servers():
            print(" Failed to connect to servers")
            return

        await self.initialize_trading()

        stats_thread = threading.Thread(target=self.display_stats, daemon=True)
        stats_thread.start()


        tasks = [
            asyncio.create_task(self.listen_to_exchange()),
            asyncio.create_task(self.listen_to_relay()),
            asyncio.create_task(self.listen_to_shared()),
            asyncio.create_task(self.trading_strategy()),
            asyncio.create_task(self.send_heartbeats())
        ]

        self.tick_logger.log_tick(
            event_type="CLIENT_FULLY_STARTED",
            client_name=self.client_name,
            tasks_started=len(tasks)
        )

        try:
            # Wait for all tasks
            await asyncio.gather(*tasks)
        except Exception as e:
            print(f" Client error: {e}")
            self.tick_logger.log_tick(
                event_type="CLIENT_ERROR",
                error=str(e)
            )
        finally:
            self.connected = False
            self.tick_logger.log_tick(
                event_type="CLIENT_SHUTDOWN",
                final_portfolio_value=self.calculate_portfolio_value(),
                total_trades=self.stats['trades_completed']
            )

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="HFT Trading Client")
    parser.add_argument("--name", default="TRADER1", help="Client name (TRADER1, TRADER2, etc.)")
    parser.add_argument("--config", default="network_config.json", help="Config file")
    parser.add_argument("--mode", choices=['localhost', 'network'], help="Deployment mode")

    args = parser.parse_args()

    client = TradingClient(args.name, args.config)

    if args.mode:
        if args.mode == "network":
            client.config.switch_to_network_mode()
        else:
            client.config.switch_to_localhost_mode()

    try:
        asyncio.run(client.run())
    except KeyboardInterrupt:
        print(f"\n {args.name} stopped by user")
