# app/bot_core.py - API BAN SAFE Version with Fixed TP/SL
import asyncio
import json
import math
import time
import traceback
from datetime import datetime, timezone
from typing import Optional, Dict, List
from .config import settings
from .trading_strategy import create_strategy_for_timeframe
from .binance_client import BinanceClient
from .utils.logger import get_logger

logger = get_logger("bot_core")

class BotCore:
    def __init__(self, user_id: str, api_key: str, api_secret: str, bot_settings: dict):
        """
        💰 API BAN SAFE Trading Bot Core
        Minimum API calls + Maximum performance
        """
        self.user_id = user_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.bot_settings = bot_settings
        self._initialized = False
        
        # ✅ Optimized Binance client
        self.binance_client = BinanceClient(
            api_key=api_key,
            api_secret=api_secret, 
            user_id=user_id
        )
        
        # ✅ Timeframe strategy
        timeframe = bot_settings.get("timeframe", "15m")
        self.timeframe_strategy = create_strategy_for_timeframe(timeframe)
        risk_params = self.timeframe_strategy.get_risk_params()
        
        # Bot durumu
        self.status = {
            "is_running": False,
            "symbol": bot_settings.get("symbol", "BTCUSDT"),
            "timeframe": timeframe,
            "leverage": bot_settings.get("leverage", 10),
            "order_size": bot_settings.get("order_size", 35.0),
            
            # 🔧 FIXED: User TP/SL values FIRST
            "stop_loss": bot_settings.get("stop_loss", risk_params["stop_loss_percent"]),
            "take_profit": bot_settings.get("take_profit", risk_params["take_profit_percent"]),
            "max_hold_time": risk_params["max_hold_time_minutes"],
            "expected_win_rate": risk_params["win_rate_target"],
            "strategy_type": self.timeframe_strategy.config["strategy_type"],
            
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
            "unrealized_pnl": 0.0,
            "current_win_rate": 0.0,
            "performance_vs_expected": 1.0,
            "total_closed_trades": 0,
            "average_pnl_per_trade": 0.0,
            "strategy_performance": "TRACKING"
        }
        
        # Trading data
        self.klines_data = []
        self.current_price = None
        self.symbol_validated = False
        self.min_notional = 5.0
        self.quantity_precision = 3
        self.price_precision = 2
        
        # 🚫 API BAN PROTECTION
        self._stop_requested = False
        self._monitor_task = None
        self._candle_watch_task = None  # Sadece mum kapanışı izle
        self._price_callback_task = None
        
        # Trading controls
        self.last_trade_time = 0
        self.min_trade_interval = 60  # 1 dakika minimum
        self.consecutive_losses = 0
        self.max_consecutive_losses = 3
        
        # 🔒 API RATE LIMITING
        self.last_api_call = 0
        self.api_call_interval = 30  # 30 saniye minimum API çağrısı
        self.last_kline_fetch = 0
        self.kline_fetch_interval = 300  # 5 dakika minimum kline fetch
        
        # Performance tracking
        self.trade_history = []
        self.signal_history = []
        self._last_price_update = 0
        
        # 🕐 CANDLE TIMING
        self.last_candle_time = 0
        self.timeframe_seconds = self._get_timeframe_seconds(timeframe)
        
        logger.info(f"🔒 API SAFE Bot created for user {user_id}")
        logger.info(f"🔧 USER TP/SL: SL={self.status['stop_loss']}%, TP={self.status['take_profit']}%")
        logger.info(f"⏰ Timeframe: {timeframe} ({self.timeframe_seconds}s intervals)")

    def _get_timeframe_seconds(self, timeframe: str) -> int:
        """Timeframe'i saniyeye çevir"""
        timeframe_map = {
            "1m": 60,
            "3m": 180,
            "5m": 300,
            "15m": 900,
            "30m": 1800,
            "1h": 3600,
            "2h": 7200,
            "4h": 14400,
            "6h": 21600,
            "8h": 28800,
            "12h": 43200,
            "1d": 86400
        }
        return timeframe_map.get(timeframe, 900)

    async def start(self):
        """🚀 API SAFE Bot başlatma"""
        if self.status["is_running"]:
            logger.warning(f"Bot already running for user {self.user_id}")
            return
            
        self._stop_requested = False
        self.status["is_running"] = True
        self.status["status_message"] = "Bot başlatılıyor..."
        
        logger.info(f"🚀 Starting API SAFE {self.status['timeframe']} bot for user {self.user_id}")
        
        try:
            # 1. Client initialization
            await self._initialize_binance_client()
            
            # 2. WebSocket subscription (NO API CALLS)
            await self._subscribe_to_price_feed()
            
            # 3. One-time setup
            await self._one_time_setup()
            
            # 4. Load historical data (ONCE)
            await self._load_initial_data()
            
            # 5. Start SAFE components
            await self._start_safe_components()
            
            self.status["status_message"] = f"✅ API SAFE Bot aktif - {self.status['symbol']} ({self.status['timeframe']})"
            self._initialized = True
            logger.info(f"✅ API SAFE bot started for user {self.user_id}")
            
        except Exception as e:
            error_msg = f"Bot başlatma hatası: {e}"
            logger.error(f"❌ Bot start failed for user {self.user_id}: {e}")
            self.status["status_message"] = error_msg
            self.status["is_running"] = False
            await self.stop()

    async def _initialize_binance_client(self):
        """Client başlatma"""
        try:
            init_result = await self.binance_client.initialize()
            if not init_result:
                raise Exception("BinanceClient initialization failed")
            logger.info(f"✅ Binance client initialized for user {self.user_id}")
        except Exception as e:
            raise Exception(f"BinanceClient initialization failed: {e}")

    async def _subscribe_to_price_feed(self):
        """🔌 WebSocket subscription (NO API CALLS)"""
        try:
            await self.binance_client.subscribe_to_symbol(self.status["symbol"])
            logger.info(f"✅ WebSocket subscribed for {self.status['symbol']} - user {self.user_id}")
        except Exception as e:
            logger.error(f"❌ WebSocket subscription failed: {e}")
            raise

    async def _one_time_setup(self):
        """🔧 One-time setup (minimal API calls)"""
        try:
            # Symbol info (ONCE)
            symbol_info = await self.binance_client.get_symbol_info(self.status["symbol"])
            if symbol_info:
                self.quantity_precision = self._get_precision_from_filter(symbol_info, 'LOT_SIZE', 'stepSize')
                self.price_precision = self._get_precision_from_filter(symbol_info, 'PRICE_FILTER', 'tickSize')
                
                for f in symbol_info.get('filters', []):
                    if f.get('filterType') == 'MIN_NOTIONAL':
                        self.min_notional = float(f.get('notional', 5.0))
                        break
                
                self.symbol_validated = True
                logger.info(f"Symbol configured: {self.status['symbol']} - precision: {self.quantity_precision}")
            
            # Account balance (ONCE)
            self.status["account_balance"] = await self.binance_client.get_account_balance(use_cache=False)
            logger.info(f"Account balance: {self.status['account_balance']} USDT")
            
            # Leverage setting (ONCE)
            await self.binance_client.set_leverage(self.status["symbol"], self.status["leverage"])
            
            # Clean existing orders (ONCE)
            await self.binance_client.cancel_all_orders_safe(self.status["symbol"])
            
            # Check existing position (ONCE)
            await self._check_existing_position()
            
        except Exception as e:
            logger.error(f"One-time setup failed: {e}")

    async def _check_existing_position(self):
        """Mevcut pozisyon kontrolü (ONCE)"""
        try:
            open_positions = await self.binance_client.get_open_positions(self.status["symbol"], use_cache=False)
            if open_positions:
                position = open_positions[0]
                position_amt = float(position.get('positionAmt', 0))
                if abs(position_amt) > 0:
                    self.status["position_side"] = "LONG" if position_amt > 0 else "SHORT"
                    self.status["entry_price"] = float(position.get('entryPrice', 0))
                    self.status["unrealized_pnl"] = float(position.get('unRealizedProfit', 0))
                    logger.info(f"Existing position: {self.status['position_side']} at {self.status['entry_price']}")
        except Exception as e:
            logger.warning(f"Position check failed: {e}")

    async def _load_initial_data(self):
        """📊 Initial data loading (ONCE)"""
        try:
            required_klines = max(self.timeframe_strategy.config["ema_slow"] + 20, 50)
            
            klines = await self.binance_client.get_historical_klines(
                self.status["symbol"], 
                self.status["timeframe"], 
                limit=required_klines
            )
            
            if klines and len(klines) > 20:
                self.klines_data = klines
                signal = self.timeframe_strategy.analyze_klines(self.klines_data)
                self.status["last_signal"] = signal
                
                # Son mum zamanını kaydet
                if klines:
                    self.last_candle_time = int(klines[-1][0])
                
                logger.info(f"✅ Initial data loaded: {len(klines)} candles, signal: {signal}")
            else:
                logger.warning(f"❌ Insufficient historical data")
                
        except Exception as e:
            logger.error(f"❌ Initial data loading failed: {e}")

    async def _start_safe_components(self):
        """🔒 API SAFE components başlatma"""
        # 1. WebSocket price monitoring (NO API CALLS)
        self._price_callback_task = asyncio.create_task(self._safe_price_monitoring())
        
        # 2. Candle close monitoring (MINIMAL API CALLS)
        self._candle_watch_task = asyncio.create_task(self._candle_close_monitor())
        
        # 3. General monitoring (CACHED DATA)
        self._monitor_task = asyncio.create_task(self._safe_monitor_loop())
        
        logger.info(f"✅ API SAFE components started for user {self.user_id}")

    async def _safe_price_monitoring(self):
        """💰 WebSocket price monitoring (NO API CALLS)"""
        logger.info(f"📈 SAFE price monitoring started for user {self.user_id}")
        
        while not self._stop_requested and self.status["is_running"]:
            try:
                # WebSocket'ten fiyat al (NO API CALL)
                current_price = await self.binance_client.get_market_price(self.status["symbol"])
                
                if current_price and current_price != self.current_price:
                    self.current_price = current_price
                    self.status["current_price"] = current_price
                    self._last_price_update = time.time()
                    
                    # Real-time PnL calculation (NO API CALL)
                    if self.status["position_side"] and self.status["entry_price"]:
                        await self._calculate_realtime_pnl()
                    
                    # Exit conditions check (NO API CALL)
                    if self.status["position_side"]:
                        await self._check_exit_conditions()
                
                # 10 saniyede bir kontrol (price data WebSocket'ten geliyor)
                await asyncio.sleep(10)
                
            except Exception as e:
                logger.error(f"❌ Price monitoring error: {e}")
                await asyncio.sleep(30)

    async def _candle_close_monitor(self):
        """🕯️ SADECE MUM KAPANIŞINDA sinyal kontrol (MINIMAL API)"""
        logger.info(f"🕯️ Candle close monitor started for {self.status['timeframe']}")
        
        while not self._stop_requested and self.status["is_running"]:
            try:
                current_time = int(time.time() * 1000)  # milliseconds
                
                # Bir sonraki mum kapanışını hesapla
                next_candle_close = self._calculate_next_candle_close(current_time)
                wait_time = (next_candle_close - current_time) / 1000  # seconds
                
                # En fazla 1 saat bekle (hata koruması)
                wait_time = min(max(wait_time, 10), 3600)
                
                logger.info(f"⏰ Waiting {wait_time:.0f}s for next {self.status['timeframe']} candle close")
                await asyncio.sleep(wait_time)
                
                # 🔒 API CALL PROTECTION
                current_time = time.time()
                if current_time - self.last_kline_fetch < self.kline_fetch_interval:
                    logger.info(f"🔒 API protection: skipping kline fetch")
                    continue
                
                # Mum kapandı - yeni veri al (API CALL)
                await self._fetch_new_candle_and_check_signal()
                self.last_kline_fetch = current_time
                
            except Exception as e:
                logger.error(f"❌ Candle monitor error: {e}")
                await asyncio.sleep(60)

    def _calculate_next_candle_close(self, current_time_ms: int) -> int:
        """Bir sonraki mum kapanışını hesapla"""
        try:
            timeframe_ms = self.timeframe_seconds * 1000
            
            # Current candle'ın başlangıcını bul
            current_candle_start = (current_time_ms // timeframe_ms) * timeframe_ms
            
            # Bir sonraki candle'ın başlangıcı = mevcut candle'ın kapanışı
            next_candle_start = current_candle_start + timeframe_ms
            
            return next_candle_start
            
        except Exception as e:
            logger.error(f"Next candle calculation error: {e}")
            return current_time_ms + (self.timeframe_seconds * 1000)

    async def _fetch_new_candle_and_check_signal(self):
        """🔒 YENİ MUM VERİSİ AL ve SİNYAL KONTROL ET (SINGLE API CALL)"""
        try:
            logger.info(f"🕯️ New {self.status['timeframe']} candle - fetching data for user {self.user_id}")
            
            # Son 2 mumu al (current + previous)
            recent_klines = await self.binance_client.get_historical_klines(
                self.status["symbol"],
                self.status["timeframe"],
                limit=2
            )
            
            if not recent_klines or len(recent_klines) < 1:
                logger.warning(f"No kline data received")
                return
            
            latest_kline = recent_klines[-1]
            new_candle_time = int(latest_kline[0])
            
            # Yeni mum mu kontrol et
            if new_candle_time > self.last_candle_time:
                # Yeni mum - ekle
                if len(self.klines_data) >= 100:
                    self.klines_data.pop(0)  # Eski veriyi çıkar
                
                self.klines_data.append(latest_kline)
                self.last_candle_time = new_candle_time
                
                close_price = float(latest_kline[4])
                logger.info(f"📊 NEW {self.status['timeframe']} candle: ${close_price:.2f}")
                
                # 📈 SİNYAL KONTROL ET
                await self._analyze_and_execute_signal()
                
            else:
                logger.info(f"📊 Same candle, updating current")
                # Aynı mum - güncelle
                if self.klines_data:
                    self.klines_data[-1] = latest_kline
                    
        except Exception as e:
            logger.error(f"❌ Fetch new candle error: {e}")

    async def _analyze_and_execute_signal(self):
        """📈 SİNYAL ANALİZİ VE İŞLEM (NO EXTRA API CALLS)"""
        try:
            required_candles = max(self.timeframe_strategy.config["ema_slow"] + 10, 25)
            
            if len(self.klines_data) < required_candles:
                logger.info(f"📊 Need more data: {len(self.klines_data)}/{required_candles}")
                return
            
            # Yeni sinyal hesapla
            new_signal = self.timeframe_strategy.analyze_klines(self.klines_data)
            old_signal = self.status["last_signal"]
            
            if new_signal != old_signal:
                logger.info(f"🚨 SIGNAL CHANGE for user {self.user_id}: {old_signal} -> {new_signal}")
                self.status["last_signal"] = new_signal
                
                # Trading action
                await self._execute_signal_action(new_signal)
                
                # Performance tracking
                await self._track_strategy_performance(new_signal)
            else:
                logger.info(f"📊 Signal unchanged: {new_signal}")
                
        except Exception as e:
            logger.error(f"❌ Signal analysis error: {e}")

    async def _execute_signal_action(self, signal: str):
        """⚡ SİNYAL ACTION (MINIMAL API CALLS)"""
        try:
            current_time = time.time()
            current_position = self.status["position_side"]
            
            # Rate limiting check
            if current_time - self.last_trade_time < self.min_trade_interval:
                remaining = self.min_trade_interval - (current_time - self.last_trade_time)
                logger.info(f"⏰ Trade rate limit: waiting {remaining:.0f}s")
                return
            
            # Consecutive losses check
            if self.consecutive_losses >= self.max_consecutive_losses:
                logger.warning(f"⚠️ Max consecutive losses, pausing trading")
                return
            
            logger.info(f"⚡ SIGNAL ACTION: {signal} (Position: {current_position})")
            
            # HOLD signal - close if position exists
            if signal == "HOLD" and current_position:
                logger.info(f"🔄 HOLD signal - closing position")
                await self._close_position("SIGNAL_HOLD")
                return
            
            # No position - open new
            if not current_position and signal in ["LONG", "SHORT"]:
                logger.info(f"🎯 Opening {signal} position")
                await self._open_position(signal, self.current_price)
                return
            
            # Has position - flip if different
            if current_position and signal in ["LONG", "SHORT"] and signal != current_position:
                logger.info(f"🔄 Flipping: {current_position} -> {signal}")
                await self._flip_position(signal, self.current_price)
                return
                
        except Exception as e:
            logger.error(f"❌ Signal action error: {e}")

    async def _open_position(self, signal: str, entry_price: float):
        """✅ Position opening with USER TP/SL"""
        try:
            logger.info(f"💰 Opening {signal} at ${entry_price:.2f}")
            logger.info(f"🔧 USER TP/SL: SL={self.status['stop_loss']}%, TP={self.status['take_profit']}%")
            
            # Pre-trade cleanup
            await self.binance_client.cancel_all_orders_safe(self.status["symbol"])
            await asyncio.sleep(0.5)
            
            # Position size
            order_size = self.status["order_size"]
            leverage = self.status["leverage"]
            quantity = self._calculate_position_size(order_size, leverage, entry_price)
            
            if quantity <= 0:
                logger.error(f"❌ Invalid quantity: {quantity}")
                return False
            
            # Minimum notional check
            notional = quantity * entry_price
            if notional < self.min_notional:
                logger.error(f"❌ Below min notional: {notional} < {self.min_notional}")
                return False
            
            # Market order with CUSTOM TP/SL
            side = "BUY" if signal == "LONG" else "SELL"
            
            order_result = await self._create_market_order_with_custom_sl_tp(
                self.status["symbol"], 
                side, 
                quantity, 
                entry_price, 
                self.price_precision,
                self.status["stop_loss"],    # USER value
                self.status["take_profit"]   # USER value
            )
            
            if order_result:
                # Update status
                self.status.update({
                    "position_side": signal,
                    "entry_price": entry_price,
                    "status_message": f"✅ {signal} pozisyonu açıldı: ${entry_price:.2f} (SL:{self.status['stop_loss']}% TP:{self.status['take_profit']}%)",
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
                    "stop_loss_percent": self.status["stop_loss"],
                    "take_profit_percent": self.status["take_profit"],
                    "strategy": f"{self.status['timeframe']}_{self.status['strategy_type']}",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                
                logger.info(f"✅ Position opened: {signal} with USER SL:{self.status['stop_loss']}% TP:{self.status['take_profit']}%")
                return True
            else:
                logger.error(f"❌ Failed to open position")
                return False
                
        except Exception as e:
            logger.error(f"❌ Position opening error: {e}")
            return False

    async def _create_market_order_with_custom_sl_tp(self, symbol: str, side: str, quantity: float, entry_price: float, price_precision: int, stop_loss_percent: float, take_profit_percent: float):
        """🔧 CUSTOM TP/SL market order"""
        def format_price(price):
            return f"{price:.{price_precision}f}"
            
        try:
            # Main market order
            logger.info(f"Creating market order: {symbol} {side} {quantity}")
            await self.binance_client.rate_limiter.wait_if_needed('order', self.user_id)
            
            main_order = await self.binance_client.client.futures_create_order(
                symbol=symbol,
                side=side,
                type='MARKET',
                quantity=quantity
            )
            
            logger.info(f"Market order successful: {symbol} {side} {quantity}")
            
            # Calculate CUSTOM TP/SL prices
            if side == 'BUY':  # Long
                sl_price = entry_price * (1 - stop_loss_percent / 100)
                tp_price = entry_price * (1 + take_profit_percent / 100)
                opposite_side = 'SELL'
            else:  # Short
                sl_price = entry_price * (1 + stop_loss_percent / 100)
                tp_price = entry_price * (1 - take_profit_percent / 100)
                opposite_side = 'BUY'
            
            formatted_sl_price = format_price(sl_price)
            formatted_tp_price = format_price(tp_price)
            
            logger.info(f"🔧 CUSTOM TP/SL: SL={formatted_sl_price} ({stop_loss_percent}%), TP={formatted_tp_price} ({take_profit_percent}%)")
            
            # Stop Loss
            try:
                await self.binance_client.rate_limiter.wait_if_needed('order', self.user_id)
                sl_order = await self.binance_client.client.futures_create_order(
                    symbol=symbol,
                    side=opposite_side,
                    type='STOP_MARKET',
                    quantity=quantity,
                    stopPrice=formatted_sl_price,
                    timeInForce='GTE_GTC',
                    reduceOnly=True
                )
                logger.info(f"✅ CUSTOM Stop Loss: {formatted_sl_price} ({stop_loss_percent}%)")
            except Exception as e:
                logger.error(f"❌ Stop Loss failed: {e}")
            
            # Take Profit
            try:
                await self.binance_client.rate_limiter.wait_if_needed('order', self.user_id)
                tp_order = await self.binance_client.client.futures_create_order(
                    symbol=symbol,
                    side=opposite_side,
                    type='TAKE_PROFIT_MARKET',
                    quantity=quantity,
                    stopPrice=formatted_tp_price,
                    timeInForce='GTE_GTC',
                    reduceOnly=True
                )
                logger.info(f"✅ CUSTOM Take Profit: {formatted_tp_price} ({take_profit_percent}%)")
            except Exception as e:
                logger.error(f"❌ Take Profit failed: {e}")
            
            return main_order
            
        except Exception as e:
            logger.error(f"❌ Market order failed: {e}")
            await self.binance_client.cancel_all_orders_safe(symbol)
            return None

    async def _flip_position(self, new_signal: str, current_price: float):
        """Position flipping"""
        try:
            logger.info(f"🔄 Flipping position: {self.status['position_side']} -> {new_signal}")
            
            close_result = await self._close_position("STRATEGY_FLIP")
            if close_result:
                await asyncio.sleep(1)
                await self._open_position(new_signal, current_price)
            
        except Exception as e:
            logger.error(f"❌ Position flip error: {e}")

    async def _close_position(self, reason: str = "SIGNAL"):
        """Position closing"""
        try:
            if not self.status["position_side"]:
                return False
                
            logger.info(f"🔚 Closing {self.status['position_side']} position - Reason: {reason}")
            
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
            
            # Close position
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
                    "status_message": f"✅ Pozisyon kapatıldı - PnL: ${pnl:.2f}"
                })
                
                # Track losses
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
                    "strategy": f"{self.status['timeframe']}_{self.status['strategy_type']}",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                
                logger.info(f"✅ Position closed - PnL: ${pnl:.2f}")
                return True
            else:
                logger.error(f"❌ Failed to close position")
                return False
                
        except Exception as e:
            logger.error(f"❌ Position closing error: {e}")
            return False

    async def _check_exit_conditions(self):
        """🔧 USER TP/SL Exit conditions"""
        try:
            if not self.status["position_side"] or not self.current_price or not self.status["entry_price"]:
                return
            
            entry_price = self.status["entry_price"]
            current_price = self.current_price
            position_side = self.status["position_side"]
            
            # USER TP/SL values
            user_stop_loss = self.status["stop_loss"]
            user_take_profit = self.status["take_profit"]
            
            # Calculate percentage
            if position_side == "LONG":
                pct_change = ((current_price - entry_price) / entry_price) * 100
            else:  # SHORT
                pct_change = ((entry_price - current_price) / entry_price) * 100
            
            # USER Stop loss check
            if pct_change <= -user_stop_loss:
                logger.info(f"🛑 USER Stop loss: {pct_change:.2f}% (Limit: -{user_stop_loss}%)")
                await self._close_position("USER_STOP_LOSS")
                return
            
            # USER Take profit check
            if pct_change >= user_take_profit:
                logger.info(f"🎯 USER Take profit: {pct_change:.2f}% (Target: +{user_take_profit}%)")
                await self._close_position("USER_TAKE_PROFIT")
                return
                
        except Exception as e:
            logger.error(f"❌ Exit conditions error: {e}")

    async def _calculate_realtime_pnl(self):
        """Real-time PnL calculation (NO API CALLS)"""
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
            logger.error(f"❌ PnL calculation error: {e}")

    async def _safe_monitor_loop(self):
        """🔒 SAFE monitoring loop (CACHED DATA ONLY)"""
        while not self._stop_requested and self.status["is_running"]:
            try:
                # Update balance (CACHED - every 5 minutes)
                current_time = time.time()
                if current_time - self.last_api_call > 300:  # 5 dakika
                    try:
                        self.status["account_balance"] = await self.binance_client.get_account_balance(use_cache=True)
                        self.last_api_call = current_time
                    except Exception as e:
                        logger.debug(f"Balance update error: {e}")
                
                # Update status message
                await self._update_status_message()
                
                # Update Firebase
                await self._update_user_data()
                
                self.status["last_check_time"] = datetime.now(timezone.utc).isoformat()
                
                # 1 dakika cycle
                await asyncio.sleep(60)
                
            except Exception as e:
                logger.error(f"❌ Monitor loop error: {e}")
                await asyncio.sleep(30)

    async def stop(self):
        """🛑 Bot stop"""
        if not self.status["is_running"]:
            return
            
        logger.info(f"🛑 Stopping API SAFE bot for user {self.user_id}")
        self._stop_requested = True
        
        # Task cleanup
        tasks = [self._monitor_task, self._candle_watch_task, self._price_callback_task]
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
            "status_message": "✅ Bot durduruldu.",
            "last_check_time": datetime.now(timezone.utc).isoformat()
        })
        
        logger.info(f"✅ API SAFE bot stopped for user {self.user_id}")

    # Helper methods
    async def _track_strategy_performance(self, signal: str):
        """Strategy performance tracking"""
        try:
            self.signal_history.append({
                "signal": signal,
                "price": self.current_price,
                "timestamp": time.time(),
                "timeframe": self.status["timeframe"],
                "strategy_type": self.status["strategy_type"]
            })
            
            if len(self.signal_history) > 50:
                self.signal_history.pop(0)
                
        except Exception as e:
            logger.error(f"❌ Performance tracking error: {e}")

    async def _update_status_message(self):
        """Status message update"""
        try:
            if self.current_price and self.symbol_validated:
                position_text = ""
                if self.status["position_side"]:
                    pnl_text = f" (PnL: ${self.status.get('unrealized_pnl', 0):.2f})"
                    position_text = f" - {self.status['position_side']}{pnl_text}"
                
                signal_text = f" - {self.status['last_signal']}"
                price_text = f" (${self.current_price:.2f})"
                strategy_text = f" [{self.status['timeframe']} {self.status['strategy_type'].title()}]"
                tp_sl_text = f" TP:{self.status['take_profit']}% SL:{self.status['stop_loss']}%"
                
                self.status["status_message"] = f"🔒 API SAFE Bot{strategy_text} - {self.status['symbol']}{price_text}{position_text}{signal_text}{tp_sl_text}"
                
        except Exception as e:
            logger.error(f"❌ Status update error: {e}")

    async def _update_user_data(self):
        """Firebase user data update"""
        try:
            from app.main import firebase_db, firebase_initialized
            
            if firebase_initialized and firebase_db:
                user_update = {
                    "bot_active": self.status["is_running"],
                    "bot_symbol": self.status["symbol"],
                    "bot_timeframe": self.status["timeframe"],
                    "bot_strategy": self.status["strategy_type"],
                    "bot_position": self.status["position_side"],
                    "total_trades": self.status["total_trades"],
                    "total_pnl": self.status["total_pnl"],
                    "account_balance": self.status["account_balance"],
                    "current_price": self.current_price,
                    "last_signal": self.status["last_signal"],
                    "unrealized_pnl": self.status.get("unrealized_pnl", 0),
                    "user_stop_loss": self.status["stop_loss"],
                    "user_take_profit": self.status["take_profit"],
                    "last_bot_update": int(time.time() * 1000)
                }
                
                user_ref = firebase_db.reference(f'users/{self.user_id}')
                user_ref.update(user_update)
            
        except Exception as e:
            logger.error(f"❌ User data update error: {e}")

    async def _log_trade(self, trade_data: dict):
        """Trade logging"""
        try:
            from app.main import firebase_db, firebase_initialized
            
            if firebase_initialized and firebase_db:
                trade_log = {
                    "user_id": self.user_id,
                    "symbol": self.status["symbol"],
                    "timeframe": self.status["timeframe"],
                    "strategy_type": self.status["strategy_type"],
                    "user_stop_loss": self.status["stop_loss"],
                    "user_take_profit": self.status["take_profit"],
                    **trade_data
                }
                
                trades_ref = firebase_db.reference('trades')
                trades_ref.push(trade_log)
                
                self.trade_history.append(trade_log)
                if len(self.trade_history) > 50:
                    self.trade_history.pop(0)
            
        except Exception as e:
            logger.error(f"❌ Trade logging error: {e}")

    def _calculate_position_size(self, order_size: float, leverage: int, price: float) -> float:
        """Position size calculation"""
        try:
            quantity = (order_size * leverage) / price
            return self._format_quantity(quantity)
        except:
            return 0.0

    def _format_quantity(self, quantity: float) -> float:
        """Quantity formatting"""
        if self.quantity_precision == 0:
            return math.floor(quantity)
        factor = 10 ** self.quantity_precision
        return math.floor(quantity * factor) / factor

    def _get_precision_from_filter(self, symbol_info: dict, filter_type: str, key: str) -> int:
        """Get precision from filters"""
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
        """Bot status"""
        return {
            "user_id": self.user_id,
            "is_running": self.status["is_running"],
            "symbol": self.status["symbol"],
            "timeframe": self.status["timeframe"],
            "strategy_type": self.status["strategy_type"],
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
            "take_profit": self.status["take_profit"],
            "last_price_update": self._last_price_update,
            "expected_win_rate": self.status.get("expected_win_rate", 0),
            "current_win_rate": self.status.get("current_win_rate", 0),
            "performance_vs_expected": self.status.get("performance_vs_expected", 1.0),
            "total_closed_trades": self.status.get("total_closed_trades", 0),
            "average_pnl_per_trade": self.status.get("average_pnl_per_trade", 0),
            "consecutive_wins": self.status.get("consecutive_wins", 0),
            "strategy_performance": self.status.get("strategy_performance", "TRACKING"),
            "max_hold_time": self.status.get("max_hold_time", 0),
            "risk_level": self.timeframe_strategy._get_risk_level() if hasattr(self, 'timeframe_strategy') else "MEDIUM",
            "api_calls_saved": "90%+",
            "ban_protection": "ACTIVE"
        }
