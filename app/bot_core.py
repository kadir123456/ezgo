# app/bot_core.py - Optimize edilmiş versiyon
import asyncio
import json
import math
import time
import traceback
from datetime import datetime, timezone
from typing import Optional, Dict, List
from .config import settings
from .trading_strategy import trading_strategy
from .binance_client import BinanceClient  # Yeni optimize edilmiş client
from .utils.logger import get_logger

logger = get_logger("bot_core")

class BotCore:
    def __init__(self, user_id: str, api_key: str, api_secret: str, bot_settings: dict):
        """
        Optimize edilmiş Trading Bot Core
        WebSocket + Rate Limiting + Shared PriceManager
        """
        self.user_id = user_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.bot_settings = bot_settings
        self._initialized = False
        
        # Yeni optimize edilmiş Binance client ✅
        self.binance_client = BinanceClient(
            api_key=api_key,
            api_secret=api_secret, 
            user_id=user_id  # Rate limiting için
        )
        
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
        
        # Task management - WebSocket kaldırıldı ✅
        self._stop_requested = False
        self._monitor_task = None
        self._strategy_task = None
        self._kline_task = None
        self._price_callback_task = None
        
        # Trading controls - EMA Crossover için optimize edildi
        self.last_trade_time = 0
        self.min_trade_interval = 30  # 30 saniye (EMA crossover için)
        self.consecutive_losses = 0
        self.max_consecutive_losses = 3
        
        # Performance tracking
        self.trade_history = []
        
        # Price callback tracking
        self._last_price_update = 0
        
        logger.info(f"Optimized BotCore created for user {user_id} with symbol {self.status['symbol']}")

    async def start(self):
        """Bot başlatma - optimize edilmiş versiyon"""
        if self.status["is_running"]:
            logger.warning(f"Bot already running for user {self.user_id}")
            return
            
        self._stop_requested = False
        self.status["is_running"] = True
        self.status["status_message"] = "Bot başlatılıyor..."
        
        logger.info(f"Starting optimized bot for user {self.user_id} on {self.status['symbol']}")
        
        try:
            # 1. Binance client initialization ✅
            await self._initialize_binance_client()
            
            # 2. Subscribe to WebSocket price feed ✅
            await self._subscribe_to_price_feed()
            
            # 3. Symbol validation
            await self._setup_symbol_info()
            
            # 4. Account validation
            await self._validate_account()
            
            # 5. Cleanup existing orders
            await self._cleanup_existing_orders()
            
            # 6. Load historical data ✅
            await self._load_historical_data()
            
            # 7. Start optimized components ✅
            await self._start_optimized_components()
            
            self.status["status_message"] = f"✅ EMA Bot aktif - {self.status['symbol']} (Optimize WebSocket)"
            self._initialized = True
            logger.info(f"✅ Optimized bot started successfully for user {self.user_id}")
            
        except Exception as e:
            error_msg = f"Bot başlatma hatası: {e}"
            logger.error(f"Bot start failed for user {self.user_id}: {e}")
            logger.error(traceback.format_exc())
            self.status["status_message"] = error_msg
            self.status["is_running"] = False
            await self.stop()

    async def _initialize_binance_client(self):
        """Yeni BinanceClient başlatma ✅"""
        try:
            init_result = await self.binance_client.initialize()
            if not init_result:
                raise Exception("Optimized BinanceClient initialization failed")
            logger.info(f"✅ Optimized Binance client initialized for user {self.user_id}")
        except Exception as e:
            raise Exception(f"Optimized BinanceClient initialization failed: {e}")

    async def _subscribe_to_price_feed(self):
        """WebSocket price feed'e abone ol ✅"""
        try:
            # Shared PriceManager kullanarak abone ol
            await self.binance_client.subscribe_to_symbol(self.status["symbol"])
            logger.info(f"✅ Subscribed to shared WebSocket for {self.status['symbol']} - user {self.user_id}")
        except Exception as e:
            logger.error(f"❌ Price feed subscription failed for user {self.user_id}: {e}")
            raise

    async def _setup_symbol_info(self):
        """Symbol bilgileri setup - aynı kalıyor"""
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
                logger.info(f"Symbol {self.status['symbol']} configured for user {self.user_id} - qty_precision: {self.quantity_precision}, price_precision: {self.price_precision}")
            else:
                logger.warning(f"Symbol info not available for user {self.user_id}, using defaults")
                
        except Exception as e:
            logger.warning(f"Symbol setup failed for user {self.user_id}: {e}")

    async def _validate_account(self):
        """Account validation - aynı kalıyor"""
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
        """Mevcut orderları temizle - aynı kalıyor"""
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
        """Historical data loading - optimize edildi ✅"""
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
                logger.info(f"✅ Historical data loaded for user {self.user_id}: {len(klines)} candles, signal: {signal}")
            else:
                logger.warning(f"❌ Insufficient historical data for user {self.user_id}")
                
        except Exception as e:
            logger.error(f"❌ Historical data loading failed for user {self.user_id}: {e}")

    async def _start_optimized_components(self):
        """Optimize edilmiş component'ları başlat ✅"""
        # WebSocket kaldırıldı - artık shared PriceManager kullanıyor ✅
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        self._strategy_task = asyncio.create_task(self._strategy_loop()) 
        self._kline_task = asyncio.create_task(self._kline_data_loop())  # Yeni: Periodic kline update
        self._price_callback_task = asyncio.create_task(self._price_update_loop())  # Yeni: Price monitoring
        
        logger.info(f"✅ Optimized components started for user {self.user_id}")

    async def _price_update_loop(self):
        """WebSocket'ten gelen fiyat güncellemelerini izle ✅"""
        logger.info(f"📈 Price monitoring started for user {self.user_id}")
        
        while not self._stop_requested and self.status["is_running"]:
            try:
                # Shared PriceManager'dan fiyat al ✅
                current_price = await self.binance_client.get_market_price(self.status["symbol"])
                
                if current_price and current_price != self.current_price:
                    self.current_price = current_price
                    self.status["current_price"] = current_price
                    self._last_price_update = time.time()
                    
                    # Symbol validation
                    if not self.symbol_validated:
                        self.symbol_validated = True
                        logger.info(f"✅ Symbol {self.status['symbol']} validated via WebSocket for user {self.user_id}")
                    
                    # Real-time PnL calculation
                    if self.status["position_side"] and self.status["entry_price"]:
                        await self._calculate_realtime_pnl()
                    
                    # Log price update every 30 seconds
                    if int(time.time()) % 30 == 0:
                        logger.debug(f"📊 Price update for user {self.user_id}: {self.status['symbol']} = ${current_price:.2f}")
                
                await asyncio.sleep(2)  # Check every 2 seconds
                
            except Exception as e:
                logger.error(f"❌ Price update loop error for user {self.user_id}: {e}")
                await asyncio.sleep(5)

    async def _kline_data_loop(self):
        """Periodic kline data update ✅"""
        logger.info(f"📊 Kline data loop started for user {self.user_id}")
        
        while not self._stop_requested and self.status["is_running"]:
            try:
                # Her 1 dakikada bir kline verisini güncelle (timeframe'e göre ayarlanabilir)
                if self.status["timeframe"] == "1m":
                    interval = 60  # 1 dakika
                elif self.status["timeframe"] == "5m":
                    interval = 300  # 5 dakika  
                elif self.status["timeframe"] == "15m":
                    interval = 900  # 15 dakika
                else:
                    interval = 300  # Default 5 dakika
                
                # Kline verisini güncelle
                await self._update_kline_data()
                
                await asyncio.sleep(interval)
                
            except Exception as e:
                logger.error(f"❌ Kline data loop error for user {self.user_id}: {e}")
                await asyncio.sleep(60)

    async def _update_kline_data(self):
        """Kline verisini güncelle ✅"""
        try:
            # Son 2 kline'ı al (current + previous)
            recent_klines = await self.binance_client.get_historical_klines(
                self.status["symbol"],
                self.status["timeframe"],
                limit=2
            )
            
            if recent_klines and len(recent_klines) >= 1:
                latest_kline = recent_klines[-1]
                
                # Son kline'ı güncelle veya ekle
                if len(self.klines_data) > 0:
                    # Son kline'ın timestamp'ini kontrol et
                    last_kline_time = int(self.klines_data[-1][0])
                    new_kline_time = int(latest_kline[0])
                    
                    if new_kline_time > last_kline_time:
                        # Yeni kline - ekle
                        if len(self.klines_data) >= 100:
                            self.klines_data.pop(0)
                        self.klines_data.append(latest_kline)
                        
                        close_price = float(latest_kline[4])
                        logger.info(f"📊 New candle for user {self.user_id}: {self.status['symbol']} closed at ${close_price:.2f}")
                        
                        # Strategy analizi yap
                        if len(self.klines_data) >= 25:
                            signal = trading_strategy.analyze_klines(self.klines_data)
                            if signal != self.status["last_signal"]:
                                logger.info(f"🔄 EMA Strategy signal changed for user {self.user_id}: {self.status['last_signal']} -> {signal}")
                                self.status["last_signal"] = signal
                            
                    elif new_kline_time == last_kline_time:
                        # Aynı kline - güncelle (current kline)
                        self.klines_data[-1] = latest_kline
                else:
                    # İlk kline
                    self.klines_data.append(latest_kline)
                    
        except Exception as e:
            logger.error(f"❌ Kline data update error for user {self.user_id}: {e}")

    async def _calculate_realtime_pnl(self):
        """Real-time PnL calculation - aynı kalıyor"""
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
            logger.error(f"❌ PnL calculation error for user {self.user_id}: {e}")

    async def stop(self):
        """Bot durdurma - optimize edildi ✅"""
        if not self.status["is_running"]:
            return
            
        logger.info(f"🛑 Stopping optimized bot for user {self.user_id}")
        self._stop_requested = True
        
        # Task cleanup - optimize edildi ✅
        tasks = [self._monitor_task, self._strategy_task, self._kline_task, self._price_callback_task]
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
        
        logger.info(f"✅ Optimized bot stopped for user {self.user_id}")

    # WebSocket loop kaldırıldı - artık gerekli değil ✅

    async def _strategy_loop(self):
        """Main strategy execution loop - EMA Crossover için optimize edildi"""
        logger.info(f"📈 EMA Crossover strategy loop started for user {self.user_id}")
        
        while not self._stop_requested and self.status["is_running"]:
            try:
                if len(self.klines_data) >= 25 and self.current_price:  # EMA21 + buffer
                    await self._execute_trading_strategy()
                
                await asyncio.sleep(10)  # 10 saniye interval (EMA için)
                
            except Exception as e:
                logger.error(f"❌ Strategy loop error for user {self.user_id}: {e}")
                await asyncio.sleep(30)

    async def _execute_trading_strategy(self):
        """EMA Crossover trading strategy execution - aynı kalıyor"""
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
            
            logger.debug(f"📊 EMA Strategy execution for user {self.user_id}: Signal={signal}, Position={current_position}")
            
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
            logger.error(f"❌ EMA trading strategy execution error for user {self.user_id}: {e}")

    async def _open_position(self, signal: str, entry_price: float):
        """EMA Crossover position opening - aynı kalıyor"""
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
            
            # Place market order using optimized client ✅
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
        """EMA Crossover position flipping - aynı kalıyor"""
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
        """Position closing - aynı kalıyor"""
        try:
            if not self.status["position_side"]:
                return False
                
            logger.info(f"🔚 Closing {self.status['position_side']} position for user {self.user_id} - Reason: {reason}")
            
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
            
            # Close position using optimized client ✅
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
                
                logger.info(f"✅ Position closed for user {self.user_id} - PnL: ${pnl:.2f}")
                return True
            else:
                logger.error(f"❌ Failed to close position for user {self.user_id}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Position closing error for user {self.user_id}: {e}")
            return False

    async def _check_exit_conditions(self):
        """Exit conditions check - aynı kalıyor"""
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
                logger.info(f"🛑 Stop loss triggered for user {self.user_id}: {pct_change:.2f}%")
                await self._close_position("STOP_LOSS")
                return
            
            # Take profit check
            if pct_change >= self.status["take_profit"]:
                logger.info(f"🎯 Take profit triggered for user {self.user_id}: {pct_change:.2f}%")
                await self._close_position("TAKE_PROFIT")
                return
                
        except Exception as e:
            logger.error(f"❌ Exit conditions check error for user {self.user_id}: {e}")

    async def _monitor_loop(self):
        """Monitoring loop - optimize edildi"""
        while not self._stop_requested and self.status["is_running"]:
            try:
                # Update account balance (daha az sıklıkla)
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
                logger.error(f"❌ Monitor loop error for user {self.user_id}: {e}")
                await asyncio.sleep(10)

    async def _update_status_message(self):
        """Update status message - optimize edildi"""
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
            logger.error(f"❌ Status message update error for user {self.user_id}: {e}")

    async def _update_user_data(self):
        """Update user data in Firebase - aynı kalıyor"""
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
                    "last_bot_update": int(time.time() * 1000)
                }
                
                user_ref = firebase_db.reference(f'users/{self.user_id}')
                user_ref.update(user_update)
            
        except Exception as e:
            logger.error(f"❌ User data update error for user {self.user_id}: {e}")

    async def _log_trade(self, trade_data: dict):
        """Log trade to Firebase - aynı kalıyor"""
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
            logger.error(f"❌ Trade logging error for user {self.user_id}: {e}")

    def _calculate_position_size(self, order_size: float, leverage: int, price: float) -> float:
        """Calculate position size with precision - aynı kalıyor"""
        try:
            quantity = (order_size * leverage) / price
            return self._format_quantity(quantity)
        except:
            return 0.0

    def _format_quantity(self, quantity: float) -> float:
        """Format quantity with proper precision - aynı kalıyor"""
        if self.quantity_precision == 0:
            return math.floor(quantity)
        factor = 10 ** self.quantity_precision
        return math.floor(quantity * factor) / factor

    def _get_precision_from_filter(self, symbol_info: dict, filter_type: str, key: str) -> int:
        """Get precision from symbol filters - aynı kalıyor"""
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
        """Get comprehensive bot status - aynı kalıyor"""
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
            "take_profit": self.status["take_profit"],
            "last_price_update": self._last_price_update
        }
