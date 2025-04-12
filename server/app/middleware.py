from fastapi import Request, HTTPException, Depends
from fastapi.security import APIKeyHeader
from starlette.middleware.base import BaseHTTPMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
import time
from typing import Callable
import logging

from app.core.config import settings

# Rate limiters
limiter = Limiter(key_func=get_remote_address)

# API Key security
api_key_header = APIKeyHeader(name=settings.API_KEY_HEADER, auto_error=False)

async def verify_api_key(api_key: str = Depends(api_key_header)):
    """Verify API key if configured"""
    if settings.API_KEYS and (not api_key or api_key not in settings.API_KEYS):
        raise HTTPException(
            status_code=403,
            detail="Invalid or missing API key"
        )
    return api_key

class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware with different limits for different endpoints"""
    
    def __init__(self, app):
        super().__init__(app)
        self.limiter = limiter

    async def dispatch(self, request: Request, call_next: Callable):
        # Get client IP
        client_ip = get_remote_address(request)
        
        # Define rate limits based on endpoint
        if request.url.path.startswith("/api/v1/documents/upload"):
            # Stricter limits for uploads
            if not await self.limiter.test(f"{client_ip}_upload", settings.RATE_LIMIT_UPLOADS_PER_HOUR / 3600):
                raise HTTPException(
                    status_code=429,
                    detail="Upload rate limit exceeded"
                )
        else:
            # General API rate limit
            if not await self.limiter.test(f"{client_ip}_general", settings.RATE_LIMIT_PER_MINUTE / 60):
                raise HTTPException(
                    status_code=429,
                    detail="API rate limit exceeded"
                )

        response = await call_next(request)
        return response

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware for logging requests and responses"""
    
    async def dispatch(self, request: Request, call_next: Callable):
        start_time = time.time()
        
        # Log request
        logging.info(f"Request: {request.method} {request.url.path}")
        
        try:
            response = await call_next(request)
            
            # Log response
            process_time = time.time() - start_time
            logging.info(
                f"Response: {request.method} {request.url.path} "
                f"- Status: {response.status_code} "
                f"- Time: {process_time:.3f}s"
            )
            
            # Add timing header
            response.headers["X-Process-Time"] = str(process_time)
            return response
            
        except Exception as e:
            process_time = time.time() - start_time
            logging.error(
                f"Error: {request.method} {request.url.path} "
                f"- Time: {process_time:.3f}s "
                f"- Error: {str(e)}"
            )
            raise

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to responses"""
    
    async def dispatch(self, request: Request, call_next: Callable):
        response = await call_next(request)
        
        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        
        return response
