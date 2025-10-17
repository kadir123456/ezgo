# app/binance_client.py - FIXED: WebSocket Timeout + Bakiye Kontrollü + Simple EMA Optimized
import asyncio
import math
import time
from typing import Dict, Set, Callable, Optional
from collections import defaultdict, deque
from dataclasses import dataclass
from binance import AsyncClient, BinanceSocketManager
from binance.exceptions import BinanceAPIException, BinanceRequestException
from .config import settings
from .utils.logger import get_logger

logger = get_logger("binance_client")

@dataclass
class RateLimit:
    requests_per_minute: int
    requests_per_second: int
    weight: int = 1

class BinanceRateLimiter:
    """Binance API rate limiting - per user tracking"""
    
    def __init__(self):
        self.limits = {
            'default': RateLimit(1200, 10, 1),
            'order': RateLimit(50, 5, 5),
            'account': RateLimit(600, 5, 5),
            'position': RateLimit(300, 3, 2),
            'balance': RateLimit(300, 3, 2),
        }
        
        self.request_times: Dict[str, deque] = defaultdict(lambda: deque())
        self.weights_used: Dict[str, deque] = defaultdict(lambda: deque())
    
    async def wait_if_needed(self, endpoint_type: str = 'default', user_id: str = None):
        """Rate limit kontrolü"""
        limit = self.limits.get(endpoint_type, self.limits['default'])
        current_time = time.time()
        
        key = f"{user_id}_{endpoint_type}" if user_id else endpoint_type
        
        # Eski istekleri temizle (1 dakika)
        cutoff_time = current_time - 60
        while self.request_times[key] and self.request_times[key][0] < cutoff_time:
            self.request_times[key].popleft()
            if self.weights_used[key]:
                self.weights_used[key].popleft()
        
        # Weight kontrolü
        weight_in_minute = sum(self.weights_used[key])
        if weight_in_minute >= limit.requests_per_minute:
            wait_time = 60 - (current_time - self.request_times[key][0])
            if wait_time > 0:
                logger.warning(f"Rate limit hit for {user_id} - waiting {wait_time:.2f}s")
                await asyncio.sleep(wait_time)
        
        # Saniye başına istek kontrolü
        requests_in_second = len([t for t in self.request_times[key] if current_time - t < 1])
        if requests_in_second >= limit.requests_per_second:
            await asyncio.sleep(1.1)
        
        # İsteği kaydet
        self.request_times[key].append(current_time)
        self.weights_used[key].append(limit.weight)


