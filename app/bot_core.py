# app/bot_core.py - UPDATED: %90 Bakiye + Kullanıcı Tutarı Desteği
import asyncio
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
        🎯 %90 BAKİYE + KULLANICI TUTARI DESTEĞİ
        - order_size = 0 → Bakiyenin %90'ını kullan
        - order_size > 0 → Kullanıcının belirlediği tutarı kullan
        - EMA9 x EMA21 crossover stratejisi
        """
        self.user_id = user_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.bot_settings = bot_settings
        self._initialized = False
        
        # ✅ Simple EMA Binance client
        self.binance_client = BinanceClient(
            api_key=api_key,
            api_secret=api_secret, 
            user_id=user_id
        )
        
        # ✅ BASİT EMA STRATEJİSİ
        timeframe = bot_settings.get("timeframe", "15m")
        self.simple_ema_strategy = create_strategy_for_timeframe(timeframe)
        risk_params = self.simple_ema_strategy.get_risk_params()
        
        # 🔥 YENİ: Order size mode kontrolü
        raw_order_size = bot_settings.get("order_size", 35.0)
        self.use_percentage_mode = (raw_order_size == 0)  # 0 ise %90 modu
        self.percentage_to_use = 90  # %90 kullan
        self.fixed_order_size = raw_order_size if raw_order_size > 0 else 35.0
        
        # Bot durumu
        self.status = {
            "is_running": False,
            "symbol": bot_settings.get("symbol", "BTCUSDT"),
            "timeframe": timeframe,
            "leverage": bot_settings.get("leverage", 10),
            "order_size": raw_order_size,  # Kullanıcının girdiği değer
            "order_size_mode": "percentage_90" if self.use_percentage_mode else "fixed",
            
            # 🔧 USER TP/SL values
            "stop_loss": bot_settings.get("stop_loss", risk_params["stop_loss_percent"]),
            "take_profit": bot_settings.get("take_profit", risk_params["take_profit_percent"]),
            "max_hold_time": risk_params["max_hold_time_minutes"],
            "min_balance_required": risk_params["min_balance_usdt"],
            "strategy_type": "Simple EMA Crossover",
            "signal_frequency": risk_params["signal_frequency"],
            
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
            "balance_sufficient": True,
            "last_balance_check": 0
        }
        
        # Trading data
        self.klines_data = []
        self.current_price = None
        self.symbol_validated = False
        self.min_notional = 5.0
        self.quantity_precision = 3
        self.price_precision = 2
        
        # ✅ Bakiye kontrol ayarları
        self.min_balance_usdt = risk_params["min_balance_usdt"]  # 20 USDT minimum
        self.balance_check_interval = 120  # 2 dakikada bir bakiye kontrol
        self.last_balance_check = 0
        self.insufficient_balance_count = 0
        self.max_insufficient_balance = 3  # 3 kez yetersiz bakiye = bot dur
        
        # 🎯 SIMPLE Rate Limiting
        self._stop_requested = False
        self._monitor_task = None
        self._candle_watch_task = None
        self._price_callback_task = None
        
        # Trading controls
        self.last_trade_time = 0
        self.min_trade_interval = 60      # 1 dakika min interval
        self.consecutive_losses = 0
        self.max_consecutive_losses = 5
        
        # ✅ SIMPLE API RATE LIMITING
        self.last_api_call = 0
        self.api_call_interval = 15       # 15 saniye
        self.last_kline_fetch = 0
        self.kline_fetch_interval = 300   # 5 dakika (EMA için yeterli)
        
        # Performance tracking
        self.trade_history = []
        self.signal_history = []
        self._last_price_update = 0
        
        # 🕐 SIMPLE CANDLE TIMING
        self.last_candle_time = 0
        self.timeframe_seconds = self._get_timeframe_seconds(timeframe)
        
        logger.info(f"🎯 Simple EMA Bot created for user {user_id}")
        logger.info(f"💰 Min balance required: {self.min_balance_usdt} USDT")
        logger.info(f"📊 Strategy: EMA9 x EMA21 crossover")
        logger.info(f"🔧 USER TP/SL: SL={self.status['stop_loss']}%, TP={self.status['take_profit']}%")
        
        # 🔥 YENİ LOG
        if self.use_percentage_mode:
            logger.info(f"💵 ORDER MODE: %{self.percentage_to_use} of balance (dynamic)")
        else:
            logger.info(f"💵 ORDER MODE: Fixed {self.fixed_order_size} USDT")

    def _get_timeframe_seconds(self, timeframe: str) -> int:
        """Timeframe'i saniyeye çevir"""
        timeframe_map = {
            "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
            "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, 
            "8h": 28800, "12h": 43200, "1d": 86400
        }
        return timeframe_map.get(timeframe, 900)

    async def start(self):
        """🎯 BAKİYE KONTROLÜ + Simple EMA Bot başlatma"""
        if self.status["is_running"]:
            logger.warning(f"Bot already running for user {self.user_id}")
            return
            
        self._stop_requested = False
        self.status["is_running"] = True
        self.status["status_message"] = "🎯 Simple EMA bot başlatılıyor..."
        
        logger.info(f"🎯 Starting Simple EMA bot for user {self.user_id}")
        
        try:
            # 1. Client initialization
            await self._initialize_binance_client()
            
            # 2. İLK BAKİYE KONTROLÜ - ZORUNLU
            if not await self._check_balance_sufficient():
                raise Exception(f"Yetersiz bakiye: {self.status['account_balance']:.2f} USDT < {self.min_balance_usdt} USDT")
            
            # 3. WebSocket subscription
            await self._subscribe_to_price_feed()
            
            # 4. One-time setup
            await self._one_time_setup()
            
            # 5. Load historical data
            await self._load_initial_data()
            
            # 6. Start components
            await self._start_simple_components()
            
            # 🔥 Mode bilgisi status mesajına ekle
            mode_text = f"Mode: %{self.percentage_to_use}" if self.use_percentage_mode else f"Mode: {self.fixed_order_size} USDT"
            
            self.status["status_message"] = f"🎯 Simple EMA Bot aktif - {self.status['symbol']} ({self.status['timeframe']}) - {mode_text}"
            self._initialized = True
            logger.info(f"🎯 Simple EMA bot started for user {self.user_id}")
            
        except Exception as e:
            error_msg = f"Bot başlatma hatası: {e}"
            logger.error(f"❌ Simple EMA bot start failed for user {self.user_id}: {e}")
            self.status["status_message"] = error_msg
            self.status["is_running"] = False
            await self.stop()

    async def _check_balance_sufficient(self) -> bool:
        """💰 BAKİYE YETERLİLİĞİ KONTROLÜ"""
        try:
            current_time = time.time()
            
            # Rate limiting - her çağrıda kontrol etme
            if current_time - self.last_balance_check < self.balance_check_interval:
                return self.status["balance_sufficient"]
            
            # Gerçek bakiye kontrolü
            balance = await self.binance_client.get_account_balance(use_cache=False)
            self.status["account_balance"] = balance
            self.last_balance_check = current_time
            
            # Yeterlilik kontrolü
            if balance < self.min_balance_usdt:
                self.insufficient_balance_count += 1
                self.status["balance_sufficient"] = False
                
                logger.warning(f"💰 YETERSIZ BAKİYE: {balance:.2f} USDT < {self.min_balance_usdt} USDT")
                logger.warning(f"💰 Yetersizlik sayısı: {self.insufficient_balance_count}/{self.max_insufficient_balance}")
                
                # 3 kez üst üste yetersiz bakiye = bot dur
                if self.insufficient_balance_count >= self.max_insufficient_balance:
                    logger.error(f"💰 Bot durduruluyor: {self.max_insufficient_balance} kez yetersiz bakiye")
                    await self._stop_due_to_insufficient_balance()
                    return False
                
                return False
            else:
                # Bakiye yeterli
                if not self.status["balance_sufficient"]:
                    logger.info(f"💰 Bakiye yeterli hale geldi: {balance:.2f} USDT")
                
                self.status["balance_sufficient"] = True
                self.insufficient_balance_count = 0  # Reset counter
                return True
                
        except Exception as e:
            logger.error(f"💰 Bakiye kontrolü hatası: {e}")
            return False

    async def _stop_due_to_insufficient_balance(self):
        """💰 Yetersiz bakiye nedeniyle bot durdur"""
        try:
            # Mevcut pozisyonu kapat
            if self.status["position_side"]:
                await self._close_position("INSUFFICIENT_BALANCE")
            
            # Bot durumunu güncelle
            self.status["is_running"] = False
            self.status["status_message"] = f"💰 Bot durduruldu: Yetersiz bakiye ({self.status['account_balance']:.2f} USDT < {self.min_balance_usdt} USDT)"
            
            # Firebase güncelle
            await self._update_user_data()
            
            # Bot'u tamamen durdur
            await self.stop()
            
            logger.info(f"💰 Bot stopped due to insufficient balance for user {self.user_id}")
            
        except Exception as e:
            logger.error(f"💰 Error stopping bot due to insufficient balance: {e}")

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
        """🔌 WebSocket subscription"""
        try:
            await self.binance_client.subscribe_to_symbol(self.status["symbol"])
            logger.info(f"✅ WebSocket subscribed for {self.status['symbol']} - user {self.user_id}")
        except Exception as e:
            logger.error(f"❌ WebSocket subscription failed: {e}")
            raise

    async def _one_time_setup(self):
        """🔧 One-time setup"""
        try:
            # Symbol info
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
            
            # Leverage setting
            await self.binance_client.set_leverage(self.status["symbol"], self.status["leverage"])
            
            # Clean existing orders
            await self.binance_client.cancel_all_orders_safe(self.status["symbol"])
            
            # Check existing position
            await self._check_existing_position()
            
        except Exception as e:
            logger.error(f"One-time setup failed: {e}")

    async def _check_existing_position(self):
        """Mevcut pozisyon kontrolü"""
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
        """📊 Initial data loading - Simple EMA için"""
        try:
            # EMA21 için en az 25 mum gerekli
            required_klines = 30
            
            klines = await self.binance_client.get_historical_klines(
                self.status["symbol"], 
                self.status["timeframe"], 
                limit=required_klines
            )
            
            if klines and len(klines) > 25:
                self.klines_data = klines
                signal = self.simple_ema_strategy.analyze_klines(self.klines_data)
                self.status["last_signal"] = signal
                
                # Son mum zamanını kaydet
                if klines:
                    self.last_candle_time = int(klines[-1][0])
                
                logger.info(f"✅ Simple EMA data loaded: {len(klines)} candles, signal: {signal}")
            else:
                logger.warning(f"❌ Insufficient historical data")
                
        except Exception as e:
            logger.error(f"❌ Initial data loading failed: {e}")

    async def _start_simple_components(self):
        """🎯 Simple components başlatma"""
        # 1. Price monitoring
        self._price_callback_task = asyncio.create_task(self._simple_price_monitoring())
        
        # 2. Candle monitoring
        self._candle_watch_task = asyncio.create_task(self._simple_candle_monitor())
        
        # 3. General monitoring (balance check included)
        self._monitor_task = asyncio.create_task(self._simple_monitor_loop())
        
        logger.info(f"🎯 Simple components started for user {self.user_id}")

    async def _simple_price_monitoring(self):
        """🎯 Simple price monitoring"""
        logger.info(f"🎯 Simple price monitoring started for user {self.user_id}")
        
        while not self._stop_requested and self.status["is_running"]:
            try:
                # WebSocket fiyat al
                current_price = await self.binance_client.get_market_price(self.status["symbol"])
                
                if current_price and current_price != self.current_price:
                    self.current_price = current_price
                    self.status["current_price"] = current_price
                    self._last_price_update = time.time()
                    
                    # Real-time PnL calculation
                    if self.status["position_side"] and self.status["entry_price"]:
                        await self._calculate_realtime_pnl()
                    
                    # Exit conditions check
                    if self.status["position_side"]:
                        await self._check_exit_conditions()
                
                # 10 saniyede bir kontrol
                await asyncio.sleep(10)
                
            except Exception as e:
                logger.error(f"❌ Simple price monitoring error: {e}")
                await asyncio.sleep(20)

    async def _simple_candle_monitor(self):
        """🎯 Simple candle monitor - EMA için"""
        logger.info(f"🎯 Simple candle monitor started for {self.status['timeframe']}")
        
        while not self._stop_requested and self.status["is_running"]:
            try:
                current_time = int(time.time() * 1000)
                
                # Bir sonraki mum kapanışını hesapla
                next_candle_close = self._calculate_next_candle_close(current_time)
                wait_time = (next_candle_close - current_time) / 1000
                
                # En fazla 30 dakika bekle
                wait_time = min(max(wait_time, 10), 1800)
                
                logger.info(f"⏰ Simple: Waiting {wait_time:.0f}s for next {self.status['timeframe']} candle")
                await asyncio.sleep(wait_time)
                
                # Rate limit kontrolü
                current_time = time.time()
                if current_time - self.last_kline_fetch < self.kline_fetch_interval:
                    continue
                
                # Yeni mum verisi al
                await self._fetch_simple_candle_data()
                self.last_kline_fetch = current_time
                
            except Exception as e:
                logger.error(f"❌ Simple candle monitor error: {e}")
                await asyncio.sleep(30)

    def _calculate_next_candle_close(self, current_time_ms: int) -> int:
        """Bir sonraki mum kapanışını hesapla"""
        try:
            timeframe_ms = self.timeframe_seconds * 1000
            current_candle_start = (current_time_ms // timeframe_ms) * timeframe_ms
            next_candle_start = current_candle_start + timeframe_ms
            return next_candle_start
        except Exception as e:
            logger.error(f"Next candle calculation error: {e}")
            return current_time_ms + (self.timeframe_seconds * 1000)

    async def _fetch_simple_candle_data(self):
        """🎯 Simple candle fetch - EMA için"""
        try:
            logger.info(f"🎯 Simple {self.status['timeframe']} candle fetch for user {self.user_id}")
            
            # Son 2 mumu al
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
                if len(self.klines_data) >= 50:
                    self.klines_data.pop(0)
                
                self.klines_data.append(latest_kline)
                self.last_candle_time = new_candle_time
                
                close_price = float(latest_kline[4])
                logger.info(f"📊 NEW Simple {self.status['timeframe']} candle: ${close_price:.2f}")
                
                # 📈 SIMPLE EMA SİNYAL KONTROL ET
                await self._analyze_and_execute_simple_signal()
                
            else:
                # Aynı mum - güncelle
                if self.klines_data:
                    self.klines_data[-1] = latest_kline
                    
        except Exception as e:
            logger.error(f"❌ Simple candle fetch error: {e}")

    async def _analyze_and_execute_simple_signal(self):
        """🎯 Simple EMA sinyal analizi"""
        try:
            if len(self.klines_data) < 25:  # EMA21 için gerekli
                logger.info(f"📊 Simple: Need more data: {len(self.klines_data)}/25")
                return
            
            # 🎯 Simple EMA sinyal hesapla
            new_signal = self.simple_ema_strategy.analyze_klines(self.klines_data)
            old_signal = self.status["last_signal"]
            
            if new_signal != old_signal:
                logger.info(f"🎯 SIMPLE EMA SIGNAL CHANGE for user {self.user_id}: {old_signal} -> {new_signal}")
                self.status["last_signal"] = new_signal
                
                # 🎯 Simple trading action
                await self._execute_simple_signal_action(new_signal)
                
            else:
                logger.debug(f"📊 Simple: Signal unchanged: {new_signal}")
                
        except Exception as e:
            logger.error(f"❌ Simple signal analysis error: {e}")

    async def _execute_simple_signal_action(self, signal: str):
        """⚡ Simple sinyal action"""
        try:
            current_time = time.time()
            current_position = self.status["position_side"]
            
            # Bakiye kontrolü ZORUNLU
            if not await self._check_balance_sufficient():
                logger.warning(f"💰 Yetersiz bakiye, sinyal atlandı: {signal}")
                return
            
            # Rate limiting check
            if current_time - self.last_trade_time < self.min_trade_interval:
                remaining = self.min_trade_interval - (current_time - self.last_trade_time)
                logger.debug(f"⏰ Simple trade cooldown: {remaining:.0f}s remaining")
                return
            
            # Consecutive losses check
            if self.consecutive_losses >= self.max_consecutive_losses:
                logger.warning(f"⚠️ Max consecutive losses ({self.max_consecutive_losses}), pausing")
                return
            
            logger.info(f"⚡ SIMPLE SIGNAL ACTION: {signal} (Position: {current_position})")
            
            # HOLD signal - close if position exists
            if signal == "HOLD" and current_position:
                logger.info(f"🔄 HOLD signal - closing position")
                await self._close_position("SIMPLE_SIGNAL_HOLD")
                return
            
            # No position - open new
            if not current_position and signal in ["LONG", "SHORT"]:
                logger.info(f"🎯 Opening Simple {signal} position")
                await self._open_position(signal, self.current_price)
                return
            
            # Has position - flip if different
            if current_position and signal in ["LONG", "SHORT"] and signal != current_position:
                logger.info(f"🔄 Simple flip: {current_position} -> {signal}")
                await self._flip_position(signal, self.current_price)
                return
                
        except Exception as e:
            logger.error(f"❌ Simple signal action error: {e}")

    def _calculate_dynamic_order_size(self, balance: float, leverage: int, entry_price: float) -> float:
        """
        🔥 YENİ: Dinamik order size hesaplama
        - %90 bakiye modunda: balance * 0.90 kullan
        - Sabit mod: kullanıcının belirlediği tutarı kullan
        """
        try:
            if self.use_percentage_mode:
                # %90 bakiye kullan
                usable_balance = balance * (self.percentage_to_use / 100.0)
                order_size_usdt = usable_balance
                logger.info(f"💵 DYNAMIC ORDER: {balance:.2f} USDT balance → {order_size_usdt:.2f} USDT (%{self.percentage_to_use})")
            else:
                # Sabit tutar kullan
                order_size_usdt = self.fixed_order_size
                logger.info(f"💵 FIXED ORDER: {order_size_usdt:.2f} USDT (user defined)")
            
            # Quantity hesapla
            quantity = (order_size_usdt * leverage) / entry_price
            formatted_quantity = self._format_quantity(quantity)
            
            logger.info(f"💵 Calculated quantity: {formatted_quantity} (price: {entry_price:.2f}, leverage: {leverage}x)")
            
            return formatted_quantity
            
        except Exception as e:
            logger.error(f"❌ Dynamic order size calculation error: {e}")
            return 0.0

    async def _open_position(self, signal: str, entry_price: float):
        """✅ Simple position opening - UPDATED for %90 balance"""
        try:
            logger.info(f"💰 Simple opening {signal} at ${entry_price:.2f}")
            logger.info(f"🔧 USER TP/SL: SL={self.status['stop_loss']}%, TP={self.status['take_profit']}%")
            
            # Pre-trade cleanup
            await self.binance_client.cancel_all_orders_safe(self.status["symbol"])
            await asyncio.sleep(0.5)
            
            # 🔥 YENİ: Güncel bakiyeyi al
            current_balance = await self.binance_client.get_account_balance(use_cache=False)
            logger.info(f"💰 Current balance: {current_balance:.2f} USDT")
            
            # 🔥 YENİ: Dinamik order size hesapla
            leverage = self.status["leverage"]
            quantity = self._calculate_dynamic_order_size(current_balance, leverage, entry_price)
            
            if quantity <= 0:
                logger.error(f"❌ Invalid quantity: {quantity}")
                return False
            
            # Minimum notional check
            notional = quantity * entry_price
            if notional < self.min_notional:
                logger.error(f"❌ Below min notional: {notional:.2f} < {self.min_notional}")
                return False
            
            # 🎯 Simple Market order with CUSTOM TP/SL
            side = "BUY" if signal == "LONG" else "SELL"
            
            order_result = await self._create_simple_market_order_with_sl_tp(
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
                    "status_message": f"🎯 Simple {signal} opened: ${entry_price:.2f} (SL:{self.status['stop_loss']}% TP:{self.status['take_profit']}%)",
                    "total_trades": self.status["total_trades"] + 1,
                    "last_trade_time": time.time()
                })
                
                self.last_trade_time = time.time()
                
                # Log trade
                await self._log_trade({
                    "action": "SIMPLE_EMA_OPEN",
                    "side": signal,
                    "quantity": quantity,
                    "price": entry_price,
                    "stop_loss_percent": self.status["stop_loss"],
                    "take_profit_percent": self.status["take_profit"],
                    "strategy": f"Simple_EMA_{self.status['timeframe']}",
                    "signal_type": "EMA_CROSSOVER",
                    "balance_at_open": current_balance,
                    "order_mode": "percentage_90" if self.use_percentage_mode else "fixed",
                    "order_size_usdt": quantity * entry_price / leverage,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                
                logger.info(f"🎯 Simple position opened: {signal}")
                return True
            else:
                logger.error(f"❌ Failed to open Simple position")
                return False
                
        except Exception as e:
            logger.error(f"❌ Simple position opening error: {e}")
            return False

    async def _create_simple_market_order_with_sl_tp(self, symbol: str, side: str, quantity: float, entry_price: float, price_precision: int, stop_loss_percent: float, take_profit_percent: float):
        """🎯 Simple CUSTOM TP/SL market order"""
        def format_price(price):
            return f"{price:.{price_precision}f}"
            
        try:
            # Main market order
            logger.info(f"Creating Simple market order: {symbol} {side} {quantity}")
            await self.binance_client.rate_limiter.wait_if_needed('order', self.user_id)
            
            main_order = await self.binance_client.client.futures_create_order(
                symbol=symbol,
                side=side,
                type='MARKET',
                quantity=quantity
            )
            
            logger.info(f"🎯 Simple market order successful: {symbol} {side} {quantity}")
            
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
                logger.info(f"✅ Simple Stop Loss: {formatted_sl_price}")
            except Exception as e:
                logger.error(f"❌ Simple Stop Loss failed: {e}")
            
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
                logger.info(f"✅ Simple Take Profit: {formatted_tp_price}")
            except Exception as e:
                logger.error(f"❌ Simple Take Profit failed: {e}")
            
            return main_order
            
        except Exception as e:
            logger.error(f"❌ Simple market order failed: {e}")
            await self.binance_client.cancel_all_orders_safe(symbol)
            return None

    async def _flip_position(self, new_signal: str, current_price: float):
        """🔄 Simple Position flipping"""
        try:
            logger.info(f"🔄 Simple flipping position: {self.status['position_side']} -> {new_signal}")
            
            close_result = await self._close_position("SIMPLE_STRATEGY_FLIP")
            if close_result:
                await asyncio.sleep(1)
                await self._open_position(new_signal, current_price)
            
        except Exception as e:
            logger.error(f"❌ Simple position flip error: {e}")

    async def _close_position(self, reason: str = "SIGNAL"):
        """🔚 Simple Position closing"""
        try:
            if not self.status["position_side"]:
                return False
                
            logger.info(f"🔚 Simple closing {self.status['position_side']} position - Reason: {reason}")
            
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
                    "status_message": f"🎯 Simple pozisyon kapatıldı - PnL: ${pnl:.2f}"
                })
                
                # Track losses
                if pnl < 0:
                    self.consecutive_losses += 1
                else:
                    self.consecutive_losses = 0
                
                # Log trade
                await self._log_trade({
                    "action": "SIMPLE_EMA_CLOSE",
                    "reason": reason,
                    "pnl": pnl,
                    "price": self.current_price,
                    "strategy": f"Simple_EMA_{self.status['timeframe']}",
                    "balance_after_close": self.status["account_balance"],
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                
                logger.info(f"🎯 Simple position closed - PnL: ${pnl:.2f}")
                return True
            else:
                logger.error(f"❌ Failed to close Simple position")
                return False
                
        except Exception as e:
            logger.error(f"❌ Simple position closing error: {e}")
            return False

    async def _check_exit_conditions(self):
        """🔧 Simple USER TP/SL Exit conditions"""
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
                logger.info(f"🛑 Simple USER Stop loss: {pct_change:.2f}% (Limit: -{user_stop_loss}%)")
                await self._close_position("SIMPLE_USER_STOP_LOSS")
                return
            
            # USER Take profit check
            if pct_change >= user_take_profit:
                logger.info(f"🎯 Simple USER Take profit: {pct_change:.2f}% (Target: +{user_take_profit}%)")
                await self._close_position("SIMPLE_USER_TAKE_PROFIT")
                return
                
        except Exception as e:
            logger.error(f"❌ Simple exit conditions error: {e}")

    async def _calculate_realtime_pnl(self):
        """💰 Simple Real-time PnL calculation"""
        try:
            if self.status["position_side"] and self.current_price and self.status["entry_price"]:
                entry_price = self.status["entry_price"]
                current_price = self.current_price
                leverage = self.status["leverage"]
                
                # 🔥 YENİ: Order size'ı mode'a göre hesapla
                if self.use_percentage_mode:
                    # %90 bakiye kullanıldı
                    order_size = self.status["account_balance"] * (self.percentage_to_use / 100.0)
                else:
                    # Sabit tutar kullanıldı
                    order_size = self.fixed_order_size
                
                if self.status["position_side"] == "LONG":
                    pnl_percentage = ((current_price - entry_price) / entry_price) * 100 * leverage
                else:  # SHORT
                    pnl_percentage = ((entry_price - current_price) / entry_price) * 100 * leverage
                
                unrealized_pnl = (order_size * pnl_percentage) / 100
                self.status["unrealized_pnl"] = unrealized_pnl
                
        except Exception as e:
            logger.error(f"❌ Simple PnL calculation error: {e}")

    async def _simple_monitor_loop(self):
        """🎯 Simple monitoring loop - BALANCE CHECK INCLUDED"""
        while not self._stop_requested and self.status["is_running"]:
            try:
                # 💰 BAKİYE KONTROLÜ - Her 2 dakikada bir
                await self._check_balance_sufficient()
                
                # Update status message
                await self._update_simple_status_message()
                
                # Update Firebase
                await self._update_user_data()
                
                self.status["last_check_time"] = datetime.now(timezone.utc).isoformat()
                
                # 60 saniyede bir döngü
                await asyncio.sleep(60)
                
            except Exception as e:
                logger.error(f"❌ Simple monitor loop error: {e}")
                await asyncio.sleep(30)

    async def stop(self):
        """🛑 Simple Bot stop"""
        if not self.status["is_running"]:
            return
            
        logger.info(f"🛑 Stopping Simple bot for user {self.user_id}")
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
            "status_message": "🎯 Simple Bot durduruldu.",
            "last_check_time": datetime.now(timezone.utc).isoformat()
        })
        
        logger.info(f"✅ Simple bot stopped for user {self.user_id}")

    # Helper methods
    async def _update_simple_status_message(self):
        """🎯 Simple status message"""
        try:
            if self.current_price and self.symbol_validated:
                position_text = ""
                if self.status["position_side"]:
                    pnl_text = f" (PnL: ${self.status.get('unrealized_pnl', 0):.2f})"
                    position_text = f" - {self.status['position_side']}{pnl_text}"
                
                signal_text = f" - {self.status['last_signal']}"
                price_text = f" (${self.current_price:.2f})"
                balance_text = f" Bal: {self.status['account_balance']:.1f} USDT"
                strategy_text = f" [EMA9xEMA21 {self.status['timeframe']}]"
                tp_sl_text = f" TP:{self.status['take_profit']}% SL:{self.status['stop_loss']}%"
                
                # 🔥 YENİ: Mode bilgisi ekle
                mode_text = f" Mode:%{self.percentage_to_use}" if self.use_percentage_mode else f" Mode:{self.fixed_order_size}$"
                
                self.status["status_message"] = f"🎯 Simple Bot{strategy_text} - {self.status['symbol']}{price_text}{position_text}{signal_text}{balance_text}{tp_sl_text}{mode_text}"
                
        except Exception as e:
            logger.error(f"❌ Simple status update error: {e}")

    async def _update_user_data(self):
        """🔥 Simple Firebase user data update"""
        try:
            from app.main import firebase_db, firebase_initialized
            
            if firebase_initialized and firebase_db:
                user_update = {
                    "bot_active": self.status["is_running"],
                    "bot_symbol": self.status["symbol"],
                    "bot_timeframe": self.status["timeframe"],
                    "bot_strategy": "Simple EMA Crossover",
                    "bot_position": self.status["position_side"],
                    "total_trades": self.status["total_trades"],
                    "total_pnl": self.status["total_pnl"],
                    "account_balance": self.status["account_balance"],
                    "current_price": self.current_price,
                    "last_signal": self.status["last_signal"],
                    "unrealized_pnl": self.status.get("unrealized_pnl", 0),
                    "user_stop_loss": self.status["stop_loss"],
                    "user_take_profit": self.status["take_profit"],
                    "min_balance_required": self.min_balance_usdt,
                    "balance_sufficient": self.status["balance_sufficient"],
                    "strategy_type": "simple_ema_crossover",
                    "order_size_mode": self.status["order_size_mode"],  # 🔥 YENİ
                    "order_size": self.status["order_size"],  # 🔥 YENİ
                    "last_bot_update": int(time.time() * 1000)
                }
                
                user_ref = firebase_db.reference(f'users/{self.user_id}')
                user_ref.update(user_update)
            
        except Exception as e:
            logger.error(f"❌ Simple user data update error: {e}")

    async def _log_trade(self, trade_data: dict):
        """📝 Simple Trade logging"""
        try:
            from app.main import firebase_db, firebase_initialized
            
            if firebase_initialized and firebase_db:
                trade_log = {
                    "user_id": self.user_id,
                    "symbol": self.status["symbol"],
                    "timeframe": self.status["timeframe"],
                    "strategy_type": "simple_ema_crossover",
                    "user_stop_loss": self.status["stop_loss"],
                    "user_take_profit": self.status["take_profit"],
                    "min_balance_usdt": self.min_balance_usdt,
                    **trade_data
                }
                
                trades_ref = firebase_db.reference('trades')
                trades_ref.push(trade_log)
                
                self.trade_history.append(trade_log)
                if len(self.trade_history) > 100:
                    self.trade_history.pop(0)
            
        except Exception as e:
            logger.error(f"❌ Simple trade logging error: {e}")

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
        """🎯 Simple Bot status"""
        return {
            "user_id": self.user_id,
            "is_running": self.status["is_running"],
            "symbol": self.status["symbol"],
            "timeframe": self.status["timeframe"],
            "strategy_type": "Simple EMA Crossover",
            "indicators": "EMA9 x EMA21",
            "leverage": self.status["leverage"],
            "position_side": self.status["position_side"],
            "status_message": self.status["status_message"],
            "account_balance": self.status["account_balance"],
            "balance_sufficient": self.status["balance_sufficient"],
            "min_balance_required": self.min_balance_usdt,
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
            "order_size_mode": self.status["order_size_mode"],  # 🔥 YENİ
            "stop_loss": self.status["stop_loss"],
            "take_profit": self.status["take_profit"],
            "last_price_update": self._last_price_update,
            "last_balance_check": self.last_balance_check,
            "insufficient_balance_count": self.insufficient_balance_count,
            
            # Simple EMA specific info
            "strategy_description": "🎯 Simple EMA9 x EMA21 Crossover with %90 Balance Support",
            "filters": "None - Pure crossover signals",
            "balance_monitoring": "Active - Every 2 minutes",
            "auto_stop_on_insufficient_balance": True,
            "percentage_mode": self.use_percentage_mode,  # 🔥 YENİ
            "percentage_value": self.percentage_to_use if self.use_percentage_mode else None  # 🔥 YENİ
        }
