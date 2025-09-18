import asyncio
import json
import websockets
from .config import settings
from .trading_strategy import trading_strategy
from datetime import datetime, timezone
import math
import time
import traceback
from typing import Optional, Dict, List
from .utils.logger import get_logger

logger = get_logger("bot_core")

class BotCore:
    def __init__(self, user_id: str, binance_client, bot_settings: dict):
        """
        Complete Trading Bot Core - Mevcut BinanceClient ile uyumlu
        """
        self.user_id = user_id
        self.binance_client = binance_client  # Mevcut BinanceClient
        self.bot_settings = bot_settings
        self._initialized = False
        
        # Bot durumu - kullanıcıya özel
        self.status = {
            "is_running": False,
            "symbol": bot_settings.get("symbol", "BTCUSDT"),
            "timeframe": bot_settings.get("timeframe", "15m"),
            "leverage": bot_settings.get("leverage", 10),
            "order_size": bot_settings.get("order_size", 35.0),
            "stop_loss": bot_settings.get("stop_loss", 2.0),
            "take_profit": bot_settings.get("take_profit", 4.0),
            "position_side": None,
            "status_message": "Bot başlatılmadı.",
            "account_balance": 0.0,
            "position_pnl": 0.0,
            "last_check_time": None,
            "total_trades": 0,
            "total_pnl": 0.0,
            "last_trade_time": None,
            "last_signal": "HOLD",
            "entry_price": 0.0,
            "current_price": 0.0,
            "unrealized_pnl": 0.0
        }
        
        # Trading data
        self.klines_data = []
        self.current_price = None
        self.symbol_validated = False
        self.min_notional = 5.0
        
        # Precision settings
        self.quantity_precision = 3
        self.price_precision = 2
        
        # WebSocket ve task management
        self._stop_requested = False
        self._websocket_task = None
        self._monitor_task = None
        self._strategy_task = None
        
        # Trading controls - EMA Crossover için optimize edildi
        self.last_trade_time = 0
        self.min_trade_interval = 30  # 30 saniye (EMA crossover için)
        self.consecutive_losses = 0
        self.max_consecutive_losses = 3
        
        # Performance tracking
        self.trade_history = []
        
        logger.info(f"BotCore created for user {user_id} with symbol {self.status['symbol']}")

    async def start(self):
        """Bot başlatma - mevcut BinanceClient ile uyumlu"""
        if self.status["is_running"]:
            logger.warning(f"Bot already running for user {self.user_id}")
            return
            
        self._stop_requested = False
        self.status["is_running"] = True
        self.status["status_message"] = "Bot başlatılıyor..."
        
        logger.info(f"Starting bot for user {self.user_id} on {self.status['symbol']}")
        
        try:
            # 1. Binance client initialization
            await self._initialize_binance_client()
            
            # 2. Symbol validation
            await self._setup_symbol_info()
            
            # 3. Account validation
            await self._validate_account()
            
            # 4. Cleanup existing orders
            await self._cleanup_existing_orders()
            
            # 5. Load historical data
            await self._load_historical_data()
            
            # 6. Start real-time components
            await self._start_realtime_components()
            
            self.status["status_message"] = f"Bot aktif - {self.status['symbol']} (WebSocket + Trading)"
            self._initialized = True
            logger.info(f"Bot started successfully for user {self.user_id} with WebSocket data stream")
            
        except Exception as e:
            error_msg = f"Bot başlatma hatası: {e}"
            logger.error(f"Bot start failed for user {self.user_id}: {e}")
            logger.error(traceback.format_exc())
            self.status["status_message"] = error_msg
            self.status["is_running"] = False
            await self.stop()

    async def _initialize_binance_client(self):
        """BinanceClient başlatma"""
        try:
            if not self._initialized:
                init_result = await self.binance_client.initialize()
                if not init_result:
                    raise Exception("BinanceClient initialization failed")
            logger.info(f"Binance client initialized for user {self.user_id}")
        except Exception as e:
            raise Exception(f"BinanceClient initialization failed: {e}")

    async def _setup_symbol_info(self):
        """Symbol bilgileri setup"""
        try:
            symbol_info = await self.binance_client.get_symbol_info(self.status["symbol"])
            if symbol_info:
                self.quantity_precision = self._get_precision_from_filter(symbol_info, 'LOT_SIZE', 'stepSize')
                self.price_precision = self._get_precision_from_filter(symbol_info, 'PRICE_FILTER', 'tickSize')
                
                for f in symbol_info.get('filters', []):
                    if f.get('filterType') == 'MIN_NOTIONAL':
                        self.min_notional = float(f.get('notional', 5.0))
                        break
                
                self.symbol_validated = True
                logger.info(f"Symbol {self.status['symbol']} configured - qty_precision: {self.quantity_precision}, price_precision: {self.price_precision}")
            else:
                logger.warning(f"Symbol info not available via REST for user {self.user_id}, using WebSocket")
                
        except Exception as e:
            logger.warning(f"Symbol setup failed for user {self.user_id}: {e}")

    async def _validate_account(self):
        """Account validation"""
        try:
            # Balance check
            self.status["account_balance"] = await self.binance_client.get_account_balance(use_cache=False)
            if self.status["account_balance"] < self.status["order_size"]:
                logger.warning(f"Low balance warning for user {self.user_id}: {self.status['account_balance']} < {self.status['order_size']}")
            
            logger.info(f"Account balance for user {self.user_id}: {self.status['account_balance']} USDT")
            
            # Leverage setting
            leverage_result = await self.binance_client.set_leverage(self.status["symbol"], self.status["leverage"])
            if leverage_result:
                logger.info(f"Leverage set for user {self.user_id}: {self.status['leverage']}x")
            else:
                logger.warning(f"Could not set leverage for user {self.user_id}")
                
        except Exception as e:
            logger.error(f"Account validation failed for user {self.user_id}: {e}")

    async def _cleanup_existing_orders(self):
        """Mevcut orderları temizle"""
        try:
            await self.binance_client.cancel_all_orders_safe(self.status["symbol"])
            
            # Mevcut pozisyon kontrolü
            open_positions = await self.binance_client.get_open_positions(self.status["symbol"], use_cache=False)
            if open_positions:
                position = open_positions[0]
                position_amt = float(position.get('positionAmt', 0))
                if abs(position_amt) > 0:
                    if position_amt > 0:
                        self.status["position_side"] = "LONG"
                    else:
                        self.status["position_side"] = "SHORT"
                    
                    self.status["entry_price"] = float(position.get('entryPrice', 0))
                    self.status["unrealized_pnl"] = float(position.get('unRealizedProfit', 0))
                    logger.info(f"Existing position found for user {self.user_id}: {self.status['position_side']} at {self.status['entry_price']}")
                    
        except Exception as e:
            logger.warning(f"Cleanup failed for user {self.user_id}: {e}")

    async def _load_historical_data(self):
        """Historical data loading"""
        try:
            klines = await self.binance_client.get_historical_klines(
                self.status["symbol"], 
                self.status["timeframe"], 
                limit=50
            )
            if klines and len(klines) > 20:
                self.klines_data = klines
                signal = trading_strategy.analyze_klines(self.klines_data)
                self.status["last_signal"] = signal
                logger.info(f"Historical data loaded for user {self.user_id}: {len(klines)} candles")
            else:
                logger.warning(f"Insufficient historical data for user {self.user_id}")
                
        except Exception as e:
            logger.warning(f"Historical data loading failed for user {self.user_id}: {e}")

    async def _start_realtime_components(self):
        """Real-time components başlat"""
        self._websocket_task = asyncio.create_task(self._websocket_loop())
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        self._strategy_task = asyncio.create_task(self._strategy_loop())
        
        logger.info(f"Real-time components started for user {self.user_id}")

    async def stop(self):
        """Bot durdurma"""
        if not self.status["is_running"]:
            return
            
        logger.info(f"Stopping bot for user {self.user_id}")
        self._stop_requested = True
        
        # Task cleanup
        tasks = [self._websocket_task, self._monitor_task, self._strategy_task]
        for task in tasks:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        # Final cleanup
        try:
            await self.binance_client.cancel_all_orders_safe(self.status["symbol"])
        except:
            pass
        
        self.status.update({
            "is_running": False,
            "status_message": "Bot durduruldu.",
            "last_check_time": datetime.now(timezone.utc).isoformat()
        })
        
        logger.info(f"Bot stopped for user {self.user_id}")

    async def _websocket_loop(self):
        """WebSocket data stream"""
        symbol = self.status["symbol"].lower()
        timeframe = self.status["timeframe"]
        
        ticker_stream = f"{symbol}@ticker"
        kline_stream = f"{symbol}@kline_{timeframe}"
        ws_url = f"wss://stream.binance.com:9443/stream?streams={ticker_stream}/{kline_stream}"
        
        reconnect_attempts = 0
        max_reconnects = 15
        
        logger.info(f"Starting combined WebSocket for user {self.user_id} on {symbol}")
        
        while not self._stop_requested and reconnect_attempts < max_reconnects:
            try:
                async with websockets.connect(
                    ws_url,
                    ping_interval=30,
                    ping_timeout=15,
                    close_timeout=10
                ) as ws:
                    logger.info(f"WebSocket connected for user {self.user_id}")
                    reconnect_attempts = 0
                    
                    while not self._stop_requested:
                        try:
                            message = await asyncio.wait_for(ws.recv(), timeout=65.0)
                            await self._handle_websocket_message(message)
                        except asyncio.TimeoutError:
                            try:
                                await ws.ping()
                            except:
                                logger.warning(f"WebSocket ping failed for user {self.user_id}")
                                break
                        except websockets.exceptions.ConnectionClosed:
                            logger.warning(f"WebSocket closed for user {self.user_id}")
                            break
                        except Exception as e:
                            logger.error(f"WebSocket message error for user {self.user_id}: {e}")
                            await asyncio.sleep(1)
                            
            except Exception as e:
                if not self._stop_requested:
                    reconnect_attempts += 1
                    backoff_time = min(5 * reconnect_attempts, 30)
                    logger.error(f"WebSocket error for user {self.user_id} (attempt {reconnect_attempts}): {e}")
                    if reconnect_attempts < max_reconnects:
                        logger.info(f"Reconnecting WebSocket for user {self.user_id} in {backoff_time}s")
                        await asyncio.sleep(backoff_time)

    async def _handle_websocket_message(self, message: str):
        """WebSocket message handling"""
        try:
            data = json.loads(message)
            
            if 'stream' in data and 'data' in data:
                stream = data['stream']
                stream_data = data['data']
                
                if '@ticker' in stream:
                    await self._handle_ticker_data(stream_data)
                elif '@kline' in stream:
                    await self._handle_kline_data(stream_data)
            else:
                if 'e' in data:
                    if data['e'] == '24hrTicker':
                        await self._handle_ticker_data(data)
                    elif data['e'] == 'kline':
                        await self._handle_kline_data(data)
                        
        except Exception as e:
            logger.error(f"WebSocket message parsing error for user {self.user_id}: {e}")

    async def _handle_ticker_data(self, ticker_data: dict):
        """Ticker data handling"""
        try:
            self.current_price = float(ticker_data['c'])
            self.status["current_price"] = self.current_price
            
            if not self.symbol_validated:
                self.symbol_validated = True
                logger.info(f"Symbol {self.status['symbol']} validated via WebSocket for user {self.user_id}")
            
            # Real-time PnL calculation
            if self.status["position_side"] and self.status["entry_price"]:
                await self._calculate_realtime_pnl()
                
        except Exception as e:
            logger.error(f"Ticker data handling error for user {self.user_id}: {e}")

    async def _calculate_realtime_pnl(self):
        """Real-time PnL calculation"""
        try:
            if self.status["position_side"] and self.current_price and self.status["entry_price"]:
                entry_price = self.status["entry_price"]
                current_price = self.current_price
                order_size = self.status["order_size"]
                leverage = self.status["leverage"]
                
                if self.status["position_side"] == "LONG":
                    pnl_percentage = ((current_price - entry_price) / entry_price) * 100 * leverage
                else:  # SHORT
                    pnl_percentage = ((entry_price - current_price) / entry_price) * 100 * leverage
                
                unrealized_pnl = (order_size * pnl_percentage) / 100
                self.status["unrealized_pnl"] = unrealized_pnl
                
        except Exception as e:
            logger.error(f"PnL calculation error for user {self.user_id}: {e}")

    async def _handle_kline_data(self, kline_data: dict):
        """Kline data handling"""
        try:
            if 'k' in kline_data:
                kline_info = kline_data['k']
            else:
                kline_info = kline_data
            
            # Only closed candles
            if not kline_info.get('x', False):
                return
            
            close_price = float(kline_info['c'])
            self.current_price = close_price
            self.status["current_price"] = close_price
            
            logger.info(f"New candle closed for user {self.user_id}: ${close_price:.2f}")
            
            # Update klines data
            new_kline = [
                int(kline_info['t']),    # Open time
                str(kline_info['o']),    # Open
                str(kline_info['h']),    # High
                str(kline_info['l']),    # Low
                str(kline_info['c']),    # Close
                str(kline_info['v']),    # Volume
                int(kline_info['T']),    # Close time
                str(kline_info['q']),    # Quote asset volume
                int(kline_info['n']),    # Number of trades
                str(kline_info['V']),    # Taker buy base asset volume
                str(kline_info['Q']),    # Taker buy quote asset volume
                '0'                      # Ignore
            ]
            
            # Maintain klines buffer
            if len(self.klines_data) >= 100:
                self.klines_data.pop(0)
            self.klines_data.append(new_kline)
            
            # Trigger strategy analysis - EMA Crossover
            if len(self.klines_data) >= 25:  # EMA21 + buffer için daha fazla veri
                signal = trading_strategy.analyze_klines(self.klines_data)
                if signal != self.status["last_signal"]:
                    logger.info(f"🔄 EMA Strategy signal changed for user {self.user_id}: {self.status['last_signal']} -> {signal}")
                    self.status["last_signal"] = signal
                else:
                    logger.debug(f"EMA Strategy signal unchanged for user {self.user_id}: {signal}")
            else:
                logger.info(f"📊 Collecting EMA data for user {self.user_id}: {len(self.klines_data)}/25 candles")
            
        except Exception as e:
            logger.error(f"Kline data handling error for user {self.user_id}: {e}")

    async def _strategy_loop(self):
        """Main strategy execution loop - EMA Crossover için optimize edildi"""
        logger.info(f"📈 EMA Crossover strategy loop started for user {self.user_id}")
        
        while not self._stop_requested and self.status["is_running"]:
            try:
                if len(self.klines_data) >= 25 and self.current_price:  # EMA21 + buffer
                    await self._execute_trading_strategy()
                
                await asyncio.sleep(10)  # 10 saniye interval (EMA için)
                
            except Exception as e:
                logger.error(f"Strategy loop error for user {self.user_id}: {e}")
                await asyncio.sleep(30)

    async def _execute_trading_strategy(self):
        """EMA Crossover trading strategy execution"""
        try:
            current_time = time.time()
            
            # Rate limiting check
            if current_time - self.last_trade_time < self.min_trade_interval:
                return
            
            # Consecutive losses protection
            if self.consecutive_losses >= self.max_consecutive_losses:
                logger.warning(f"⚠️ Max consecutive losses reached for user {self.user_id}, pausing trading")
                return
            
            signal = self.status["last_signal"]
            current_position = self.status["position_side"]
            
            # No signal, do nothing
            if signal == "HOLD":
                return
            
            logger.info(f"📊 EMA Strategy execution for user {self.user_id}: Signal={signal}, Position={current_position}")
            
            # No position, open new position
            if not current_position and signal in ["LONG", "SHORT"]:
                logger.info(f"🎯 Opening new {signal} position for user {self.user_id}")
                await self._open_position(signal, self.current_price)
                return
            
            # Has position, check for exit or flip
            if current_position:
                # Opposite signal - flip position
                if signal != current_position and signal in ["LONG", "SHORT"]:
                    logger.info(f"🔄 EMA Crossover flip signal for user {self.user_id}: {current_position} -> {signal}")
                    await self._flip_position(signal, self.current_price)
                    return
                
                # Check stop loss / take profit
                await self._check_exit_conditions()
                
        except Exception as e:
            logger.error(f"EMA trading strategy execution error for user {self.user_id}: {e}")

    async def _open_position(self, signal: str, entry_price: float):
        """EMA Crossover position opening"""
        try:
            logger.info(f"📈 Opening {signal} position for user {self.user_id} at ${entry_price:.2f} (EMA Crossover)")
            
            # Pre-trade cleanup
            await self.binance_client.cancel_all_orders_safe(self.status["symbol"])
            await asyncio.sleep(0.5)
            
            # Position size calculation
            order_size = self.status["order_size"]
            leverage = self.status["leverage"]
            quantity = self._calculate_position_size(order_size, leverage, entry_price)
            
            if quantity <= 0:
                logger.error(f"❌ Invalid quantity calculated for user {self.user_id}: {quantity}")
                return False
            
            # Check minimum notional
            notional = quantity * entry_price
            if notional < self.min_notional:
                logger.error(f"❌ Order below minimum notional for user {self.user_id}: {notional} < {self.min_notional}")
                return False
            
            # Place market order using existing method
            side = "BUY" if signal == "LONG" else "SELL"
            
            try:
                order_result = await self.binance_client.create_market_order_with_sl_tp(
                    self.status["symbol"], 
                    side, 
                    quantity, 
                    entry_price, 
                    self.price_precision
                )
                
                if order_result:
                    # Update status
                    self.status.update({
                        "position_side": signal,
                        "entry_price": entry_price,
                        "status_message": f"✅ {signal} pozisyonu açıldı: ${entry_price:.2f} (EMA)",
                        "total_trades": self.status["total_trades"] + 1,
                        "last_trade_time": time.time()
                    })
                    
                    self.last_trade_time = time.time()
                    
                    # Log trade
                    await self._log_trade({
                        "action": "OPEN",
                        "side": signal,
                        "quantity": quantity,
                        "price": entry_price,
                        "strategy": "EMA_CROSSOVER",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    
                    logger.info(f"✅ EMA Crossover position opened successfully for user {self.user_id}: {signal} at ${entry_price:.2f}")
                    return True
                else:
                    logger.error(f"❌ Failed to open EMA position for user {self.user_id}")
                    return False
                    
            except Exception as order_error:
                logger.error(f"❌ EMA order placement error for user {self.user_id}: {order_error}")
                return False
                
        except Exception as e:
            logger.error(f"❌ EMA position opening error for user {self.user_id}: {e}")
            return False

    async def _flip_position(self, new_signal: str, current_price: float):
        """EMA Crossover position flipping"""
        try:
            logger.info(f"🔄 EMA Crossover flipping position for user {self.user_id}: {self.status['position_side']} -> {new_signal} at ${current_price:.2f}")
            
            # Close current position first
            close_result = await self._close_position("EMA_FLIP")
            
            if close_result:
                await asyncio.sleep(1)  # Brief pause
                # Open new position
                await self._open_position(new_signal, current_price)
            
        except Exception as e:
            logger.error(f"❌ EMA position flip error for user {self.user_id}: {e}")

    async def _close_position(self, reason: str = "SIGNAL"):
        """Position closing using existing BinanceClient"""
        try:
            if not self.status["position_side"]:
                return False
                
            logger.info(f"Closing {self.status['position_side']} position for user {self.user_id} - Reason: {reason}")
            
            # Get current position
            open_positions = await self.binance_client.get_open_positions(self.status["symbol"], use_cache=False)
            if not open_positions:
                self.status["position_side"] = None
                return True
            
            position = open_positions[0]
            position_amt = float(position.get('positionAmt', 0))
            
            if abs(position_amt) == 0:
                self.status["position_side"] = None
                return True
            
            # Close position using existing method
            side_to_close = 'SELL' if position_amt > 0 else 'BUY'
            
            close_result = await self.binance_client.close_position(
                self.status["symbol"], 
                position_amt, 
                side_to_close
            )
            
            if close_result:
                # Calculate PnL
                pnl = await self.binance_client.get_last_trade_pnl(self.status["symbol"])
                
                # Update status
                self.status.update({
                    "position_side": None,
                    "entry_price": 0.0,
                    "unrealized_pnl": 0.0,
                    "total_pnl": self.status["total_pnl"] + pnl,
                    "status_message": f"Pozisyon kapatıldı - PnL: ${pnl:.2f}"
                })
                
                # Track consecutive losses
                if pnl < 0:
                    self.consecutive_losses += 1
                else:
                    self.consecutive_losses = 0
                
                # Log trade
                await self._log_trade({
                    "action": "CLOSE",
                    "reason": reason,
                    "pnl": pnl,
                    "price": self.current_price,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                
                logger.info(f"Position closed for user {self.user_id} - PnL: ${pnl:.2f}")
                return True
            else:
                logger.error(f"Failed to close position for user {self.user_id}")
                return False
                
        except Exception as e:
            logger.error(f"Position closing error for user {self.user_id}: {e}")
            return False

    async def _check_exit_conditions(self):
        """Exit conditions check"""
        try:
            if not self.status["position_side"] or not self.current_price or not self.status["entry_price"]:
                return
            
            entry_price = self.status["entry_price"]
            current_price = self.current_price
            position_side = self.status["position_side"]
            
            # Calculate percentage change
            if position_side == "LONG":
                pct_change = ((current_price - entry_price) / entry_price) * 100
            else:  # SHORT
                pct_change = ((entry_price - current_price) / entry_price) * 100
            
            # Stop loss check
            if pct_change <= -self.status["stop_loss"]:
                logger.info(f"Stop loss triggered for user {self.user_id}: {pct_change:.2f}%")
                await self._close_position("STOP_LOSS")
                return
            
            # Take profit check
            if pct_change >= self.status["take_profit"]:
                logger.info(f"Take profit triggered for user {self.user_id}: {pct_change:.2f}%")
                await self._close_position("TAKE_PROFIT")
                return
                
        except Exception as e:
            logger.error(f"Exit conditions check error for user {self.user_id}: {e}")

    async def _monitor_loop(self):
        """Monitoring loop"""
        while not self._stop_requested and self.status["is_running"]:
            try:
                # Update account balance
                try:
                    self.status["account_balance"] = await self.binance_client.get_account_balance(use_cache=True)
                except Exception as e:
                    logger.debug(f"Balance update error for user {self.user_id}: {e}")
                
                # Update position PnL
                if self.status["position_side"]:
                    try:
                        self.status["position_pnl"] = await self.binance_client.get_position_pnl(
                            self.status["symbol"], 
                            use_cache=True
                        )
                    except Exception as e:
                        logger.debug(f"PnL update error for user {self.user_id}: {e}")
                
                # Update status message
                await self._update_status_message()
                
                # Update user data in Firebase
                await self._update_user_data()
                
                self.status["last_check_time"] = datetime.now(timezone.utc).isoformat()
                
                await asyncio.sleep(30)  # Monitor interval
                
            except Exception as e:
                logger.error(f"Monitor loop error for user {self.user_id}: {e}")
                await asyncio.sleep(10)

    async def _update_status_message(self):
        """Update status message - EMA Crossover için"""
        try:
            if self.current_price and self.symbol_validated:
                position_text = ""
                if self.status["position_side"]:
                    pnl_text = f" (PnL: ${self.status.get('unrealized_pnl', 0):.2f})"
                    position_text = f" - {self.status['position_side']}{pnl_text}"
                
                signal_text = f" - EMA: {self.status['last_signal']}"
                price_text = f" (${self.current_price:.2f})"
                
                self.status["status_message"] = f"📈 EMA Bot aktif - {self.status['symbol']}{price_text}{position_text}{signal_text}"
                
        except Exception as e:
            logger.error(f"Status message update error for user {self.user_id}: {e}")

    async def _update_user_data(self):
        """Update user data in Firebase - FIX: ServerValue hatası düzeltildi"""
        try:
            from app.main import firebase_db, firebase_initialized
            
            if firebase_initialized and firebase_db:
                user_update = {
                    "bot_active": self.status["is_running"],
                    "bot_symbol": self.status["symbol"],
                    "bot_position": self.status["position_side"],
                    "total_trades": self.status["total_trades"],
                    "total_pnl": self.status["total_pnl"],
                    "account_balance": self.status["account_balance"],
                    "current_price": self.current_price,
                    "last_signal": self.status["last_signal"],
                    "unrealized_pnl": self.status.get("unrealized_pnl", 0),
                    "symbol_validated": self.symbol_validated,
                    "last_bot_update": int(time.time() * 1000)  # FIX: Manual timestamp
                }
                
                user_ref = firebase_db.reference(f'users/{self.user_id}')
                user_ref.update(user_update)
            
        except Exception as e:
            logger.error(f"User data update error for user {self.user_id}: {e}")

    async def _log_trade(self, trade_data: dict):
        """Log trade to Firebase"""
        try:
            from app.main import firebase_db, firebase_initialized
            
            if firebase_initialized and firebase_db:
                trade_log = {
                    "user_id": self.user_id,
                    "symbol": self.status["symbol"],
                    **trade_data
                }
                
                trades_ref = firebase_db.reference('trades')
                trades_ref.push(trade_log)
                
                # Add to local history
                self.trade_history.append(trade_log)
                
                # Maintain history limit
                if len(self.trade_history) > 50:
                    self.trade_history.pop(0)
            
        except Exception as e:
            logger.error(f"Trade logging error for user {self.user_id}: {e}")

    def _calculate_position_size(self, order_size: float, leverage: int, price: float) -> float:
        """Calculate position size with precision"""
        try:
            quantity = (order_size * leverage) / price
            return self._format_quantity(quantity)
        except:
            return 0.0

    def _format_quantity(self, quantity: float) -> float:
        """Format quantity with proper precision"""
        if self.quantity_precision == 0:
            return math.floor(quantity)
        factor = 10 ** self.quantity_precision
        return math.floor(quantity * factor) / factor

    def _get_precision_from_filter(self, symbol_info: dict, filter_type: str, key: str) -> int:
        """Get precision from symbol filters"""
        try:
            for f in symbol_info.get('filters', []):
                if f.get('filterType') == filter_type:
                    size_str = f.get(key, '0.001')
                    if '.' in size_str:
                        return len(size_str.split('.')[1].rstrip('0'))
                    return 0
        except:
            pass
        return 3 if filter_type == 'LOT_SIZE' else 2

    def get_status(self) -> dict:
        """Get comprehensive bot status"""
        return {
            "user_id": self.user_id,
            "is_running": self.status["is_running"],
            "symbol": self.status["symbol"],
            "timeframe": self.status["timeframe"],
            "leverage": self.status["leverage"],
            "position_side": self.status["position_side"],
            "status_message": self.status["status_message"],
            "account_balance": self.status["account_balance"],
            "position_pnl": self.status.get("position_pnl", 0),
            "unrealized_pnl": self.status.get("unrealized_pnl", 0),
            "total_trades": self.status["total_trades"],
            "total_pnl": self.status["total_pnl"],
            "last_check_time": self.status["last_check_time"],
            "current_price": self.current_price,
            "entry_price": self.status.get("entry_price", 0),
            "last_signal": self.status.get("last_signal", "HOLD"),
            "symbol_validated": self.symbol_validated,
            "data_candles": len(self.klines_data),
            "consecutive_losses": self.consecutive_losses,
            "last_trade_time": self.status.get("last_trade_time"),
            "order_size": self.status["order_size"],
            "stop_loss": self.status["stop_loss"],
            "take_profit": self.status["take_profit"]
        }
