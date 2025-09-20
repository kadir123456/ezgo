# app/binance_client.py
import asyncio
import json
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
    Singleton WebSocket Price Manager
    Tüm kullanıcılar için merkezi fiyat yönetimi
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
            PriceManager._initialized = True
    
    async def initialize(self):
        """WebSocket manager'ı başlat"""
        if self.is_running:
            return True
            
        try:
            # Public client (API key gerekmez)
            self.client = await AsyncClient.create(
                testnet=settings.ENVIRONMENT == "TEST"
            )
            self.bm = BinanceSocketManager(self.client)
            self.is_running = True
            
            logger.info("PriceManager initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize PriceManager: {e}")
            return False
    
    async def subscribe_symbol(self, symbol: str):
        """Symbol'e abone ol"""
        if symbol not in self.subscribed_symbols and self.is_running:
            self.subscribed_symbols.add(symbol)
            
            # Bu symbol için WebSocket başlat
            task_name = f"ws_{symbol}"
            if task_name not in self.websocket_tasks:
                self.websocket_tasks[task_name] = asyncio.create_task(
                    self._symbol_websocket(symbol)
                )
            
            logger.info(f"Subscribed to {symbol} price stream")
    
    async def _symbol_websocket(self, symbol: str):
        """Symbol için WebSocket stream"""
        retry_count = 0
        max_retries = 5
        
        while self.is_running and retry_count < max_retries:
            try:
                stream_name = f"{symbol.lower()}@ticker"
                
                async with self.bm.symbol_ticker_socket(symbol) as stream:
                    logger.info(f"WebSocket connected for {symbol}")
                    retry_count = 0  # Reset retry count on successful connection
                    
                    while self.is_running:
                        try:
                            msg = await asyncio.wait_for(stream.recv(), timeout=30)
                            await self._handle_price_update(msg)
                        except asyncio.TimeoutError:
                            logger.warning(f"WebSocket timeout for {symbol}")
                            continue
                        except Exception as e:
                            logger.error(f"WebSocket message error for {symbol}: {e}")
                            break
                            
            except Exception as e:
                retry_count += 1
                logger.error(f"WebSocket error for {symbol} (retry {retry_count}): {e}")
                
                if retry_count < max_retries:
                    wait_time = min(2 ** retry_count, 30)  # Exponential backoff
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Max retries reached for {symbol} WebSocket")
                    break
    
    async def _handle_price_update(self, msg):
        """Fiyat güncellemesini işle"""
        try:
            symbol = msg['s']
            price = float(msg['c'])  # Close price
            
            self.prices[symbol] = price
            self.price_timestamps[symbol] = time.time()
            
            # Debug log (çok sık log olmaması için her 100. güncellemeyi logla)
            if int(time.time()) % 10 == 0:  # Her 10 saniyede bir
                logger.debug(f"Price updated: {symbol} = ${price:.2f}")
                
        except Exception as e:
            logger.error(f"Price update error: {e}")
    
    def get_price(self, symbol: str) -> Optional[float]:
        """Cache'den fiyat al"""
        if symbol in self.prices:
            # 30 saniyeden eski fiyat kabul etme
            if time.time() - self.price_timestamps.get(symbol, 0) < 30:
                return self.prices[symbol]
        return None
    
    async def close(self):
        """Tüm bağlantıları kapat"""
        self.is_running = False
        
        # WebSocket task'ları iptal et
        for task in self.websocket_tasks.values():
            if not task.done():
                task.cancel()
        
        # Client'ı kapat
        if self.client:
            await self.client.close_connection()
        
        logger.info("PriceManager closed")


