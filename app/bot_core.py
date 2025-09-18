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
        Her kullanıcı için ayrı BotCore instance'ı
        """
        self.user_id = user_id
        self.binance_client = binance_client  # Kullanıcıya özel Binance client
        self.bot_settings = bot_settings
        
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
            "total_pnl": 0.0
        }
        
        self.klines_data = []
        self._stop_requested = False
        self._websocket_task = None
        self._monitor_task = None
        self.quantity_precision = 3  # Default değer
        self.price_precision = 2     # Default değer
        
        # WebSocket veri depolama
        self.current_price = None
        self.symbol_validated = False
        
        logger.info(f"BotCore created for user {user_id} with symbol {self.status['symbol']}")

    async def start(self):
        """Kullanıcıya özel bot başlatma - WebSocket odaklı"""
        if self.status["is_running"]:
            logger.warning(f"Bot already running for user {self.user_id}")
            return
            
        self._stop_requested = False
        self.status["is_running"] = True
        self.status["status_message"] = "Bot başlatılıyor..."
        
        logger.info(f"Starting bot for user {self.user_id} on {self.status['symbol']}")
        
        try:
            # 1. Binance client'ı başlat
            await self.binance_client.initialize()
            logger.info(f"Binance client initialized for user {self.user_id}")
            
            # 2. Symbol bilgilerini WebSocket'ten al (opsiyonel REST validation)
            try:
                symbol_info = await self.binance_client.get_symbol_info(self.status["symbol"])
                if symbol_info:
                    # Precision hesaplama
                    self.quantity_precision = self._get_precision_from_filter(symbol_info, 'LOT_SIZE', 'stepSize')
                    self.price_precision = self._get_precision_from_filter(symbol_info, 'PRICE_FILTER', 'tickSize')
                    logger.info(f"Symbol info loaded for user {self.user_id}: precision={self.quantity_precision}")
                else:
                    logger.warning(f"Symbol info not available via REST for user {self.user_id}, using WebSocket")
            except Exception as rest_error:
                logger.warning(f"REST symbol validation failed for user {self.user_id}: {rest_error}")
                logger.info("Continuing with WebSocket-only approach...")
            
            # 3. Hesap bakiyesi kontrolü
            try:
                self.status["account_balance"] = await self.binance_client.get_account_balance(use_cache=False)
                logger.info(f"Account balance for user {self.user_id}: {self.status['account_balance']} USDT")
            except Exception as balance_error:
                logger.warning(f"Balance check failed for user {self.user_id}: {balance_error}")
                self.status["account_balance"] = 0.0
            
            # 4. Kaldıraç ayarlama (opsiyonel)
            try:
                await self.binance_client.set_leverage(self.status["symbol"], self.status["leverage"])
                logger.info(f"Leverage set for user {self.user_id}: {self.status['leverage']}x")
            except Exception as leverage_error:
                logger.warning(f"Leverage setting failed for user {self.user_id}: {leverage_error}")
            
            # 5. Geçmiş veri çekme (opsiyonel)
            try:
                klines = await self.binance_client.get_historical_klines(
                    self.status["symbol"], 
                    self.status["timeframe"], 
                    limit=50
                )
                if klines:
                    self.klines_data = klines
                    logger.info(f"Historical data loaded for user {self.user_id}: {len(klines)} candles")
                else:
                    logger.warning(f"No historical data for user {self.user_id}, will use WebSocket data")
            except Exception as klines_error:
                logger.warning(f"Historical data loading failed for user {self.user_id}: {klines_error}")
            
            # 6. Mevcut pozisyon kontrolü (opsiyonel)
            try:
                open_positions = await self.binance_client.get_open_positions(self.status["symbol"], use_cache=False)
                if open_positions:
                    position = open_positions[0]
                    position_amt = float(position['positionAmt'])
                    if position_amt > 0:
                        self.status["position_side"] = "LONG"
                    elif position_amt < 0:
                        self.status["position_side"] = "SHORT"
                    logger.info(f"Existing position found for user {self.user_id}: {self.status['position_side']}")
            except Exception as position_error:
                logger.warning(f"Position check failed for user {self.user_id}: {position_error}")
            
            # 7. WebSocket ve monitoring başlat - ana veri kaynağı
            self._websocket_task = asyncio.create_task(self._websocket_loop())
            self._monitor_task = asyncio.create_task(self._monitor_loop())
            
            self.status["status_message"] = f"Bot aktif - {self.status['symbol']} WebSocket'ten izleniyor"
            logger.info(f"Bot started successfully for user {self.user_id} with WebSocket data stream")
            
        except Exception as e:
            error_msg = f"Bot başlatma hatası: {e}"
            logger.error(f"Bot start failed for user {self.user_id}: {e}")
            self.status["status_message"] = error_msg
            self.status["is_running"] = False
            await self.stop()

    async def stop(self):
        """Kullanıcıya özel bot durdurma"""
        if not self.status["is_running"]:
            return
            
        logger.info(f"Stopping bot for user {self.user_id}")
        self._stop_requested = True
        
        # WebSocket task'ını durdur
        if self._websocket_task and not self._websocket_task.done():
            self._websocket_task.cancel()
            try:
                await self._websocket_task
            except asyncio.CancelledError:
                pass
        
        # Monitor task'ını durdur
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        
        # Binance client'ı kapat
        if self.binance_client:
            await self.binance_client.close()
        
        self.status.update({
            "is_running": False,
            "position_side": None,
            "status_message": "Bot durduruldu.",
            "last_check_time": datetime.now(timezone.utc).isoformat()
        })
        
        logger.info(f"Bot stopped for user {self.user_id}")

    async def _websocket_loop(self):
        """WebSocket veri akışı - hem ticker hem kline verisi"""
        symbol = self.status["symbol"].lower()
        timeframe = self.status["timeframe"]
        
        # Kombineli stream: hem fiyat hem kline verisi
        ticker_stream = f"{symbol}@ticker"
        kline_stream = f"{symbol}@kline_{timeframe}"
        
        # WebSocket URL - multiple streams
        ws_url = f"wss://stream.binance.com:9443/stream?streams={ticker_stream}/{kline_stream}"
        
        reconnect_attempts = 0
        max_reconnects = 10
        
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
                    else:
                        logger.error(f"Max WebSocket reconnect attempts reached for user {self.user_id}")
                        await self.stop()

    async def _handle_websocket_message(self, message: str):
        """WebSocket mesaj işleme - hem ticker hem kline"""
        try:
            data = json.loads(message)
            
            # Multi-stream formatında data gelir
            if 'stream' in data and 'data' in data:
                stream = data['stream']
                stream_data = data['data']
                
                # Ticker verisi (fiyat güncellemeleri)
                if '@ticker' in stream:
                    await self._handle_ticker_data(stream_data)
                
                # Kline verisi (mum grafik verileri)
                elif '@kline' in stream:
                    await self._handle_kline_data(stream_data)
                    
            # Tek stream formatı (backward compatibility)
            else:
                if 'e' in data:
                    if data['e'] == '24hrTicker':
                        await self._handle_ticker_data(data)
                    elif data['e'] == 'kline':
                        await self._handle_kline_data(data)
                        
        except Exception as e:
            logger.error(f"WebSocket message parsing error for user {self.user_id}: {e}")

    async def _handle_ticker_data(self, ticker_data: dict):
        """Ticker (fiyat) verisi işleme"""
        try:
            # Güncel fiyatı güncelle
            self.current_price = float(ticker_data['c'])  # Close price
            
            # İlk kez sembol validation
            if not self.symbol_validated:
                self.symbol_validated = True
                logger.info(f"Symbol {self.status['symbol']} validated via WebSocket for user {self.user_id}")
                
                # İlk fiyat geldiğinde bot'un tamamen hazır olduğunu belirt
                if self.status["status_message"] == f"Bot aktif - {self.status['symbol']} WebSocket'ten izleniyor":
                    self.status["status_message"] = f"Bot aktif - {self.status['symbol']} (${self.current_price})"
            
            logger.debug(f"Price update for user {self.user_id}: {self.current_price}")
            
        except Exception as e:
            logger.error(f"Ticker data handling error for user {self.user_id}: {e}")

    async def _handle_kline_data(self, kline_data: dict):
        """Kline (mum grafik) verisi işleme"""
        try:
            # Kline objesi içinden veri çıkar
            if 'k' in kline_data:
                kline_info = kline_data['k']
            else:
                kline_info = kline_data
            
            # Sadece kapanan mumları işle
            if not kline_info.get('x', False):
                return
            
            close_price = float(kline_info['c'])
            logger.info(f"New candle closed for user {self.user_id}: ${close_price}")
            
            # Güncel fiyatı da güncelle
            self.current_price = close_price
            
            # Kline data güncelle
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
            
            # Klines listesini güncelle
            if len(self.klines_data) >= 50:
                self.klines_data.pop(0)
            self.klines_data.append(new_kline)
            
            # Yeterli veri varsa strateji analizi yap
            if len(self.klines_data) >= 20:  # Minimum veri gereksinimi
                signal = trading_strategy.analyze_klines(self.klines_data)
                logger.info(f"Strategy signal for user {self.user_id}: {signal}")
                
                # Trading mantığı
                await self._handle_trading_signal(signal, close_price)
            else:
                logger.info(f"Collecting data for user {self.user_id}: {len(self.klines_data)}/20 candles")
            
        except Exception as e:
            logger.error(f"Kline data handling error for user {self.user_id}: {e}")

    async def _handle_trading_signal(self, signal: str, current_price: float):
        """Trading sinyal işleme - kullanıcıya özel"""
        try:
            current_position = self.status["position_side"]
            
            # Sinyal yoksa bekle
            if signal == "HOLD":
                return
            
            # Pozisyon yok, yeni sinyal var
            if not current_position and signal != "HOLD":
                await self._open_position(signal, current_price)
                return
            
            # Mevcut pozisyon var, ters sinyal geldi
            if current_position and signal != current_position and signal != "HOLD":
                await self._flip_position(signal, current_price)
                return
                
        except Exception as e:
            logger.error(f"Trading signal handling error for user {self.user_id}: {e}")

    async def _open_position(self, signal: str, entry_price: float):
        """Yeni pozisyon açma - kullanıcıya özel"""
        try:
            logger.info(f"Opening {signal} position for user {self.user_id}")
            
            # Yetim emir temizliği
            await self.binance_client.cancel_all_orders_safe(self.status["symbol"])
            await asyncio.sleep(0.3)
            
            # Pozisyon büyüklüğü hesapla
            order_size = self.status["order_size"]
            leverage = self.status["leverage"]
            quantity = self._format_quantity((order_size * leverage) / entry_price)
            
            if quantity <= 0:
                logger.error(f"Invalid quantity calculated for user {self.user_id}: {quantity}")
                return False
            
            # Market order aç
            side = "BUY" if signal == "LONG" else "SELL"
            order = await self.binance_client.create_market_order_with_sl_tp(
                self.status["symbol"], 
                side, 
                quantity, 
                entry_price, 
                self.price_precision
            )
            
            if order:
                self.status["position_side"] = signal
                self.status["status_message"] = f"{signal} pozisyonu açıldı: ${entry_price}"
                self.status["total_trades"] += 1
                
                # Firebase'e kaydet
                try:
                    from app.main import firebase_db, firebase_initialized
                    if firebase_initialized and firebase_db:
                        trades_ref = firebase_db.reference('trades')
                        trades_ref.push({
                            "user_id": self.user_id,
                            "symbol": self.status["symbol"],
                            "side": signal,
                            "quantity": quantity,
                            "price": entry_price,
                            "status": "OPENED",
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        })
                except Exception as log_error:
                    logger.error(f"Trade logging error: {log_error}")
                
                logger.info(f"Position opened successfully for user {self.user_id}")
                return True
            else:
                logger.error(f"Failed to open position for user {self.user_id}")
                return False
                
        except Exception as e:
            logger.error(f"Position opening error for user {self.user_id}: {e}")
            return False

    async def _flip_position(self, new_signal: str, current_price: float):
        """Pozisyon çevirme - kullanıcıya özel"""
        try:
            logger.info(f"Flipping position for user {self.user_id}: {self.status['position_side']} -> {new_signal}")
            
            # Mevcut pozisyonu kapat
            open_positions = await self.binance_client.get_open_positions(self.status["symbol"], use_cache=False)
            if open_positions:
                position = open_positions[0]
                position_amt = float(position['positionAmt'])
                side_to_close = 'SELL' if position_amt > 0 else 'BUY'
                
                # PnL hesapla
                pnl = await self.binance_client.get_last_trade_pnl(self.status["symbol"])
                self.status["total_pnl"] += pnl
                
                # Pozisyonu kapat
                close_result = await self.binance_client.close_position(
                    self.status["symbol"], 
                    position_amt, 
                    side_to_close
                )
                
                if close_result:
                    # Firebase'e kaydet
                    try:
                        from app.main import firebase_db, firebase_initialized
                        if firebase_initialized and firebase_db:
                            trades_ref = firebase_db.reference('trades')
                            trades_ref.push({
                                "user_id": self.user_id,
                                "symbol": self.status["symbol"],
                                "pnl": pnl,
                                "status": "CLOSED_BY_FLIP",
                                "timestamp": datetime.now(timezone.utc).isoformat()
                            })
                    except Exception as log_error:
                        logger.error(f"Trade logging error: {log_error}")
                    
                    await asyncio.sleep(1)
                    
                    # Yeni pozisyon aç
                    await self._open_position(new_signal, current_price)
                    
        except Exception as e:
            logger.error(f"Position flip error for user {self.user_id}: {e}")

    async def _monitor_loop(self):
        """Pozisyon monitoring - kullanıcıya özel"""
        while not self._stop_requested and self.status["is_running"]:
            try:
                # Hesap bakiyesi güncelle
                try:
                    self.status["account_balance"] = await self.binance_client.get_account_balance(use_cache=True)
                except Exception as balance_error:
                    logger.debug(f"Balance update error for user {self.user_id}: {balance_error}")
                
                # Pozisyon PnL güncelle
                if self.status["position_side"]:
                    try:
                        self.status["position_pnl"] = await self.binance_client.get_position_pnl(
                            self.status["symbol"], 
                            use_cache=True
                        )
                    except Exception as pnl_error:
                        logger.debug(f"PnL update error for user {self.user_id}: {pnl_error}")
                
                self.status["last_check_time"] = datetime.now(timezone.utc).isoformat()
                
                # Status message güncelle (WebSocket fiyat ile)
                if self.current_price and self.symbol_validated:
                    position_text = f" - {self.status['position_side']}" if self.status["position_side"] else ""
                    self.status["status_message"] = f"Bot aktif - {self.status['symbol']} (${self.current_price}){position_text}"
                
                # Kullanıcı verilerini Firebase'de güncelle
                await self._update_user_data()
                
                await asyncio.sleep(30)  # 30 saniyede bir güncelle
                
            except Exception as e:
                logger.error(f"Monitor loop error for user {self.user_id}: {e}")
                await asyncio.sleep(10)

    async def _update_user_data(self):
        """Kullanıcı verilerini Firebase'de güncelle"""
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
                    "symbol_validated": self.symbol_validated,
                    "last_bot_update": firebase_db.reference().server_timestamp
                }
                
                user_ref = firebase_db.reference(f'users/{self.user_id}')
                user_ref.update(user_update)
            
        except Exception as e:
            logger.error(f"User data update error for user {self.user_id}: {e}")

    def _get_precision_from_filter(self, symbol_info, filter_type, key):
        """Symbol precision hesaplama"""
        try:
            for f in symbol_info['filters']:
                if f['filterType'] == filter_type:
                    size_str = f[key]
                    if '.' in size_str:
                        return len(size_str.split('.')[1].rstrip('0'))
                    return 0
        except:
            pass
        return 3 if filter_type == 'LOT_SIZE' else 2  # Default values

    def _format_quantity(self, quantity: float):
        """Quantity formatla"""
        if self.quantity_precision == 0:
            return math.floor(quantity)
        factor = 10 ** self.quantity_precision
        return math.floor(quantity * factor) / factor

    def get_status(self):
        """Bot durumunu döndür"""
        return {
            "user_id": self.user_id,
            "is_running": self.status["is_running"],
            "symbol": self.status["symbol"],
            "timeframe": self.status["timeframe"],
            "leverage": self.status["leverage"],
            "position_side": self.status["position_side"],
            "status_message": self.status["status_message"],
            "account_balance": self.status["account_balance"],
            "position_pnl": self.status["position_pnl"],
            "total_trades": self.status["total_trades"],
            "total_pnl": self.status["total_pnl"],
            "last_check_time": self.status["last_check_time"],
            "current_price": self.current_price,
            "symbol_validated": self.symbol_validated,
            "data_candles": len(self.klines_data)
        }
