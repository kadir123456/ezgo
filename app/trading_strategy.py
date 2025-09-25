# app/trading_strategy.py - UPDATED: Basit EMA Kesişimi + Bakiye Kontrollü
import pandas as pd
import numpy as np
from .utils.logger import get_logger

logger = get_logger("trading_strategy")

class SimpleEMAStrategy:
    """
    🎯 BASİT EMA KESİŞİMİ STRATEJİSİ
    - Sadece EMA9 ve EMA21 kesişimi
    - Tüm filtreler kaldırıldı
    - Long ve Short işlemler
    - Bakiye kontrolü entegreli
    """
    
    def __init__(self, timeframe: str = "15m"):
        self.timeframe = timeframe
        self.config = self._get_simple_config(timeframe)
        
        logger.info(f"🎯 Simple EMA Strategy initialized for {timeframe}")
        logger.info(f"EMA9 x EMA21 crossover strategy - No filters")

    def _get_simple_config(self, timeframe: str) -> dict:
        """Basit EMA konfigürasyonu - tüm timeframe'ler için aynı"""
        
        return {
            "strategy_type": "simple_ema_crossover",
            "ema_fast": 9,          # EMA9
            "ema_slow": 21,         # EMA21
            "profit_target": 1.0,   # %1.0 TP
            "stop_loss": 0.8,       # %0.8 SL
            "max_hold_time": 240,   # 4 saat max
            "min_balance_usdt": 20, # Minimum bakiye gereksinimi
            "signal_frequency": "medium"
        }

    def analyze_klines(self, klines: list) -> str:
        """
        🎯 BASİT EMA KESİŞİMİ ANALİZİ
        Sadece EMA9 ve EMA21 kesişimi kontrol eder
        """
        try:
            if len(klines) < 25:  # En az 25 mum gerekli
                return "HOLD"

            df = self._prepare_dataframe(klines)
            df = self._calculate_simple_emas(df)
            
            # Basit kesişim sinyali
            signal = self._get_crossover_signal(df)
            
            if signal != "HOLD":
                logger.info(f"🎯 EMA CROSSOVER: {signal} - {self.timeframe}")
                logger.info(f"EMA9: {df.iloc[-1]['ema9']:.2f}, EMA21: {df.iloc[-1]['ema21']:.2f}")
            
            return signal
            
        except Exception as e:
            logger.error(f"EMA analysis error for {self.timeframe}: {e}")
            return "HOLD"

    def _prepare_dataframe(self, klines: list) -> pd.DataFrame:
        """DataFrame hazırlığı"""
        df = pd.DataFrame(klines, columns=[
            'open_time', 'open', 'high', 'low', 'close', 'volume', 'close_time',
            'quote_asset_volume', 'number_of_trades', 'taker_buy_base_asset_volume',
            'taker_buy_quote_asset_volume', 'ignore'
        ])
        
        df['close'] = pd.to_numeric(df['close'])
        return df

    def _calculate_simple_emas(self, df: pd.DataFrame) -> pd.DataFrame:
        """Sadece EMA9 ve EMA21 hesapla"""
        df['ema9'] = df['close'].ewm(span=9).mean()
        df['ema21'] = df['close'].ewm(span=21).mean()
        return df

    def _get_crossover_signal(self, df: pd.DataFrame) -> str:
        """
        🎯 BASİT EMA KESİŞİMİ SİNYALİ
        EMA9 > EMA21 = LONG
        EMA9 < EMA21 = SHORT
        """
        if len(df) < 2:
            return "HOLD"
            
        current = df.iloc[-1]
        previous = df.iloc[-2]
        
        # Mevcut EMA değerleri
        current_ema9 = current['ema9']
        current_ema21 = current['ema21']
        
        # Önceki EMA değerleri
        prev_ema9 = previous['ema9']
        prev_ema21 = previous['ema21']
        
        # Golden Cross - EMA9 crosses above EMA21 (LONG)
        if prev_ema9 <= prev_ema21 and current_ema9 > current_ema21:
            logger.info(f"🟢 GOLDEN CROSS: EMA9 ({current_ema9:.2f}) > EMA21 ({current_ema21:.2f})")
            return "LONG"
        
        # Death Cross - EMA9 crosses below EMA21 (SHORT)
        elif prev_ema9 >= prev_ema21 and current_ema9 < current_ema21:
            logger.info(f"🔴 DEATH CROSS: EMA9 ({current_ema9:.2f}) < EMA21 ({current_ema21:.2f})")
            return "SHORT"
        
        return "HOLD"

    def get_risk_params(self) -> dict:
        """Risk parametreleri"""
        return {
            "stop_loss_percent": self.config["stop_loss"],
            "take_profit_percent": self.config["profit_target"], 
            "max_hold_time_minutes": self.config["max_hold_time"],
            "min_balance_usdt": self.config["min_balance_usdt"],
            "signal_frequency": self.config["signal_frequency"]
        }

    def get_strategy_info(self) -> dict:
        """Strateji bilgileri"""
        return {
            "timeframe": self.timeframe,
            "strategy_type": "Simple EMA Crossover",
            "indicators": "EMA9 x EMA21",
            "profit_target": f"{self.config['profit_target']}%",
            "stop_loss": f"{self.config['stop_loss']}%",
            "max_hold_time": f"{self.config['max_hold_time']} dakika",
            "min_balance": f"{self.config['min_balance_usdt']} USDT",
            "filters": "None - Pure crossover",
            "description": "🎯 Sadece EMA kesişimi - Filtre yok"
        }


# ✅ BACKWARD COMPATIBILITY
class TradingStrategy:
    """Eski trading_strategy sınıfı - Simple EMA ile güncellendi"""
    def __init__(self, short_ema_period: int = 9, long_ema_period: int = 21):
        self.strategy = SimpleEMAStrategy("15m")
        logger.info(f"🎯 TradingStrategy (legacy) - Simple EMA Crossover")

    def analyze_klines(self, klines: list) -> str:
        """Legacy analyze_klines - Simple EMA ile"""
        return self.strategy.analyze_klines(klines)


# Factory function - güncellendi
def create_strategy_for_timeframe(timeframe: str) -> SimpleEMAStrategy:
    """🎯 Simple EMA strategy factory"""
    strategy = SimpleEMAStrategy(timeframe)
    logger.info(f"🎯 Created Simple EMA strategy for {timeframe}")
    return strategy

# Global instances - Simple EMA ile güncellendi
trading_strategy = TradingStrategy()
strategies = {
    "1m": SimpleEMAStrategy("1m"),
    "3m": SimpleEMAStrategy("3m"),
    "5m": SimpleEMAStrategy("5m"),
    "15m": SimpleEMAStrategy("15m"),
    "30m": SimpleEMAStrategy("30m"),
    "1h": SimpleEMAStrategy("1h"),
    "2h": SimpleEMAStrategy("2h"),
    "4h": SimpleEMAStrategy("4h"),
    "6h": SimpleEMAStrategy("6h"),
    "8h": SimpleEMAStrategy("8h"),
    "12h": SimpleEMAStrategy("12h"),
    "1d": SimpleEMAStrategy("1d")
}
