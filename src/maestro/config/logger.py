import logging
import sys
from pythonjsonlogger.json import JsonFormatter
from maestro.config.settings import settings

def setup_logging():
    root_logger = logging.getLogger()
    
    # Limpa handlers existentes para evitar duplicação em reloads (ex: dev)
    if root_logger.hasHandlers():
        root_logger.handlers.clear()
        
    root_logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)

    if settings.environment.lower() == "local":
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
    else:
        formatter = JsonFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            rename_fields={"levelname": "level", "asctime": "timestamp"}
        )

    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
