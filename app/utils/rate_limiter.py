import time
from typing import Dict, List
from fastapi import Request, HTTPException
import logging

logger = logging.getLogger("rate_limiter")

class RateLimiter:
    """Simple rate limiter"""
    
    def __init__(self):
        self.requests: Dict[str, List[float]] = {}
        
    async def check_request_limit(self, request: Request, limit_str: str):
        """Rate limit kontrolü yapar"""
        try:
            # Limit string'ini parse et (örn: "5/minute")
            count, period = limit_str.split('/')
            count = int(count)
            
            if period == 'minute':
                window = 60
            elif period == 'hour':
                window = 3600
            elif period == 'day':
                window = 86400
            else:
                window = 60  # Default
                
            # Client IP'sini al
            client_ip = request.client.host if request.client else "unknown"
            current_time = time.time()
            
            # Bu client için geçmiş istekleri al
            if client_ip not in self.requests:
                self.requests[client_ip] = []
                
            # Eski istekleri temizle
            self.requests[client_ip] = [
                req_time for req_time in self.requests[client_ip] 
                if current_time - req_time < window
            ]
            
            # Limit kontrolü
            if len(self.requests[client_ip]) >= count:
                logger.warning(f"Rate limit exceeded for {client_ip}")
                raise HTTPException(status_code=429, detail="Rate limit exceeded")
                
            # İsteği kaydet
            self.requests[client_ip].append(current_time)
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Rate limit check error: {e}")
            # Hata durumunda geçir
            pass

# Global limiter
limiter = RateLimiter()
