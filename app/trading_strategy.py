import pandas as pd
from .utils.logger import get_logger

logger = get_logger("trading_strategy")

class TradingStrategy:
    """
    Saf EMA (9, 21) kesişimine dayalı sinyal üretici.
    """
    def __init__(self, short_ema_period: int = 9, long_ema_period: int = 21):
        self.short_ema_period = short_ema_period
        self.long_ema_period = long_ema_period
        logger.info(f"EMA Crossover Stratejisi başlatıldı: EMA({self.short_ema_period}, {self.long_ema_period})")

    def analyze_klines(self, klines: list) -> str:
        """
        EMA crossover stratejisi - Geliştirilmiş versiyon
        """
        try:
            if len(klines) < self.long_ema_period + 5:  # Biraz daha fazla veri istiyoruz
                logger.debug(f"Insufficient data: {len(klines)}/{self.long_ema_period + 5}")
                return "HOLD"

            # DataFrame oluştur
            df = pd.DataFrame(klines, columns=[
                'open_time', 'open', 'high', 'low', 'close', 'volume', 'close_time',
                'quote_asset_volume', 'number_of_trades', 'taker_buy_base_asset_volume',
                'taker_buy_quote_asset_volume', 'ignore'
            ])
            
            # Close price'ı numeric'e çevir
            df['close'] = pd.to_numeric(df['close'])
            
            # EMA hesapla
            df['short_ema'] = df['close'].ewm(span=self.short_ema_period, adjust=False).mean()
            df['long_ema'] = df['close'].ewm(span=self.long_ema_period, adjust=False).mean()

            # En son 2 satırı al
            if len(df) < 2:
                return "HOLD"
                
            last_row = df.iloc[-1]
            prev_row = df.iloc[-2]
            
            signal = "HOLD"
            
            # EMA crossover logic
            prev_short = prev_row['short_ema']
            prev_long = prev_row['long_ema']
            curr_short = last_row['short_ema']
            curr_long = last_row['long_ema']
            current_price = last_row['close']

            # Bullish crossover (EMA9 crosses above EMA21)
            if prev_short <= prev_long and curr_short > curr_long:
                signal = "LONG"
                logger.info(f"LONG signal - EMA crossover: EMA9({curr_short:.2f}) > EMA21({curr_long:.2f}) at ${current_price:.2f}")
                
            # Bearish crossover (EMA9 crosses below EMA21)  
            elif prev_short >= prev_long and curr_short < curr_long:
                signal = "SHORT"
                logger.info(f"SHORT signal - EMA crossover: EMA9({curr_short:.2f}) < EMA21({curr_long:.2f}) at ${current_price:.2f}")
            
            # Debug log for monitoring
            logger.debug(f"EMA Analysis - Price: ${current_price:.2f}, EMA9: {curr_short:.2f}, EMA21: {curr_long:.2f}, Signal: {signal}")
            
            return signal
            
        except Exception as e:
            logger.error(f"Strategy analysis error: {e}")
            return "HOLD"

# Global strategy instance
trading_strategy = TradingStrategy(short_ema_period=9, long_ema_period=21)
