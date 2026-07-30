"""
main.py — Entry point utama Facebook Marketplace Alert Bot.

Menggabungkan semua module: scraper, database, telegram bot.
Menjalankan monitoring loop dan telegram command polling secara bersamaan.
"""

import asyncio
import json
import os
import signal
import sys
import threading
import time
from datetime import datetime
from typing import List

from dotenv import load_dotenv

from database import Database
from logger_setup import setup_logger, get_logger
from models import Listing, SearchCriteria
from scraper import FacebookMarketplaceScraper
from telegram_bot import TelegramBot

# Load environment variables
load_dotenv()

# Setup logger
logger = setup_logger()


class MarketplaceAlertBot:
    """Engine utama yang mengorkestrasi semua komponen bot."""

    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self.config = self._load_config()

        # Environment variables
        self.telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        self.fb_email = os.getenv("FACEBOOK_EMAIL", "")
        self.fb_password = os.getenv("FACEBOOK_PASSWORD", "")

        # Validasi
        self._validate_env()

        # Komponen
        self.db = Database()
        self.scraper = FacebookMarketplaceScraper(
            email=self.fb_email,
            password=self.fb_password,
            cookies_file=self.config.get("facebook_cookies_file", "cookies.json"),
            headless=True,
        )
        self.telegram = TelegramBot(
            token=self.telegram_token,
            chat_id=self.telegram_chat_id,
            config_path=self.config_path,
        )

        # State
        self._monitoring = False
        self._shutdown = False
        self._monitoring_task: asyncio.Task = None
        self._scan_count = 0
        self._start_time = datetime.now()

        # Event loop reference
        self._loop: asyncio.AbstractEventLoop = None

        # Setup telegram callbacks
        self.telegram.set_callbacks(
            on_start=self._on_start,
            on_stop=self._on_stop,
            get_status=self._get_status,
            is_monitoring=lambda: self._monitoring,
        )

        logger.info("MarketplaceAlertBot initialized")

    def _load_config(self) -> dict:
        """Load konfigurasi dari file JSON."""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            logger.info("Config loaded from %s", self.config_path)
            return config
        except (IOError, json.JSONDecodeError) as e:
            logger.error("Failed to load config: %s", e)
            sys.exit(1)

    def _reload_config(self) -> dict:
        """Reload config (untuk perubahan via Telegram command)."""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                self.config = json.load(f)
            return self.config
        except (IOError, json.JSONDecodeError) as e:
            logger.warning("Failed to reload config: %s", e)
            return self.config

    def _validate_env(self):
        """Validasi bahwa semua environment variables sudah di-set."""
        missing = []
        if not self.telegram_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not self.telegram_chat_id:
            missing.append("TELEGRAM_CHAT_ID")
        if not self.fb_email:
            missing.append("FACEBOOK_EMAIL")
        if not self.fb_password:
            missing.append("FACEBOOK_PASSWORD")

        if missing:
            logger.error(
                "Missing environment variables: %s", ", ".join(missing)
            )
            logger.error("Copy .env.example ke .env dan isi semua nilai!")
            sys.exit(1)

    def _get_search_criteria(self) -> List[SearchCriteria]:
        """Parse kriteria pencarian dari config yang sudah di-reload."""
        self._reload_config()
        criteria_list = []
        for s in self.config.get("searches", []):
            if s.get("enabled", True):
                criteria_list.append(
                    SearchCriteria(
                        keyword=s["keyword"],
                        min_price=s.get("min_price", 0),
                        max_price=s.get("max_price", 999999999),
                        condition=s.get("condition", "all"),
                        location=s.get("location", None),
                        max_post_age_hours=s.get("max_post_age_hours", None),
                        enabled=True,
                    )
                )
        return criteria_list

    def _on_start(self):
        """Callback ketika user kirim /start via Telegram."""
        if not self._monitoring and self._loop:
            self._monitoring = True
            self._monitoring_task = self._loop.create_task(self._monitoring_loop())
            logger.info("Monitoring started via Telegram command")

    def _on_stop(self):
        """Callback ketika user kirim /stop via Telegram."""
        self._monitoring = False
        if self._monitoring_task and not self._monitoring_task.done():
            self._monitoring_task.cancel()
        logger.info("Monitoring stopped via Telegram command")

    def _get_status(self) -> dict:
        """Callback untuk mendapat status bot."""
        return {
            "monitoring": self._monitoring,
            "scan_count": self._scan_count,
            "uptime": str(datetime.now() - self._start_time),
            "db_stats": self.db.get_stats(),
        }

    async def _do_single_scan(self):
        """Lakukan satu siklus scan untuk semua kriteria."""
        criteria_list = self._get_search_criteria()
        if not criteria_list:
            logger.warning("No active search criteria found!")
            return

        # Dapatkan daftar kota (bisa berupa list atau string)
        loc_cfg = self.config.get("location", {})
        if isinstance(loc_cfg.get("cities"), list):
            default_cities = loc_cfg["cities"]
        elif isinstance(loc_cfg.get("city"), list):
            default_cities = loc_cfg["city"]
        elif isinstance(loc_cfg.get("city"), str):
            default_cities = [loc_cfg["city"]]
        else:
            default_cities = ["Jakarta"]

        max_listings = self.config.get("max_listings_per_search", 30)
        global_max_age = self.config.get("max_post_age_hours", None)

        total_new = 0

        for criteria in criteria_list:
            if not self._monitoring:
                break

            # Gunakan kota spesifik kriteria jika ada, atau gunakan daftar kota global
            target_cities = [criteria.location] if criteria.location else default_cities
            max_age = criteria.max_post_age_hours if criteria.max_post_age_hours is not None else global_max_age

            for city in target_cities:
                if not self._monitoring:
                    break

                logger.info("Scanning: '%s' (city=%s) ...", criteria.keyword, city)

                # Scrape listings (blocking call, run in thread)
                listings = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda c=criteria, ct=city: self.scraper.scrape_listings(
                        c, city=ct, max_listings=max_listings
                    ),
                )

                # Process setiap listing
                for listing in listings:
                    if not self._monitoring:
                        break

                    # Cek umur postingan jika max_age di-set
                    if max_age is not None and not listing.is_within_max_age(max_age):
                        logger.info(
                            "Skipping listing '%s' (posted: '%s') — exceeds max age of %s hour(s)",
                            listing.title, listing.posted_time, max_age
                        )
                        continue

                    # Cek duplikat
                    if self.db.is_duplicate(listing.listing_id):
                        continue

                    # Simpan ke database
                    self.db.save_listing(listing)

                # Kirim notifikasi
                success = await self.telegram.send_listing_notification(listing)
                self.db.mark_notified(
                    listing_id=listing.listing_id,
                    chat_id=self.telegram_chat_id,
                    success=success,
                )

                if success:
                    total_new += 1

                # Delay antar notifikasi supaya tidak spam
                await asyncio.sleep(1.5)

            # Delay antar keyword
            if self._monitoring:
                await asyncio.sleep(3)

        self._scan_count += 1

        if total_new > 0:
            logger.info(
                "Scan #%d completed — %d new listings found and notified",
                self._scan_count,
                total_new,
            )
        else:
            logger.info("Scan #%d completed — no new listings", self._scan_count)

        # Cleanup old listings berkala (setiap 100 scan)
        if self._scan_count % 100 == 0:
            cleanup_days = self.config.get("auto_cleanup_days", 30)
            self.db.cleanup_old_listings(days=cleanup_days)

    async def _monitoring_loop(self):
        """Loop utama monitoring — scan berulang sesuai interval."""
        logger.info("Monitoring loop started")

        while self._monitoring and not self._shutdown:
            try:
                await self._do_single_scan()
            except Exception as e:
                logger.error("Error during scan: %s", e)

                # Coba restart browser jika error
                try:
                    logger.info("Attempting to restart browser session...")
                    success = await asyncio.get_event_loop().run_in_executor(
                        None, self.scraper.restart
                    )
                    if success:
                        logger.info("Browser session restarted successfully")
                    else:
                        logger.error("Failed to restart browser session")
                except Exception as restart_err:
                    logger.error("Error restarting browser: %s", restart_err)

            if not self._monitoring or self._shutdown:
                break

            # Reload config untuk mendapat interval terbaru
            self._reload_config()
            interval = self.config.get("check_interval_minutes", 5) * 60

            logger.info("Next scan in %d minutes...", interval // 60)

            # Sleep dengan pengecekan berkala supaya bisa stop cepat
            for _ in range(interval):
                if not self._monitoring or self._shutdown:
                    break
                await asyncio.sleep(1)

        logger.info("Monitoring loop ended")

    async def run(self):
        """Jalankan bot — Telegram polling + monitoring loop."""
        self._loop = asyncio.get_event_loop()

        # Setup signal handlers untuk graceful shutdown
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                self._loop.add_signal_handler(sig, self._signal_handler)
            except NotImplementedError:
                # Windows tidak support add_signal_handler
                signal.signal(sig, lambda s, f: self._signal_handler())

        logger.info("=" * 60)
        logger.info("Facebook Marketplace Alert Bot Starting...")
        logger.info("=" * 60)

        # Login ke Facebook (dengan retry)
        max_retries = 3
        login_success = False
        for attempt in range(1, max_retries + 1):
            logger.info("Logging in to Facebook... (attempt %d/%d)", attempt, max_retries)
            login_success = await asyncio.get_event_loop().run_in_executor(
                None, self.scraper.login
            )
            if login_success:
                break
            logger.warning("Login attempt %d failed", attempt)
            if attempt < max_retries:
                logger.info("Retrying in 10 seconds...")
                await asyncio.sleep(10)
                # Restart browser sebelum retry
                await asyncio.get_event_loop().run_in_executor(
                    None, self.scraper.close
                )

        if not login_success:
            logger.error("Failed to login to Facebook after %d attempts!", max_retries)
            await self.telegram.send_message(
                "❌ Bot gagal login ke Facebook!\n\n"
                "Kemungkinan penyebab:\n"
                "1. Facebook mendeteksi bot/VPS IP\n"
                "2. Ada cookie consent/captcha yang menghalangi\n"
                "3. Akun kena checkpoint/2FA\n"
                "4. Email/password salah\n\n"
                "📂 Cek folder debug/ di VPS untuk screenshot & HTML halaman.\n"
                "Jalankan: ls debug/"
            )
            return

        logger.info("Facebook login successful!")

        # Kirim pesan startup ke Telegram
        await self.telegram.send_message(
            "🚀 *Bot Started\\!*\n\n"
            "Facebook Marketplace Alert Bot sudah aktif\\.\n"
            "Gunakan /start untuk memulai monitoring\\.\n"
            "Gunakan /help untuk melihat semua perintah\\.",
            parse_mode="MarkdownV2",
        )

        # Mulai Telegram polling
        await self.telegram.start_polling()

        # Bot siap, tunggu command dari user
        logger.info("Bot ready! Waiting for commands via Telegram...")
        logger.info("Send /start to begin monitoring")

        # Keep running sampai shutdown
        try:
            while not self._shutdown:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            await self._cleanup()

    def _signal_handler(self):
        """Handle SIGINT/SIGTERM untuk graceful shutdown."""
        logger.info("Shutdown signal received...")
        self._shutdown = True
        self._monitoring = False

    async def _cleanup(self):
        """Bersihkan resources saat shutdown."""
        logger.info("Cleaning up...")

        # Stop monitoring
        self._monitoring = False

        # Kirim pesan shutdown
        try:
            await self.telegram.send_message("🔴 Bot shutting down...")
        except Exception:
            pass

        # Stop Telegram polling
        try:
            await self.telegram.stop_polling()
        except Exception as e:
            logger.warning("Error stopping Telegram: %s", e)

        # Close browser
        try:
            self.scraper.close()
        except Exception as e:
            logger.warning("Error closing scraper: %s", e)

        logger.info("Cleanup complete. Goodbye!")


def main():
    """Entry point."""
    # Cek file config
    if not os.path.exists("config.json"):
        print("ERROR: config.json tidak ditemukan!")
        print("Buat file config.json terlebih dahulu. Lihat README.md untuk contoh.")
        sys.exit(1)

    # Cek .env file
    if not os.path.exists(".env"):
        print("ERROR: .env file tidak ditemukan!")
        print("Copy .env.example ke .env dan isi semua nilai.")
        sys.exit(1)

    bot = MarketplaceAlertBot()

    # Jalankan bot
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error("Fatal error: %s", e)
        raise


if __name__ == "__main__":
    main()