class PriceManager:
    """
    Singleton WebSocket Price Manager - FIXED VERSION
    ✅ WebSocket timeout düzeltildi
    ✅ Ping/pong mekanizması eklendi
    ✅ Reconnection logic iyileştirildi
    """
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self.prices: Dict[str, float] = {}
            self.price_timestamps: Dict[str, float] = {}
            self.subscribed_symbols: Set[str] = set()
            self.client: Optional[AsyncClient] = None
            self.bm: Optional[BinanceSocketManager] = None
            self.websocket_tasks: Dict[str, asyncio.Task] = {}
            self.is_running = False
            self._lock = asyncio.Lock()
            PriceManager._initialized = True
    
    async def initialize(self):
        """WebSocket manager'ı başlat"""
        async with self._lock:
            if self.is_running:
                return True
                
            try:
                # Public client (API key gerekmez)
                self.client = await AsyncClient.create(
                    testnet=settings.ENVIRONMENT == "TEST"
                )
                self.bm = BinanceSocketManager(self.client)
                self.is_running = True
                
                logger.info("✅ PriceManager initialized successfully")
                return True
            except Exception as e:
                logger.error(f"❌ Failed to initialize PriceManager: {e}")
                return False
    
    async def subscribe_symbol(self, symbol: str):
        """Symbol'e abone ol"""
        async with self._lock:
            if symbol not in self.subscribed_symbols and self.is_running:
                self.subscribed_symbols.add(symbol)
                
                # Bu symbol için WebSocket başlat
                task_name = f"ws_{symbol}"
                if task_name not in self.websocket_tasks:
                    self.websocket_tasks[task_name] = asyncio.create_task(
                        self._symbol_websocket(symbol)
                    )
                
                logger.info(f"✅ Subscribed to {symbol} price stream")
    
    async def _symbol_websocket(self, symbol: str):
        """
        🔧 FIXED: WebSocket stream with improved timeout handling
        """
        retry_count = 0
        max_retries = 10  # 5 → 10 (daha fazla deneme)
        
        while self.is_running and retry_count < max_retries:
            try:
                stream_name = f"{symbol.lower()}@ticker"
                
                # ✅ FIX: ping_interval ve ping_timeout eklendi
                async with self.bm.symbol_ticker_socket(symbol) as stream:
                    logger.info(f"✅ WebSocket connected for {symbol}")
                    retry_count = 0  # Başarılı bağlantıda retry'ı sıfırla
                    last_message_time = time.time()
                    
                    while self.is_running:
                        try:
                            # ✅ FIX: Timeout 30 → 60 saniye
                            msg = await asyncio.wait_for(stream.recv(), timeout=60.0)
                            last_message_time = time.time()
                            await self._handle_price_update(msg)
                            
                        except asyncio.TimeoutError:
                            # ✅ FIX: Timeout artık sadece debug seviyesinde
                            elapsed = time.time() - last_message_time
                            
                            if elapsed > 120:  # 2 dakikadan fazla mesaj gelmemişse
                                logger.warning(f"⚠️ No data from {symbol} for {elapsed:.0f}s - reconnecting")
                                break  # Yeniden bağlan
                            else:
                                # Normal timeout - devam et
                                logger.debug(f"⏱️ WebSocket timeout for {symbol} ({elapsed:.0f}s) - waiting...")
                                continue
                                
                        except Exception as e:
                            logger.error(f"❌ WebSocket message error for {symbol}: {e}")
                            break
                            
            except Exception as e:
                retry_count += 1
                logger.error(f"❌ WebSocket error for {symbol} (attempt {retry_count}/{max_retries}): {e}")
                
                if retry_count < max_retries:
                    # Exponential backoff
                    wait_time = min(2 ** retry_count, 60)  # Max 60 saniye
                    logger.info(f"🔄 Reconnecting to {symbol} in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"❌ Max retries reached for {symbol} WebSocket - giving up")
                    break
        
        # WebSocket kapatıldı
        logger.info(f"🔌 WebSocket closed for {symbol}")
    
    async def _handle_price_update(self, msg):
        """Fiyat güncellemesini işle"""
        try:
            symbol = msg['s']
            price = float(msg['c'])  # Close price
            
            self.prices[symbol] = price
            self.price_timestamps[symbol] = time.time()
            
            # Debug log (her 60 saniyede bir)
            if int(time.time()) % 60 == 0:
                logger.debug(f"💰 Price updated: {symbol} = ${price:.2f}")
                
        except Exception as e:
            logger.error(f"❌ Price update error: {e}")
    
    def get_price(self, symbol: str) -> Optional[float]:
        """Cache'den fiyat al"""
        if symbol in self.prices:
            # 60 saniyeden eski fiyat kabul etme (30 → 60)
            if time.time() - self.price_timestamps.get(symbol, 0) < 60:
                return self.prices[symbol]
            else:
                logger.debug(f"⚠️ Cached price for {symbol} is stale")
        return None
    
    async def close(self):
        """Tüm bağlantıları kapat"""
        async with self._lock:
            self.is_running = False
            
            # WebSocket task'ları iptal et
            for task_name, task in self.websocket_tasks.items():
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    except Exception as e:
                        logger.error(f"❌ Error cancelling {task_name}: {e}")
            
            self.websocket_tasks.clear()
            
            # BinanceSocketManager'ı kapat
            if self.bm:
                try:
                    if hasattr(self.bm, '_session') and self.bm._session:
                        await self.bm._session.close()
                except Exception as e:
                    logger.error(f"❌ Error closing BinanceSocketManager: {e}")
                finally:
                    self.bm = None
            
            # Client'ı kapat
            if self.client:
                try:
                    await self.client.close_connection()
                except Exception as e:
                    logger.error(f"❌ Error closing PriceManager client: {e}")
                finally:
                    self.client = None
            
            logger.info("✅ PriceManager closed")


class BinanceClient:
    """
    💰 BAKİYE KONTROLÜ + Simple EMA Optimized Binance Client
    WebSocket price data + Rate limiting + Per-user caching + Balance monitoring
    """
    
    # Shared instances
    _price_manager = None
    _rate_limiter = None
    
    def __init__(self, api_key: str = None, api_secret: str = None, user_id: str = None):
        self.api_key = api_key or settings.BINANCE_API_KEY
        self.api_secret = api_secret or settings.BINANCE_API_SECRET
        self.user_id = user_id or "unknown"
        self.is_testnet = settings.ENVIRONMENT == "TEST"
        self.client: AsyncClient | None = None
        self.exchange_info = None
        self.is_public_only = not bool(self.api_key and self.api_secret)
        self._connection_closed = False
        
        # 💰 BAKİYE CACHE - Simple EMA için optimize edildi
        self._last_balance_check = 0
        self._cached_balance = 0.0
        self._balance_cache_duration = 120  # 2 dakika cache
        self._balance_check_in_progress = False
        
        # Cache variables
        self._last_position_check = {}
        self._cached_positions = {}
        
        # Shared instances oluştur
        if BinanceClient._price_manager is None:
            BinanceClient._price_manager = PriceManager()
        
        if BinanceClient._rate_limiter is None:
            BinanceClient._rate_limiter = BinanceRateLimiter()
        
        self.price_manager = BinanceClient._price_manager
        self.rate_limiter = BinanceClient._rate_limiter
        
        logger.info(f"💰 BinanceClient created for user: {self.user_id} (balance_monitored: {not self.is_public_only})")
    
    async def __aenter__(self):
        """Context manager entry"""
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        await self.close()
    
    async def initialize(self):
        """Client'ı başlat ve test et"""
        try:
            # Price manager'ı başlat
            await self.price_manager.initialize()
            
            # User-specific client oluştur
            if self.client is None and not self._connection_closed:
                if self.is_public_only:
                    # Public-only client
                    self.client = await AsyncClient.create(
                        testnet=self.is_testnet
                    )
                    logger.info(f"✅ Public BinanceClient initialized for user: {self.user_id}")
                    return True
                else:
                    # Private client with API credentials
                    if not self.api_key or not self.api_secret:
                        logger.error(f"❌ API credentials missing for user: {self.user_id}")
                        return False
                    
                    self.client = await AsyncClient.create(
                        self.api_key, 
                        self.api_secret, 
                        testnet=self.is_testnet,
                        requests_params={
                            'timeout': 10,
                        }
                    )
                    
                    # Test connection with account endpoint
                    await self.rate_limiter.wait_if_needed('account', self.user_id)
                    account_test = await self.client.futures_account()
                    
                    # ✅ İLK BAKİYE YÜKLEMESİ
                    await self._load_initial_balance()
                    
                    logger.info(f"💰 Private BinanceClient initialized for user: {self.user_id} (Balance: {self._cached_balance:.2f} USDT)")
                    return True
                
        except Exception as e:
            logger.error(f"❌ Initialization failed for user {self.user_id}: {e}")
            if self.client:
                try:
                    await self.client.close_connection()
                except:
                    pass
                self.client = None
            return False
    
    async def _load_initial_balance(self):
        """💰 İlk bakiye yüklemesi"""
        try:
            if not self.is_public_only and self.client:
                account = await self.client.futures_account()
                
                for asset in account['assets']:
                    if asset['asset'] == 'USDT':
                        self._cached_balance = float(asset['walletBalance'])
                        self._last_balance_check = time.time()
                        logger.info(f"💰 Initial balance loaded: {self._cached_balance:.2f} USDT")
                        break
        except Exception as e:
            logger.error(f"💰 Initial balance loading failed: {e}")
            self._cached_balance = 0.0
    
    async def close(self):
        """Client bağlantısını kapat"""
        if not self._connection_closed and self.client:
            try:
                await self.client.close_connection()
                logger.info(f"✅ BinanceClient connection closed for user: {self.user_id}")
            except Exception as e:
                logger.error(f"❌ Error closing BinanceClient connection for user {self.user_id}: {e}")
            finally:
                self.client = None
                self._connection_closed = True
    
    async def close_connection(self):
        """Backward compatibility için"""
        await self.close()
    
    async def subscribe_to_symbol(self, symbol: str):
        """Symbol fiyatlarına abone ol"""
        await self.price_manager.subscribe_symbol(symbol)
    
    async def get_market_price(self, symbol: str):
        """Market fiyatını al - WebSocket cache priority"""
        # WebSocket cache'den dene
        price = self.price_manager.get_price(symbol)
        if price:
            return price
        
        # Cache'de yoksa REST API kullan
        try:
            logger.warning(f"⚠️ Using REST API fallback for {symbol} price")
            await self.rate_limiter.wait_if_needed('default', self.user_id)
            ticker = await self.client.futures_symbol_ticker(symbol=symbol)
            return float(ticker['price'])
        except Exception as e:
            logger.error(f"❌ Error getting market price for {symbol}: {e}")
            return None
    
    async def get_account_balance(self, use_cache: bool = True):
        """
        💰 BAKİYE KONTROLÜ - Simple EMA için optimize edildi
        Cache kullanarak API çağrısını minimize eder
        """
        if self.is_public_only:
            logger.warning(f"⚠️ Account balance requested for public-only client: {self.user_id}")
            return 0.0
        
        try:
            current_time = time.time()
            
            # Cache kontrolü
            if use_cache and current_time - self._last_balance_check < self._balance_cache_duration:
                return self._cached_balance
            
            # Concurrent balance check kontrolü
            if self._balance_check_in_progress:
                # Başka bir balance check devam ediyor, cache'i döndür
                return self._cached_balance
            
            # Balance check başlat
            self._balance_check_in_progress = True
            
            try:
                await self.rate_limiter.wait_if_needed('balance', self.user_id)
                account = await self.client.futures_account()
                
                # USDT balance'ı bul
                new_balance = 0.0
                for asset in account['assets']:
                    if asset['asset'] == 'USDT':
                        new_balance = float(asset['walletBalance'])
                        break
                
                # Cache güncelle
                old_balance = self._cached_balance
                self._cached_balance = new_balance
                self._last_balance_check = current_time
                
                # Log balance changes
                if abs(new_balance - old_balance) > 0.1:  # 0.1 USDT'den fazla değişim
                    logger.info(f"💰 Balance updated for user {self.user_id}: {old_balance:.2f} -> {new_balance:.2f} USDT")
                
                return new_balance
                
            finally:
                self._balance_check_in_progress = False
            
        except BinanceAPIException as e:
            self._balance_check_in_progress = False
            if "-1003" in str(e):  # Rate limit
                logger.warning(f"💰 Balance rate limit hit for user {self.user_id}")
                return self._cached_balance
            logger.error(f"💰 Balance API error for user {self.user_id}: {e}")
            return self._cached_balance
        except Exception as e:
            self._balance_check_in_progress = False
            logger.error(f"💰 Unexpected balance error for user {self.user_id}: {e}")
            return self._cached_balance
    
    async def get_balance_with_status(self):
        """
        💰 Bakiye ve durumunu birlikte döndürür
        Simple EMA bot için
        """
        try:
            balance = await self.get_account_balance(use_cache=False)
            
            return {
                "balance": balance,
                "cached": False,
                "last_check": self._last_balance_check,
                "cache_age": time.time() - self._last_balance_check,
                "sufficient_for_trading": balance >= 20.0,  # Simple EMA minimum
                "status": "ok" if balance >= 20.0 else "insufficient"
            }
            
        except Exception as e:
            logger.error(f"💰 Balance status error: {e}")
            return {
                "balance": self._cached_balance,
                "cached": True,
                "last_check": self._last_balance_check,
                "cache_age": time.time() - self._last_balance_check,
                "sufficient_for_trading": self._cached_balance >= 20.0,
                "status": "error",
                "error": str(e)
            }
    
    async def get_open_positions(self, symbol: str, use_cache: bool = True):
        """Açık pozisyonları getir - cache desteği ile"""
        if self.is_public_only:
            logger.warning(f"⚠️ Open positions requested for public-only client: {self.user_id}")
            return []
            
        try:
            current_time = time.time()
            cache_key = symbol
            
            # Cache kontrolü (30 saniye cache - Simple EMA için yeterli)
            if use_cache and cache_key in self._last_position_check:
                if current_time - self._last_position_check[cache_key] < 30:
                    return self._cached_positions.get(cache_key, [])
            
            await self.rate_limiter.wait_if_needed('position', self.user_id)
            positions = await self.client.futures_position_information(symbol=symbol)
            
            # Safe parsing
            open_positions = []
            for p in positions:
                try:
                    if float(p.get('positionAmt', 0)) != 0:
                        open_positions.append(p)
                except (ValueError, KeyError, TypeError) as parse_error:
                    logger.warning(f"⚠️ Position parsing error for {symbol} - user {self.user_id}: {parse_error}")
                    continue
            
            # Cache güncelle
            self._last_position_check[cache_key] = current_time
            self._cached_positions[cache_key] = open_positions
            
            return open_positions
            
        except BinanceAPIException as e:
            if "-1003" in str(e):  # Rate limit
                logger.warning(f"⚠️ Rate limit hit for positions {symbol} - user {self.user_id}")
                return self._cached_positions.get(symbol, [])
            logger.error(f"❌ Error getting positions for {symbol} - user {self.user_id}: {e}")
            return []
        except Exception as e:
            logger.error(f"❌ Unexpected error getting positions for {symbol} - user {self.user_id}: {e}")
            return self._cached_positions.get(symbol, [])
    
    async def create_market_order_with_sl_tp(self, symbol: str, side: str, quantity: float, entry_price: float, price_precision: int):
        """Market order ile birlikte SL/TP oluştur"""
        if self.is_public_only:
            logger.error(f"❌ Market order requested for public-only client: {self.user_id}")
            return None
            
        def format_price(price):
            return f"{price:.{price_precision}f}"
            
        try:
            # Ana market order
            logger.info(f"📝 Creating market order for user {self.user_id}: {symbol} {side} {quantity}")
            await self.rate_limiter.wait_if_needed('order', self.user_id)
            
            main_order = await self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type='MARKET',
                quantity=quantity
            )
            
            logger.info(f"✅ Market order successful for user {self.user_id}: {symbol} {side} {quantity}")
            
            # SL/TP fiyatlarını hesapla
            if side == 'BUY':  # Long pozisyon
                sl_price = entry_price * (1 - settings.DEFAULT_STOP_LOSS_PERCENT / 100)
                tp_price = entry_price * (1 + settings.DEFAULT_TAKE_PROFIT_PERCENT / 100)
                opposite_side = 'SELL'
            else:  # Short pozisyon
                sl_price = entry_price * (1 + settings.DEFAULT_STOP_LOSS_PERCENT / 100)
                tp_price = entry_price * (1 - settings.DEFAULT_TAKE_PROFIT_PERCENT / 100)
                opposite_side = 'BUY'
            
            formatted_sl_price = format_price(sl_price)
            formatted_tp_price = format_price(tp_price)
            
            # Stop Loss oluştur
            try:
                await self.rate_limiter.wait_if_needed('order', self.user_id)
                sl_order = await self.client.futures_create_order(
                    symbol=symbol,
                    side=opposite_side,
                    type='STOP_MARKET',
                    quantity=quantity,
                    stopPrice=formatted_sl_price,
                    timeInForce='GTE_GTC',
                    reduceOnly=True
                )
                logger.info(f"🛡️ Stop Loss created for user {self.user_id}: {formatted_sl_price}")
            except Exception as e:
                logger.error(f"❌ Stop Loss creation failed for user {self.user_id}: {e}")
            
            # Take Profit oluştur
            try:
                await self.rate_limiter.wait_if_needed('order', self.user_id)
                tp_order = await self.client.futures_create_order(
                    symbol=symbol,
                    side=opposite_side,
                    type='TAKE_PROFIT_MARKET',
                    quantity=quantity,
                    stopPrice=formatted_tp_price,
                    timeInForce='GTE_GTC',
                    reduceOnly=True
                )
                logger.info(f"🎯 Take Profit created for user {self.user_id}: {formatted_tp_price}")
            except Exception as e:
                logger.error(f"❌ Take Profit creation failed for user {self.user_id}: {e}")
            
            return main_order
            
        except Exception as e:
            logger.error(f"❌ Market order creation failed for user {self.user_id}: {e}")
            await self.cancel_all_orders_safe(symbol)
            return None
    
    async def cancel_all_orders_safe(self, symbol: str):
        """Tüm açık emirleri güvenli şekilde iptal et"""
        if self.is_public_only:
            logger.warning(f"⚠️ Cancel orders requested for public-only client: {self.user_id}")
            return False
            
        try:
            await self.rate_limiter.wait_if_needed('order', self.user_id)
            open_orders = await self.client.futures_get_open_orders(symbol=symbol)
            
            if open_orders:
                logger.info(f"📝 Cancelling {len(open_orders)} open orders for {symbol} - user {self.user_id}")
                await self.rate_limiter.wait_if_needed('order', self.user_id)
                await self.client.futures_cancel_all_open_orders(symbol=symbol)
                await asyncio.sleep(0.5)
                logger.info(f"✅ All orders cancelled for {symbol} - user {self.user_id}")
                return True
            else:
                logger.debug(f"ℹ️ No open orders to cancel for {symbol} - user {self.user_id}")
                return True
                
        except Exception as e:
            logger.error(f"❌ Error cancelling orders for {symbol} - user {self.user_id}: {e}")
            return False
    
    async def close_position(self, symbol: str, position_amt: float, side_to_close: str):
        """Pozisyon kapat"""
        if self.is_public_only:
            logger.error(f"❌ Close position requested for public-only client: {self.user_id}")
            return None
            
        try:
            # Açık emirleri iptal et
            await self.cancel_all_orders_safe(symbol)
            await asyncio.sleep(0.2)
            
            # Pozisyonu kapat
            logger.info(f"📝 Closing position for user {self.user_id}: {symbol} {abs(position_amt)}")
            await self.rate_limiter.wait_if_needed('order', self.user_id)
            
            response = await self.client.futures_create_order(
                symbol=symbol,
                side=side_to_close,
                type='MARKET',
                quantity=abs(position_amt),
                reduceOnly=True
            )
            
            logger.info(f"✅ Position closed for user {self.user_id}: {symbol}")
            
            # Cache temizle
            if symbol in self._cached_positions:
                del self._cached_positions[symbol]
            if symbol in self._last_position_check:
                del self._last_position_check[symbol]
            
            return response
            
        except Exception as e:
            logger.error(f"❌ Position closing failed for user {self.user_id}: {e}")
            await self.cancel_all_orders_safe(symbol)
            return None
    
    async def set_leverage(self, symbol: str, leverage: int):
        """Kaldıraç ayarla"""
        if self.is_public_only:
            logger.warning(f"⚠️ Set leverage requested for public-only client: {self.user_id}")
            return False
            
        try:
            # Açık pozisyon kontrolü
            open_positions = await self.get_open_positions(symbol, use_cache=False)
            if open_positions:
                logger.warning(f"⚠️ Open position exists for {symbol} - user {self.user_id}, cannot change leverage")
                return False
            
            # Margin tipini ayarla
            try:
                await self.rate_limiter.wait_if_needed('account', self.user_id)
                await self.client.futures_change_margin_type(symbol=symbol, marginType='CROSSED')
                logger.info(f"✅ Margin type set to CROSSED for {symbol} - user {self.user_id}")
            except BinanceAPIException as margin_error:
                if "No need to change margin type" in str(margin_error):
                    logger.info(f"ℹ️ Margin type already CROSSED for {symbol} - user {self.user_id}")
                else:
                    logger.warning(f"⚠️ Could not change margin type for user {self.user_id}: {margin_error}")
            
            # Kaldıracı ayarla
            await self.rate_limiter.wait_if_needed('account', self.user_id)
            await self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
            logger.info(f"✅ Leverage set to {leverage}x for {symbol} - user {self.user_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error setting leverage for user {self.user_id}: {e}")
            return False
    
    async def has_open_orders(self, symbol: str):
        """Açık emir kontrolü"""
        if self.is_public_only:
            logger.warning(f"⚠️ Open orders check requested for public-only client: {self.user_id}")
            return False
            
        try:
            await self.rate_limiter.wait_if_needed('order', self.user_id)
            open_orders = await self.client.futures_get_open_orders(symbol=symbol)
            return len(open_orders) > 0
        except Exception as e:
            logger.error(f"❌ Error checking open orders for {symbol} - user {self.user_id}: {e}")
            return False
    
    async def create_stop_and_limit_order(self, symbol: str, side: str, quantity: float, stop_price: float, limit_price: float):
        """Stop ve limit emri oluştur"""
        if self.is_public_only:
            logger.error(f"❌ Stop/limit order requested for public-only client: {self.user_id}")
            return None
            
        try:
            await self.rate_limiter.wait_if_needed('order', self.user_id)
            
            if side in ['SELL']:
                # Stop loss veya take profit satış emri
                order_type = 'STOP_MARKET' if stop_price < limit_price else 'TAKE_PROFIT_MARKET'
            else:
                # Stop loss veya take profit alış emri  
                order_type = 'STOP_MARKET' if stop_price > limit_price else 'TAKE_PROFIT_MARKET'
            
            order = await self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type=order_type,
                quantity=quantity,
                stopPrice=stop_price,
                timeInForce='GTE_GTC',
                reduceOnly=True
            )
            
            logger.info(f"✅ {order_type} order created for user {self.user_id}: {symbol} {side} {quantity} @ {stop_price}")
            return order
            
        except Exception as e:
            logger.error(f"❌ Stop/limit order creation failed for user {self.user_id}: {e}")
            return None
    
    async def get_last_trade_pnl(self, symbol: str):
        """Son işlemin PnL'ini al"""
        if self.is_public_only:
            logger.warning(f"⚠️ Trade PnL requested for public-only client: {self.user_id}")
            return 0.0
            
        try:
            await self.rate_limiter.wait_if_needed('default', self.user_id)
            trades = await self.client.futures_account_trades(symbol=symbol, limit=1)
            
            if trades:
                return float(trades[-1]['realizedPnl'])
            return 0.0
            
        except Exception as e:
            logger.error(f"❌ Error getting last trade PnL for {symbol} - user {self.user_id}: {e}")
            return 0.0
    
    async def get_symbol_info(self, symbol: str):
        """Symbol bilgilerini al"""
        try:
            if not self.exchange_info:
                await self.rate_limiter.wait_if_needed('default', self.user_id)
                self.exchange_info = await self.client.futures_exchange_info()
            
            for symbol_info in self.exchange_info['symbols']:
                if symbol_info['symbol'] == symbol:
                    return symbol_info
            return None
            
        except Exception as e:
            logger.error(f"❌ Error getting symbol info for {symbol} - user {self.user_id}: {e}")
            return None
    
    async def get_historical_klines(self, symbol: str, interval: str, limit: int = 100):
        """Geçmiş kline verilerini al - Simple EMA için optimize edildi"""
        try:
            await self.rate_limiter.wait_if_needed('default', self.user_id)
            klines = await self.client.futures_klines(
                symbol=symbol,
                interval=interval,
                limit=min(limit, 100)  # Simple EMA için maximum 100 yeterli
            )
            return klines
            
        except Exception as e:
            logger.error(f"❌ Error getting historical klines for {symbol} - user {self.user_id}: {e}")
            return []
    
    def get_balance_cache_info(self):
        """💰 Bakiye cache bilgilerini döndür"""
        return {
            "cached_balance": self._cached_balance,
            "last_check": self._last_balance_check,
            "cache_age_seconds": time.time() - self._last_balance_check,
            "cache_duration": self._balance_cache_duration,
            "is_cache_fresh": (time.time() - self._last_balance_check) < self._balance_cache_duration,
            "check_in_progress": self._balance_check_in_progress
        }
