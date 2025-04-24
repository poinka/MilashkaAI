import logging
from logging.handlers import RotatingFileHandler
import os
import sys

class ColorFormatter(logging.Formatter):
    """Custom formatter adding colors to levelname field"""
    
    COLORS = {
        'DEBUG': '\033[0;36m',    # Cyan
        'INFO': '\033[0;32m',     # Green
        'WARNING': '\033[0;33m',   # Yellow
        'ERROR': '\033[0;31m',    # Red
        'CRITICAL': '\033[0;35m',  # Magenta
        'RESET': '\033[0m'        # Reset
    }

    def format(self, record):
        # Save original levelname
        orig_levelname = record.levelname
        # Add color to levelname
        if record.levelname in self.COLORS:
            record.levelname = f"{self.COLORS[record.levelname]}{record.levelname}{self.COLORS['RESET']}"
        result = super().format(record)
        # Restore original levelname
        record.levelname = orig_levelname
        return result

class RequestFormatter(logging.Formatter):
    """Custom formatter adding request_id if available"""
    
    def format(self, record):
        # Add request_id if available in record
        if hasattr(record, 'request_id'):
            record.request_id_str = f"[{record.request_id}] "
        else:
            record.request_id_str = ""
        return super().format(record)

def setup_logging():
    # Create logs directory if it doesn't exist
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # Set up root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Console handler with color formatting and request IDs
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_format = '%(request_id_str)s[%(levelname)s] %(name)s: %(message)s'
    console_handler.setFormatter(RequestFormatter(console_format))
    console_handler.addFilter(lambda record: not getattr(record, 'debug_only', False))
    root_logger.addHandler(console_handler)

    # File handler for complete logs
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, 'app.log'),
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    file_handler.setLevel(logging.DEBUG)
    file_format = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    file_handler.setFormatter(logging.Formatter(file_format))
    root_logger.addHandler(file_handler)

    # Suppress unwanted logs
    for logger_name in [
        'uvicorn.access',
        'uvicorn.error',
        'sentence_transformers',
        'torch',
        'tqdm',
        'llama_cpp',
        'transformers',
        'spacy'
    ]:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    # Create logger for our app
    app_logger = logging.getLogger('app')
    app_logger.setLevel(logging.DEBUG)
    
    return app_logger
