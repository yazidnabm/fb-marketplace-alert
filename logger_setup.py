"""
logger_setup.py — Konfigurasi logging untuk bot
Rotating file handler (max 5MB, 3 backup) + console output
"""

import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logger(
    name: str = "fb_marketplace_bot",
    log_file: str = "bot.log",
    log_dir: str = "logs",
    level: int = logging.INFO,
    max_bytes: int = 5 * 1024 * 1024,  # 5MB
    backup_count: int = 3,
) -> logging.Logger:
    """
    Setup logger dengan rotating file handler dan console handler.

    Args:
        name: Nama logger
        log_file: Nama file log
        log_dir: Direktori untuk menyimpan file log
        level: Level logging (default: INFO)
        max_bytes: Ukuran maksimal file log sebelum rotate (default: 5MB)
        backup_count: Jumlah file backup yang disimpan (default: 3)

    Returns:
        Configured logger instance
    """
    # Buat direktori log jika belum ada
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, log_file)

    # Buat logger
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Hindari duplicate handlers
    if logger.handlers:
        return logger

    # Format log
    formatter = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)-8s] [%(module)-15s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rotating File Handler
    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    # Tambahkan handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    logger.info("Logger initialized — log file: %s", log_path)
    return logger


def get_logger(name: str = "fb_marketplace_bot") -> logging.Logger:
    """Dapatkan existing logger instance."""
    return logging.getLogger(name)