class BinanceClient:
    """
    Optimize edilmiş Binance Client
    WebSocket price data + Rate limiting + Per-user caching
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
        
        # Cache variables - kullanıcıya özel
        self._last_balance_check = 0
        self._cached_balance = 0.0
        self._last_position_check = {}
        self._cached_positions = {}
        
        # Shared instances oluştur
        if BinanceClient._price_manager is None:
            BinanceClient._price_manager = PriceManager()
        
        if BinanceClient._rate_limiter is None:
            BinanceClient._rate_limiter = BinanceRateLimiter()
        
        self.price_manager = BinanceClient._price_manager
        self.rate_limiter = BinanceClient._rate_limiter
        
        logger.info(f"BinanceClient created for user: {self.user_id}")
    
    async def initialize(self):
        """Client'ı başlat ve test et"""
        try:
            # Price manager'ı başlat
            await self.price_manager.initialize()
            
            # User-specific client oluştur
            if self.client is None:
                self.client = await AsyncClient.create(
                    self.api_key, 
                    self.api_secret, 
                    testnet=self.is_testnet
                )
                
                # Test connection
                await self.rate_limiter.wait_if_needed('account', self.user_id)
                await self.client.futures_account()
                
                logger.info(f"BinanceClient initialized for user: {self.user_id}")
                return True
                
        except Exception as e:
            logger.error(f"Initialization failed for user {self.user_id}: {e}")
            return False
    
    async def subscribe_to_symbol(self, symbol: str):
        """Symbol fiyatlarına abone ol"""
        await self.price_manager.subscribe_symbol(symbol)
    
    async def get_market_price(self, symbol: str):
        """
        Market fiyatını al - Önce WebSocket cache'den, sonra REST API
        """
        # WebSocket cache'den dene
        price = self.price_manager.get_price(symbol)
        if price:
            return price
        
        # Cache'de yoksa REST API kullan (fallback)
        try:
            logger.warning(f"Using REST API fallback for {symbol} price")
            await self.rate_limiter.wait_if_needed('default', self.user_id)
            ticker = await self.client.futures_symbol_ticker(symbol=symbol)
            return float(ticker['price'])
        except Exception as e:
            logger.error(f"Error getting market price for {symbol}: {e}")
            return None
    
    async def get_open_positions(self, symbol: str, use_cache: bool = True):
        """Açık pozisyonları getir - cache desteği ile"""
        try:
            current_time = time.time()
            cache_key = symbol
            
            # Cache kontrolü (5 saniye cache)
            if use_cache and cache_key in self._last_position_check:
                if current_time - self._last_position_check[cache_key] < 40:
                    return self._cached_positions.get(cache_key, [])
            
            await self.rate_limiter.wait_if_needed('position', self.user_id)
            positions = await self.client.futures_position_information(symbol=symbol)
            open_positions = [p for p in positions if float(p['positionAmt']) != 0]
            
            # Cache güncelle
            self._last_position_check[cache_key] = current_time
            self._cached_positions[cache_key] = open_positions
            
            return open_positions
            
        except BinanceAPIException as e:
            if "-1003" in str(e):  # Rate limit
                logger.warning(f"Rate limit hit for positions {symbol} - user {self.user_id}")
                return self._cached_positions.get(symbol, [])
            logger.error(f"Error getting positions for {symbol} - user {self.user_id}: {e}")
            return []
    
    async def create_market_order_with_sl_tp(self, symbol: str, side: str, quantity: float, entry_price: float, price_precision: int):
        """Market order ile birlikte SL/TP oluştur"""
        def format_price(price):
            return f"{price:.{price_precision}f}"
            
        try:
            # Ana market order
            logger.info(f"Creating market order for user {self.user_id}: {symbol} {side} {quantity}")
            await self.rate_limiter.wait_if_needed('order', self.user_id)
            
            main_order = await self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type='MARKET',
                quantity=quantity
            )
            
            logger.info(f"Market order successful for user {self.user_id}: {symbol} {side} {quantity}")
            
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
                logger.info(f"Stop Loss created for user {self.user_id}: {formatted_sl_price}")
            except Exception as e:
                logger.error(f"Stop Loss creation failed for user {self.user_id}: {e}")
            
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
                logger.info(f"Take Profit created for user {self.user_id}: {formatted_tp_price}")
            except Exception as e:
                logger.error(f"Take Profit creation failed for user {self.user_id}: {e}")
            
            return main_order
            
        except Exception as e:
            logger.error(f"Market order creation failed for user {self.user_id}: {e}")
            await self.cancel_all_orders_safe(symbol)
            return None
    
    async def get_account_balance(self, use_cache: bool = True):
        """Hesap bakiyesi getir - cache desteği ile"""
        try:
            current_time = time.time()
            
            # Cache kontrolü (30 saniye cache - balance daha az sıklıkla değişir)
            if use_cache and current_time - self._last_balance_check < 30:
                return self._cached_balance
            
            await self.rate_limiter.wait_if_needed('account', self.user_id)
            account = await self.client.futures_account()
            
            total_balance = 0.0
            for asset in account['assets']:
                if asset['asset'] == 'USDT':
                    total_balance = float(asset['walletBalance'])
                    break
            
            # Cache güncelle
            self._last_balance_check = current_time
            self._cached_balance = total_balance
            
            return total_balance
            
        except BinanceAPIException as e:
            if "-1003" in str(e):
                logger.warning(f"Rate limit hit for balance - user {self.user_id}")
                return self._cached_balance
            logger.error(f"Error getting account balance for user {self.user_id}: {e}")
            return self._cached_balance
    
    # Diğer metodlar aynı kalacak, sadece rate_limiter ve user_id eklenecek
    async def cancel_all_orders_safe(self, symbol: str):
        """Tüm açık emirleri güvenli şekilde iptal et"""
        try:
            await self.rate_limiter.wait_if_needed('order', self.user_id)
            open_orders = await self.client.futures_get_open_orders(symbol=symbol)
            
            if open_orders:
                logger.info(f"Cancelling {len(open_orders)} open orders for {symbol} - user {self.user_id}")
                await self.rate_limiter.wait_if_needed('order', self.user_id)
                await self.client.futures_cancel_all_open_orders(symbol=symbol)
                await asyncio.sleep(0.5)
                logger.info(f"All orders cancelled for {symbol} - user {self.user_id}")
                return True
            else:
                logger.info(f"No open orders to cancel for {symbol} - user {self.user_id}")
                return True
                
        except Exception as e:
            logger.error(f"Error cancelling orders for {symbol} - user {self.user_id}: {e}")
            return False
    
    async def close_position(self, symbol: str, position_amt: float, side_to_close: str):
        """Pozisyon kapat"""
        try:
            # Açık emirleri iptal et
            await self.cancel_all_orders_safe(symbol)
            await asyncio.sleep(0.2)
            
            # Pozisyonu kapat
            logger.info(f"Closing position for user {self.user_id}: {symbol} {abs(position_amt)}")
            await self.rate_limiter.wait_if_needed('order', self.user_id)
            
            response = await self.client.futures_create_order(
                symbol=symbol,
                side=side_to_close,
                type='MARKET',
                quantity=abs(position_amt),
                reduceOnly=True
            )
            
            logger.info(f"Position closed for user {self.user_id}: {symbol}")
            
            # Cache temizle
            if symbol in self._cached_positions:
                del self._cached_positions[symbol]
            if symbol in self._last_position_check:
                del self._last_position_check[symbol]
            
            return response
            
        except Exception as e:
            logger.error(f"Position closing failed for user {self.user_id}: {e}")
            await self.cancel_all_orders_safe(symbol)
            return None
    
    async def set_leverage(self, symbol: str, leverage: int):
        """Kaldıraç ayarla"""
        try:
            # Açık pozisyon kontrolü
            open_positions = await self.get_open_positions(symbol, use_cache=False)
            if open_positions:
                logger.warning(f"Open position exists for {symbol} - user {self.user_id}, cannot change leverage")
                return False
            
            # Margin tipini ayarla
            try:
                await self.rate_limiter.wait_if_needed('account', self.user_id)
                await self.client.futures_change_margin_type(symbol=symbol, marginType='CROSSED')
                logger.info(f"Margin type set to CROSSED for {symbol} - user {self.user_id}")
            except BinanceAPIException as margin_error:
                if "No need to change margin type" in str(margin_error):
                    logger.info(f"Margin type already CROSSED for {symbol} - user {self.user_id}")
                else:
                    logger.warning(f"Could not change margin type for user {self.user_id}: {margin_error}")
            
            # Kaldıracı ayarla
            await self.rate_limiter.wait_if_needed('account', self.user_id)
            await self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
            logger.info(f"Leverage set to {leverage}x for {symbol} - user {self.user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error setting leverage for user {self.user_id}: {e}")
            return False
    
    async def close(self):
        """Client bağlantısını kapat"""
        if self.client:
            try:
                await self.client.close_connection()
                logger.info(f"BinanceClient closed for user: {self.user_id}")
            except Exception as e:
                logger.error(f"Error closing BinanceClient for user {self.user_id}: {e}")
            finally:
                self.client = None
