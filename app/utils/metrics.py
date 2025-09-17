from datetime import datetime, timezone
import logging

logger = logging.getLogger("metrics")

class MetricsCollector:
    """Simple metrics collector"""
    
    def __init__(self):
        self.data = {
            "api_requests": 0,
            "bot_starts": 0,
            "bot_stops": 0,
            "trades": 0,
            "errors": 0,
            "websocket_connections": 0,
            "websocket_reconnections": 0,
            "active_bots": 0,
            "last_update": datetime.now(timezone.utc).isoformat()
        }
        
    def record_api_request(self, endpoint: str, method: str, status_code: int, duration: float):
        """API isteği kaydeder"""
        self.data["api_requests"] += 1
        self.data["last_update"] = datetime.now(timezone.utc).isoformat()
        logger.info(f"API request: {method} {endpoint} - {status_code}")
        
    def record_bot_start(self, user_id: str, symbol: str):
        """Bot başlatma kaydeder"""
        self.data["bot_starts"] += 1
        self.data["active_bots"] += 1
        self.data["last_update"] = datetime.now(timezone.utc).isoformat()
        logger.info(f"Bot started: {user_id} - {symbol}")
        
    def record_bot_stop(self, user_id: str, symbol: str, reason: str):
        """Bot durdurma kaydeder"""
        self.data["bot_stops"] += 1
        self.data["active_bots"] = max(0, self.data["active_bots"] - 1)
        self.data["last_update"] = datetime.now(timezone.utc).isoformat()
        logger.info(f"Bot stopped: {user_id} - {symbol} - {reason}")
        
    def record_trade(self, user_id: str, symbol: str, side: str, pnl: float, reason: str):
        """Trade kaydeder"""
        self.data["trades"] += 1
        self.data["last_update"] = datetime.now(timezone.utc).isoformat()
        logger.info(f"Trade: {user_id} - {symbol} - {side} - PnL: {pnl}")
        
    def record_error(self, error_type: str, component: str):
        """Hata kaydeder"""
        self.data["errors"] += 1
        self.data["last_update"] = datetime.now(timezone.utc).isoformat()
        logger.error(f"Error recorded: {error_type} in {component}")
        
    def update_websocket_connections(self, count: int):
        """WebSocket bağlantı sayısını günceller"""
        self.data["websocket_connections"] = count
        self.data["last_update"] = datetime.now(timezone.utc).isoformat()
        
    def record_websocket_reconnection(self, user_id: str):
        """WebSocket yeniden bağlanma kaydeder"""
        self.data["websocket_reconnections"] += 1
        self.data["last_update"] = datetime.now(timezone.utc).isoformat()
        logger.info(f"WebSocket reconnection: {user_id}")

# Global metrics instance
metrics = MetricsCollector()

def get_metrics_data() -> str:
    """Metrics verilerini Prometheus formatında döndürür"""
    data = metrics.data
    prometheus_format = f"""# HELP api_requests_total Total API requests
# TYPE api_requests_total counter
api_requests_total {data['api_requests']}

# HELP bot_starts_total Total bot starts
# TYPE bot_starts_total counter
bot_starts_total {data['bot_starts']}

# HELP bot_stops_total Total bot stops
# TYPE bot_stops_total counter
bot_stops_total {data['bot_stops']}

# HELP active_bots Current active bots
# TYPE active_bots gauge
active_bots {data['active_bots']}

# HELP trades_total Total trades
# TYPE trades_total counter
trades_total {data['trades']}

# HELP errors_total Total errors
# TYPE errors_total counter
errors_total {data['errors']}

# HELP websocket_connections Current WebSocket connections
# TYPE websocket_connections gauge
websocket_connections {data['websocket_connections']}

# HELP websocket_reconnections_total Total WebSocket reconnections
# TYPE websocket_reconnections_total counter
websocket_reconnections_total {data['websocket_reconnections']}
"""
    return prometheus_format.strip()

def get_metrics_content_type() -> str:
    """Metrics content type döndürür"""
    return "text/plain; version=0.0.4; charset=utf-8"
