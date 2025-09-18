import asyncio
from binance import AsyncClient
from binance.exceptions import BinanceAPIException, BinanceRequestException
from .config import settings
import time
from typing import Optional, Dict, Any
from .utils.logger import get_logger

logger = get_logger("binance_client")

class BinanceClient:
    """
    Kullanıcıya özel Binance client sınıfı
    Her kullanıcı için ayrı instance oluşturulur
    """
    def __init__(self, api_key: str = None, api_secret: str = None):
        self.api_key = api_key or settings.BINANCE_API_KEY
        self.api_secret = api_secret or settings.BINANCE_API_SECRET
        self.is_testnet = settings.ENVIRONMENT == "TEST"
        self.client: AsyncClient | None = None
        self.exchange_info = None
        
        # Cache variables - kullanıcıya özel
        self._last_balance_check = 0
        self._cached_balance = 0.0
        self._last_position_check = {}
        self._cached_positions = {}
        self._rate_limit_delay_time = 0.1
        
        logger.info(f"BinanceClient created for API key: {self.api_key[:8]}...")
        
    async def initialize(self):
        """Client'ı başlat ve test et"""
        if self.client is None:
            try:
                self.client = await AsyncClient.create(
                    self.api_key, 
                    self.api_secret, 
                    testnet=self.is_testnet
                )
                
                # Test connection (Hesap bilgilerini alarak bağlantıyı test eder)
                await self.client.futures_account()
                logger.info(f"BinanceClient initialized successfully for {self.api_key[:8]}...")
                return True
            
            except BinanceAPIException as e:
                logger.error(f"Binance API returned error during initialization: {e.status_code} - {e.message}")
                return False
            except BinanceRequestException as e:
                logger.error(f"Binance request failed during initialization: {e.status_code} - {e.message}")
                return False
            except Exception as e:
                logger.error(f"An unexpected error occurred during Binance client initialization: {e}")
                return False
        
        return True # Eğer client zaten varsa, True döndür
        
    async def _rate_limit_delay(self):
        """Rate limit koruması"""
        await asyncio.sleep(self._rate_limit_delay_time)
        
    async def get_symbol_info(self, symbol: str):
        """Symbol bilgilerini getir"""
        if not self.exchange_info:
            return None
        for s in self.exchange_info['symbols']:
            if s['symbol'] == symbol:
                return s
        return None
        
    async def get_open_positions(self, symbol: str, use_cache: bool = True):
        """Açık pozisyonları getir - cache desteği ile"""
        try:
            current_time = time.time()
            cache_key = symbol
            
            # Cache kontrolü (5 saniye cache)
            if use_cache and cache_key in self._last_position_check:
                if current_time - self._last_position_check[cache_key] < 5:
                    return self._cached_positions.get(cache_key, [])
            
            await self._rate_limit_delay()
            positions = await self.client.futures_position_information(symbol=symbol)
            open_positions = [p for p in positions if float(p['positionAmt']) != 0]
            
            # Cache güncelle
            self._last_position_check[cache_key] = current_time
            self._cached_positions[cache_key] = open_positions
            
            return open_positions
            
        except BinanceAPIException as e:
            if "-1003" in str(e):  # Rate limit
                logger.warning(f"Rate limit hit for positions: {symbol}")
                return self._cached_positions.get(symbol, [])
            logger.error(f"Error getting positions for {symbol}: {e}")
            return []

    async def cancel_all_orders_safe(self, symbol: str):
        """Tüm açık emirleri güvenli şekilde iptal et"""
        try:
            await self._rate_limit_delay()
            open_orders = await self.client.futures_get_open_orders(symbol=symbol)
            
            if open_orders:
                logger.info(f"Cancelling {len(open_orders)} open orders for {symbol}")
                await self._rate_limit_delay()
                await self.client.futures_cancel_all_open_orders(symbol=symbol)
                await asyncio.sleep(0.5)
                logger.info(f"All orders cancelled for {symbol}")
                return True
            else:
                logger.info(f"No open orders to cancel for {symbol}")
                return True
                
        except BinanceAPIException as e:
            if "-1003" in str(e):
                logger.warning(f"Rate limit hit while cancelling orders: {symbol}")
                return False
            logger.error(f"Error cancelling orders for {symbol}: {e}")
            return False

    async def create_market_order_with_sl_tp(self, symbol: str, side: str, quantity: float, entry_price: float, price_precision: int):
        """
        Market order ile birlikte SL/TP oluştur
        """
        def format_price(price):
            return f"{price:.{price_precision}f}"
            
        try:
            # Ana market order
            logger.info(f"Creating market order: {symbol} {side} {quantity}")
            await self._rate_limit_delay()
            
            main_order = await self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type='MARKET',
                quantity=quantity
            )
            
            logger.info(f"Market order successful: {symbol} {side} {quantity}")
            
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
                await self._rate_limit_delay()
                sl_order = await self.client.futures_create_order(
                    symbol=symbol,
                    side=opposite_side,
                    type='STOP_MARKET',
                    quantity=quantity,
                    stopPrice=formatted_sl_price,
                    timeInForce='GTE_GTC',
                    reduceOnly=True
                )
                logger.info(f"Stop Loss created: {formatted_sl_price}")
            except Exception as e:
                logger.error(f"Stop Loss creation failed: {e}")
            
            # Take Profit oluştur
            try:
                await self._rate_limit_delay()
                tp_order = await self.client.futures_create_order(
                    symbol=symbol,
                    side=opposite_side,
                    type='TAKE_PROFIT_MARKET',
                    quantity=quantity,
                    stopPrice=formatted_tp_price,
                    timeInForce='GTE_GTC',
                    reduceOnly=True
                )
                logger.info(f"Take Profit created: {formatted_tp_price}")
            except Exception as e:
                logger.error(f"Take Profit creation failed: {e}")
            
            return main_order
            
        except Exception as e:
            logger.error(f"Market order creation failed: {e}")
            await self.cancel_all_orders_safe(symbol)
            return None

    async def close_position(self, symbol: str, position_amt: float, side_to_close: str):
        """Pozisyon kapat"""
        try:
            # Açık emirleri iptal et
            await self.cancel_all_orders_safe(symbol)
            await asyncio.sleep(0.2)
            
            # Pozisyonu kapat
            logger.info(f"Closing position: {symbol} {abs(position_amt)}")
            await self._rate_limit_delay()
            
            response = await self.client.futures_create_order(
                symbol=symbol,
                side=side_to_close,
                type='MARKET',
                quantity=abs(position_amt),
                reduceOnly=True
            )
            
            logger.info(f"Position closed: {symbol}")
            
            # Cache temizle
            if symbol in self._cached_positions:
                del self._cached_positions[symbol]
            if symbol in self._last_position_check:
                del self._last_position_check[symbol]
            
            return response
            
        except Exception as e:
            logger.error(f"Position closing failed: {e}")
            await self.cancel_all_orders_safe(symbol)
            return None

    async def get_account_balance(self, use_cache: bool = True):
        """Hesap bakiyesi getir - cache desteği ile"""
        try:
            current_time = time.time()
            
            # Cache kontrolü (10 saniye cache)
            if use_cache and current_time - self._last_balance_check < 10:
                return self._cached_balance
            
            await self._rate_limit_delay()
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
                return self._cached_balance
            logger.error(f"Error getting account balance: {e}")
            return self._cached_balance

    async def get_position_pnl(self, symbol: str, use_cache: bool = True):
        """Pozisyon PnL getir"""
        try:
            current_time = time.time()
            cache_key = f"{symbol}_pnl"
            
            # Cache kontrolü (3 saniye cache)
            if use_cache and cache_key in self._last_position_check:
                if current_time - self._last_position_check[cache_key] < 3:
                    return self._cached_positions.get(cache_key, 0.0)
            
            await self._rate_limit_delay()
            positions = await self.client.futures_position_information(symbol=symbol)
            
            pnl = 0.0
            for position in positions:
                if float(position['positionAmt']) != 0:
                    pnl = float(position['unRealizedProfit'])
                    break
            
            # Cache güncelle
            self._last_position_check[cache_key] = current_time
            self._cached_positions[cache_key] = pnl
            
            return pnl
            
        except Exception as e:
            logger.error(f"Error getting position PnL: {e}")
            return self._cached_positions.get(f"{symbol}_pnl", 0.0)

    async def get_last_trade_pnl(self, symbol: str) -> float:
        """Son işlem PnL'ini getir"""
        try:
            await self._rate_limit_delay()
            trades = await self.client.futures_account_trades(symbol=symbol, limit=5)
            
            if trades:
                last_order_id = trades[-1]['orderId']
                pnl = 0.0
                for trade in reversed(trades):
                    if trade['orderId'] == last_order_id:
                        pnl += float(trade['realizedPnl'])
                    else:
                        break
                return pnl
            return 0.0
            
        except Exception as e:
            logger.error(f"Error getting last trade PnL: {e}")
            return 0.0

    async def get_historical_klines(self, symbol: str, interval: str, limit: int = 100):
        """Geçmiş kline verilerini getir"""
        try:
            logger.info(f"Getting historical klines: {symbol} {interval} {limit}")
            await self._rate_limit_delay()
            return await self.client.get_historical_klines(symbol, interval, limit=limit)
        except Exception as e:
            logger.error(f"Error getting historical klines: {e}")
            return []

    async def set_leverage(self, symbol: str, leverage: int):
        """Kaldıraç ayarla"""
        try:
            # Açık pozisyon kontrolü
            open_positions = await self.get_open_positions(symbol, use_cache=False)
            if open_positions:
                logger.warning(f"Open position exists for {symbol}, cannot change leverage")
                return False
            
            # Margin tipini ayarla
            try:
                await self._rate_limit_delay()
                await self.client.futures_change_margin_type(symbol=symbol, marginType='CROSSED')
                logger.info(f"Margin type set to CROSSED for {symbol}")
            except BinanceAPIException as margin_error:
                if "No need to change margin type" in str(margin_error):
                    logger.info(f"Margin type already CROSSED for {symbol}")
                else:
                    logger.warning(f"Could not change margin type: {margin_error}")
            
            # Kaldıracı ayarla
            await self._rate_limit_delay()
            await self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
            logger.info(f"Leverage set to {leverage}x for {symbol}")
            return True
            
        except Exception as e:
            logger.error(f"Error setting leverage: {e}")
            return False

    async def get_market_price(self, symbol: str):
        """Market fiyatını getir"""
        try:
            await self._rate_limit_delay()
            ticker = await self.client.futures_symbol_ticker(symbol=symbol)
            return float(ticker['price'])
        except Exception as e:
            logger.error(f"Error getting market price for {symbol}: {e}")
            return None

    async def close(self):
        """Client bağlantısını kapat"""
        if self.client:
            try:
                await self.client.close_connection()
                logger.info(f"BinanceClient closed for {self.api_key[:8]}...")
            except Exception as e:
                logger.error(f"Error closing BinanceClient: {e}")
            finally:
                self.client = None
