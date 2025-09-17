from pydantic import BaseModel, Field, field_validator, EmailStr
import re
import logging

logger = logging.getLogger("validation")

# ---------------------- Validators ----------------------

class TradingSymbolValidator:
    """Trading symbol validation"""
    VALID_SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "ADAUSDT", "DOTUSDT", "LINKUSDT"]

    @classmethod
    def validate_symbol(cls, symbol: str) -> bool:
        if not symbol or not isinstance(symbol, str):
            return False
        
        symbol = symbol.upper().strip()
        
        # Basic format check
        if not re.match(r'^[A-Z]{3,10}USDT$', symbol):
            return False
        
        # Whitelist check
        return symbol in cls.VALID_SYMBOLS

class TradingParametersValidator:
    """Trading parameters validation"""
    
    @staticmethod
    def validate_leverage(leverage: int) -> bool:
        return isinstance(leverage, int) and 1 <= leverage <= 125
    
    @staticmethod
    def validate_order_size(order_size: float) -> bool:
        return isinstance(order_size, (int, float)) and 10 <= order_size <= 10000
    
    @staticmethod
    def validate_percentage(percentage: float, min_val: float = 0.1, max_val: float = 50.0) -> bool:
        return isinstance(percentage, (int, float)) and min_val <= percentage <= max_val
    
    @staticmethod
    def validate_timeframe(timeframe: str) -> bool:
        valid_timeframes = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '8h', '12h', '1d']
        return timeframe in valid_timeframes

class ApiKeyValidator:
    """API key validation"""
    
    @staticmethod
    def validate_binance_api_key(api_key: str) -> bool:
        if not api_key or not isinstance(api_key, str):
            return False
        api_key = api_key.strip()
        return len(api_key) == 64 and api_key.isalnum()
    
    @staticmethod
    def validate_binance_secret(secret: str) -> bool:
        if not secret or not isinstance(secret, str):
            return False
        secret = secret.strip()
        return len(secret) == 64 and secret.isalnum()

# ---------------------- Pydantic Models ----------------------

class EnhancedStartRequest(BaseModel):
    symbol: str = Field(..., min_length=6, max_length=12)
    timeframe: str = Field(..., min_length=2, max_length=3)
    leverage: int = Field(..., ge=1, le=125)
    order_size: float = Field(..., ge=10, le=10000)
    stop_loss: float = Field(..., ge=0.1, le=50.0)
    take_profit: float = Field(..., ge=0.1, le=50.0)
    
    @field_validator('symbol')
    @classmethod
    def validate_symbol(cls, v):
        if not TradingSymbolValidator.validate_symbol(v):
            raise ValueError('Invalid trading symbol')
        return v.upper().strip()
    
    @field_validator('timeframe')
    @classmethod
    def validate_timeframe(cls, v):
        if not TradingParametersValidator.validate_timeframe(v):
            raise ValueError('Invalid timeframe')
        return v
    
    @field_validator('take_profit')
    @classmethod
    def validate_tp_greater_than_sl(cls, v, info):
        stop_loss = info.data.get('stop_loss')
        if stop_loss is not None and v <= stop_loss:
            raise ValueError('Take profit must be greater than stop loss')
        return v

class EnhancedApiKeysRequest(BaseModel):
    api_key: str = Field(..., min_length=64, max_length=64)
    api_secret: str = Field(..., min_length=64, max_length=64)
    testnet: bool = Field(default=False)
    
    @field_validator('api_key')
    @classmethod
    def validate_api_key(cls, v):
        if not ApiKeyValidator.validate_binance_api_key(v):
            raise ValueError('Invalid Binance API key format')
        return v
        
    @field_validator('api_secret')
    @classmethod
    def validate_api_secret(cls, v):
        if not ApiKeyValidator.validate_binance_secret(v):
            raise ValueError('Invalid Binance API secret format')
        return v

class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6)
    full_name: str = Field(..., min_length=2, max_length=100)

def sanitize_string(text: str, max_length: int = 100) -> str:
    """String sanitization"""
    if not text:
        return ""
    
    # Remove dangerous characters
    text = re.sub(r'[<>"\']', '', text)
    
    # Limit length
    if len(text) > max_length:
        text = text[:max_length]
    
    return text.strip()

def validate_user_input(data: dict):
    """Validate user input dict using EnhancedStartRequest model"""
    return EnhancedStartRequest(**data)
