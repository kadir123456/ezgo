# app/position_manager.py

import asyncio
import math
from typing import Dict, List, Optional
from datetime import datetime, timezone

from .binance_client import binance_client
from .firebase_manager import firebase_manager
from .config import settings
from .trading_strategy import trading_strategy
from binance.exceptions import BinanceAPIException, BinanceRequestException
import logging

logger = logging.getLogger(__name__)

class PositionManager:
    """
    Botun pozisyonlarını yönetir, TP/SL (Take Profit/Stop Loss) seviyelerini belirler
    ve pozisyonları aktif olarak izler.
    """
    def __init__(self):
        self.is_running = False
        self._monitor_task = None
        self.active_positions = {}  # Symbol'e göre aktif pozisyonları saklar
        self._last_scan_time = {}  # Her sembol için son tarama zamanı

    def get_status(self) -> dict:
        """Pozisyon yöneticisinin durumunu döndürür."""
        return {
            "is_running": self.is_running,
            "monitored_symbols": list(self.active_positions.keys()),
            "last_scan": {s: t.isoformat() for s, t in self._last_scan_time.items()},
            "details": self.active_positions
        }

    async def get_account_info(self):
        """Hesap bilgilerini Binance'tan çeker ve günceller."""
        try:
            account_info = await binance_client.get_account_balance()
            return account_info
        except Exception as e:
            logger.error(f"Hesap bilgileri alınırken hata oluştu: {e}")
            return {}

    async def place_market_order(self, symbol: str, side: str, quantity: float) -> Optional[dict]:
        """Piyasa emri verir ve pozisyonu günceller."""
        try:
            order = await binance_client.create_market_order(symbol, side, quantity)
            logger.info(f"✅ PİYASA EMRİ GÖNDERİLDİ: {order}")
            await self._update_positions()  # Pozisyonları hemen güncelle
            return order
        except Exception as e:
            logger.error(f"❌ PİYASA EMİR HATASI: {e}")
            return None

    def _process_position_data(self, positions_raw: List[dict]) -> Dict[str, dict]:
        """
        Ham pozisyon verilerini işler ve güvenli bir şekilde normalize eder.
        ZeroDivisionError ve KeyError hatalarını önler.
        """
        processed_positions = {}
        
        for p in positions_raw:
            try:
                # Güvenli veri çıkarma - get() metodunu kullan
                symbol = p.get('symbol', 'N/A')
                position_amt = float(p.get('positionAmt', 0))
                
                # Sadece açık pozisyonları işle
                if position_amt == 0:
                    continue
                
                # Temel değerleri güvenli şekilde çıkar
                entry_price = float(p.get('entryPrice', 0))
                leverage = int(p.get('leverage', 1))
                unrealized_profit = float(p.get('unRealizedProfit', 0))
                liquidation_price = float(p.get('liquidationPrice', 0))
                mark_price = float(p.get('markPrice', 0))
                isolated_wallet = float(p.get('isolatedWallet', 0))
                position_side = p.get('positionSide', 'BOTH')
                margin_type = p.get('marginType', 'CROSSED')
                
                # Percentage hesaplaması - ZeroDivisionError önleme
                percentage = 0.0
                if isolated_wallet != 0:
                    try:
                        percentage = (unrealized_profit / isolated_wallet) * 100
                    except (ZeroDivisionError, TypeError):
                        logger.warning(f"Percentage hesaplama hatası - {symbol}: isolated_wallet={isolated_wallet}, unrealized_profit={unrealized_profit}")
                        percentage = 0.0
                else:
                    logger.debug(f"Isolated wallet sıfır - {symbol}")
                
                # Pozisyon verilerini oluştur
                position_data = {
                    'symbol': symbol,
                    'entryPrice': entry_price,
                    'positionAmt': position_amt,
                    'leverage': leverage,
                    'unRealizedProfit': unrealized_profit,
                    'liquidationPrice': liquidation_price,
                    'markPrice': mark_price,
                    'isolatedWallet': isolated_wallet,
                    'positionSide': position_side,
                    'marginType': margin_type,
                    'percentage': percentage,
                    'side': 'LONG' if position_amt > 0 else 'SHORT',  # Kolay erişim için
                    'quantity': abs(position_amt)  # Mutlak miktar
                }
                
                processed_positions[symbol] = position_data
                logger.debug(f"Pozisyon işlendi: {symbol} - {position_data['side']} - P&L: {percentage:.2f}%")
                
            except (ValueError, TypeError, KeyError) as e:
                # Değer dönüşümü ve anahtar hatalarını yakala
                logger.error(f"Pozisyon verisi işlenirken hata: {e} - Veri: {p}")
                continue  # Bu pozisyonu atla ve diğerleriyle devam et
            except Exception as e:
                # Beklenmeyen diğer hatalar
                logger.error(f"Beklenmeyen hata pozisyon işlenirken: {e} - Veri: {p}")
                continue
        
        return processed_positions

    async def _update_positions(self):
        """Pozisyonları Binance API'sinden günceller."""
        try:
            # Raw pozisyon verilerini al
            raw_positions = await binance_client.get_current_positions()
            
            # Verileri güvenli şekilde işle
            if isinstance(raw_positions, list):
                self.active_positions = self._process_position_data(raw_positions)
            elif isinstance(raw_positions, dict):
                # Eğer dict dönerse, values() kullan
                self.active_positions = self._process_position_data(list(raw_positions.values()))
            else:
                logger.warning(f"Beklenmeyen pozisyon verisi formatı: {type(raw_positions)}")
                self.active_positions = {}
                
            logger.debug(f"Pozisyonlar güncellendi: {len(self.active_positions)} açık pozisyon")
            
        except Exception as e:
            logger.error(f"Pozisyonlar güncellenirken hata: {e}")
            # Hata durumunda mevcut pozisyonları koru, boş dict atama
            
    async def _add_stop_loss_and_take_profit(self, position: dict):
        """Bir pozisyona TP/SL ekler."""
        try:
            symbol = position.get('symbol', '')
            if not symbol:
                logger.error("Symbol bilgisi eksik, TP/SL eklenemedi")
                return
                
            entry_price = float(position.get('entryPrice', 0))
            position_amt = float(position.get('positionAmt', 0))
            
            if entry_price <= 0 or position_amt == 0:
                logger.error(f"Geçersiz pozisyon verileri - {symbol}: entry_price={entry_price}, position_amt={position_amt}")
                return
            
            is_long = position_amt > 0
            quantity = abs(position_amt)

            # TP ve SL fiyatlarını hesapla - güvenli hesaplama
            try:
                if is_long:
                    tp_price = entry_price * (1 + settings.TAKE_PROFIT_PERCENT / 100)
                    sl_price = entry_price * (1 - settings.STOP_LOSS_PERCENT / 100)
                else:
                    tp_price = entry_price * (1 - settings.TAKE_PROFIT_PERCENT / 100)
                    sl_price = entry_price * (1 + settings.STOP_LOSS_PERCENT / 100)
            except (TypeError, AttributeError) as e:
                logger.error(f"TP/SL fiyat hesaplama hatası - {symbol}: {e}")
                return

            # Emirleri göndermeden önce mevcut TP/SL emirlerini iptal et
            try:
                await binance_client.cancel_all_open_orders(symbol)
            except Exception as e:
                logger.warning(f"Mevcut emirler iptal edilemedi - {symbol}: {e}")
            
            try:
                # TP (Take Profit) emri
                tp_side = "SELL" if is_long else "BUY"
                await binance_client.create_stop_and_limit_order(
                    symbol, tp_side, quantity, stop_price=tp_price, limit_price=tp_price
                )
                logger.info(f"✅ {symbol} için TP emri eklendi: {tp_price:.6f}")

                # SL (Stop Loss) emri
                sl_side = "SELL" if is_long else "BUY"
                await binance_client.create_stop_and_limit_order(
                    symbol, sl_side, quantity, stop_price=sl_price, limit_price=sl_price
                )
                logger.info(f"✅ {symbol} için SL emri eklendi: {sl_price:.6f}")
            
            except Exception as e:
                logger.error(f"❌ TP/SL emirleri eklenirken hata - {symbol}: {e}")
                
        except Exception as e:
            logger.error(f"❌ TP/SL ekleme işleminde genel hata: {e}")

    async def _scan_and_protect_positions(self, specific_symbol: Optional[str] = None):
        """
        Açık pozisyonları tarar ve TP/SL emri ekler.
        _monitor_loop ve manuel tarama için kullanılır.
        """
        try:
            print("🔍 Pozisyonlar taranıyor...")
            await self._update_positions()
            
            if not self.active_positions:
                print("✔ Açık pozisyon yok.")
                return

            symbols_to_scan = [specific_symbol] if specific_symbol else list(self.active_positions.keys())
            
            for symbol in symbols_to_scan:
                try:
                    if symbol in self.active_positions:
                        position = self.active_positions[symbol]
                        
                        # Sadece pozisyon açıldığında TP/SL ekle
                        try:
                            has_orders = await binance_client.has_open_orders(symbol)
                            if not has_orders:
                                print(f"🎯 {symbol} için pozisyon bulundu. TP/SL ekleniyor...")
                                await self._add_stop_loss_and_take_profit(position)
                        except Exception as e:
                            logger.error(f"Açık emir kontrolü hatası - {symbol}: {e}")
                            continue
                            
                        self._last_scan_time[symbol] = datetime.now(timezone.utc)
                        
                except Exception as e:
                    logger.error(f"Symbol tarama hatası - {symbol}: {e}")
                    continue
                    
            print("✔ Tarama tamamlandı.")
            
        except Exception as e:
            logger.error(f"Pozisyon tarama işleminde genel hata: {e}")
        
    async def manual_scan_symbol(self, symbol: str) -> bool:
        """
        Belirli bir coin için manuel TP/SL kontrolü. bot_core.py'den çağrılır.
        """
        try:
            if not symbol or not isinstance(symbol, str):
                logger.error(f"Geçersiz symbol: {symbol}")
                return False
                
            await self._scan_and_protect_positions(specific_symbol=symbol)
            return True
        except Exception as e:
            logger.error(f"Manuel tarama hatası - {symbol}: {e}")
            return False

    async def _monitor_loop(self):
        """Arka plan TP/SL izleme döngüsü."""
        logger.info("Pozisyon monitoring döngüsü başlatılıyor...")
        
        while self.is_running:
            try:
                await self._scan_and_protect_positions()
                await asyncio.sleep(settings.CACHE_DURATION_POSITION)  # Ayarlar dosyasındaki süreyi kullan
            except asyncio.CancelledError:
                logger.info("Monitoring döngüsü iptal edildi")
                break
            except Exception as e:
                logger.error(f"Monitor döngüsünde hata: {e}")
                await asyncio.sleep(5)  # Hata durumunda kısa bir süre bekle

    async def start_monitoring(self):
        """Arka plan monitor döngüsünü başlatır."""
        try:
            if not self.is_running:
                self.is_running = True
                self._monitor_task = asyncio.create_task(self._monitor_loop())
                logger.info("Pozisyon monitor döngüsü başlatıldı.")
            else:
                logger.info("Pozisyon monitor zaten çalışıyor.")
        except Exception as e:
            logger.error(f"Monitor başlatma hatası: {e}")
            self.is_running = False
            
    async def stop_monitoring(self):
        """Arka plan monitor döngüsünü durdurur."""
        try:
            if self.is_running and self._monitor_task:
                self.is_running = False
                self._monitor_task.cancel()
                try:
                    await self._monitor_task
                except asyncio.CancelledError:
                    logger.info("Pozisyon monitor döngüsü başarıyla durduruldu.")
                finally:
                    self._monitor_task = None
            else:
                logger.info("Pozisyon monitor zaten durdurulmuş.")
        except Exception as e:
            logger.error(f"Monitor durdurma hatası: {e}")

    def get_position_summary(self) -> dict:
        """Pozisyon özetini döndürür."""
        try:
            if not self.active_positions:
                return {
                    "total_positions": 0,
                    "total_pnl": 0.0,
                    "long_positions": 0,
                    "short_positions": 0,
                    "positions": []
                }
            
            total_pnl = 0.0
            long_count = 0
            short_count = 0
            position_list = []
            
            for symbol, position in self.active_positions.items():
                try:
                    pnl = float(position.get('unRealizedProfit', 0))
                    side = position.get('side', 'UNKNOWN')
                    
                    total_pnl += pnl
                    
                    if side == 'LONG':
                        long_count += 1
                    elif side == 'SHORT':
                        short_count += 1
                    
                    position_list.append({
                        'symbol': symbol,
                        'side': side,
                        'pnl': pnl,
                        'percentage': position.get('percentage', 0.0),
                        'quantity': position.get('quantity', 0.0)
                    })
                    
                except (ValueError, TypeError) as e:
                    logger.error(f"Pozisyon özeti hesaplama hatası - {symbol}: {e}")
                    continue
            
            return {
                "total_positions": len(self.active_positions),
                "total_pnl": total_pnl,
                "long_positions": long_count,
                "short_positions": short_count,
                "positions": position_list
            }
            
        except Exception as e:
            logger.error(f"Pozisyon özeti oluşturma hatası: {e}")
            return {
                "total_positions": 0,
                "total_pnl": 0.0,
                "long_positions": 0,
                "short_positions": 0,
                "positions": [],
                "error": str(e)
            }

    async def get_all_positions(self, user_id: str) -> List[dict]:
        """
        Kullanıcının tüm pozisyonlarını döndürür - HER ZAMAN ARRAY
        """
        try:
            # Pozisyonları güncelle
            await self._update_positions()
            
            # Pozisyon listesi oluştur
            positions = []
            
            for symbol, position in self.active_positions.items():
                try:
                    positions.append({
                        'symbol': position.get('symbol', ''),
                        'side': position.get('side', 'UNKNOWN'),
                        'positionAmt': str(position.get('quantity', 0)),
                        'entryPrice': str(position.get('entryPrice', 0)),
                        'markPrice': str(position.get('markPrice', 0)),
                        'unRealizedProfit': position.get('unRealizedProfit', 0.0),
                        'percentage': position.get('percentage', 0.0),
                        'leverage': str(position.get('leverage', 1)),
                        'marginType': position.get('marginType', 'CROSSED'),
                        'positionSide': 'LONG' if position.get('positionAmt', 0) > 0 else 'SHORT'
                    })
                except Exception as pos_error:
                    logger.error(f"Pozisyon formatlanırken hata - {symbol}: {pos_error}")
                    continue
            
            return positions  # HER ZAMAN ARRAY DÖNDÜR
            
        except Exception as e:
            logger.error(f"Pozisyonlar alınırken hata - user {user_id}: {e}")
            return []  # HATA DURUMUNDA BOŞ ARRAY DÖNDÜR

# Botun geri kalanı tarafından kullanılacak global nesne
position_manager = PositionManager()
