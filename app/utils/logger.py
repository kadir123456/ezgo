import logging
import sys
from datetime import datetime
from app.config import settings

# Simple logging setup without structlog dependency
def setup_logging():
    """Setup basic logging configuration"""
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        stream=sys.stdout
    )

def get_logger(name: str):
    """Get a standard Python logger"""
    setup_logging()
    return logging.getLogger(name)
