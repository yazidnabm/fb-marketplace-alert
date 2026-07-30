"""
telegram_bot.py — Telegram bot handler untuk notifikasi dan kontrol bot.

Dual fungsi:
1. Kirim notifikasi listing baru ke user (foto + caption)
2. Menerima command dari user untuk kontrol bot
"""

import asyncio
import json
import os
from datetime import datetime
from typing import Callable, Optional

from telegram import Update, InputMediaPhoto, Bot
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from logger_setup import get_logger
from models import Listing, SearchCriteria

logger = get_logger()


import io
import urllib.request


class TelegramBot:
    """Telegram bot untuk notifikasi dan kontrol monitoring."""

    def __init__(
        self,
        token: str,
        chat_id: str,
        config_path: str = "config.json",
    ):
        """
        Inisialisasi Telegram bot.

        Args:
            token: Bot token dari BotFather
            chat_id: Chat ID user yang menerima notifikasi
            config_path: Path ke file config.json
        """
        self.token = token
        self.chat_id = chat_id
        self.config_path = config_path
        self.bot = Bot(token=token)
        self.application: Optional[Application] = None

        # Callback functions yang akan di-set oleh main.py
        self._on_start: Optional[Callable] = None
        self._on_stop: Optional[Callable] = None
        self._on_shutdown: Optional[Callable] = None
        self._get_status: Optional[Callable] = None
        self._is_monitoring: Optional[Callable] = None

        # Bot start time
        self.start_time = datetime.now()

    def set_callbacks(
        self,
        on_start: Callable,
        on_stop: Callable,
        get_status: Callable,
        is_monitoring: Callable,
        on_shutdown: Optional[Callable] = None,
    ):
        """
        Set callback functions dari main engine.

        Args:
            on_start: Fungsi untuk memulai monitoring
            on_stop: Fungsi untuk menghentikan monitoring
            get_status: Fungsi untuk mendapat status bot
            is_monitoring: Fungsi untuk cek apakah sedang monitoring
            on_shutdown: Fungsi untuk matikan bot secara total
        """
        self._on_start = on_start
        self._on_stop = on_stop
        self._get_status = get_status
        self._is_monitoring = is_monitoring
        self._on_shutdown = on_shutdown

    @staticmethod
    def _download_image(url: str) -> Optional[bytes]:
        """Download image bytes dengan User-Agent agar tidak diblokir CDN FB."""
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                }
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.read()
        except Exception:
            return None

    async def send_listing_notification(self, listing: Listing) -> bool:
        """
        Kirim notifikasi listing ke Telegram dengan foto dan caption.

        Args:
            listing: Listing yang akan dikirim

        Returns:
            True jika berhasil dikirim
        """
        try:
            caption = listing.to_telegram_caption()

            if listing.image_url:
                # Coba download bytes gambar terlebih dahulu
                img_bytes = await asyncio.get_event_loop().run_in_executor(
                    None, self._download_image, listing.image_url
                )
                photo_data = io.BytesIO(img_bytes) if img_bytes else listing.image_url

                try:
                    await self.bot.send_photo(
                        chat_id=self.chat_id,
                        photo=photo_data,
                        caption=caption,
                        parse_mode=ParseMode.MARKDOWN_V2,
                    )
                except Exception as photo_err:
                    logger.debug(
                        "Failed to send photo for listing %s (%s), sending text only",
                        listing.listing_id, photo_err
                    )
                    # Fallback: kirim tanpa parse mode jika markdown error
                    try:
                        await self.bot.send_message(
                            chat_id=self.chat_id,
                            text=caption,
                            parse_mode=ParseMode.MARKDOWN_V2,
                        )
                    except Exception:
                        # Final fallback: plain text
                        plain_caption = self._create_plain_caption(listing)
                        await self.bot.send_message(
                            chat_id=self.chat_id,
                            text=plain_caption,
                        )
            else:
                # Kirim teks saja
                try:
                    await self.bot.send_message(
                        chat_id=self.chat_id,
                        text=caption,
                        parse_mode=ParseMode.MARKDOWN_V2,
                    )
                except Exception:
                    plain_caption = self._create_plain_caption(listing)
                    await self.bot.send_message(
                        chat_id=self.chat_id,
                        text=plain_caption,
                    )

            logger.info("Notification sent for listing: %s", listing.listing_id)
            return True

        except Exception as e:
            logger.error(
                "Failed to send notification for listing %s: %s",
                listing.listing_id,
                e,
            )
            return False

    def _create_plain_caption(self, listing: Listing) -> str:
        """Buat caption plain text tanpa formatting Markdown."""
        lines = [
            f"📦 {listing.title}",
            f"💰 {listing.format_price()}",
        ]
        if listing.location:
            lines.append(f"📍 {listing.location}")
        if listing.condition:
            lines.append(f"🏷️ Kondisi: {listing.format_condition()}")
        if listing.posted_time:
            lines.append(f"🕐 {listing.posted_time}")
        if listing.matched_keyword:
            lines.append(f"🔍 Keyword: {listing.matched_keyword}")
        if listing.url:
            lines.append(f"\n🔗 {listing.url}")
        return "\n".join(lines)

    async def send_message(self, text: str, parse_mode: str = None) -> bool:
        """
        Kirim pesan teks biasa ke Telegram.

        Args:
            text: Pesan yang akan dikirim
            parse_mode: Mode parsing (MARKDOWN_V2, HTML, dll)

        Returns:
            True jika berhasil
        """
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=parse_mode,
            )
            return True
        except Exception as e:
            logger.error("Failed to send message: %s", e)
            return False

    # ========== Command Handlers ==========

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler untuk command /start — mulai monitoring."""
        if str(update.effective_chat.id) != self.chat_id:
            return

        if self._is_monitoring and self._is_monitoring():
            await update.message.reply_text("⚠️ Monitoring sudah berjalan!")
            return

        if self._on_start:
            self._on_start()
            await update.message.reply_text(
                "✅ *Monitoring dimulai\\!*\n\n"
                "Bot akan mengecek Facebook Marketplace secara berkala\\.\n"
                "Gunakan /status untuk melihat status bot\\.",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        else:
            await update.message.reply_text("❌ Bot belum siap.")

    async def _cmd_stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler untuk command /stop — hentikan monitoring."""
        if str(update.effective_chat.id) != self.chat_id:
            return

        if self._is_monitoring and not self._is_monitoring():
            await update.message.reply_text("⚠️ Monitoring sudah dihentikan.")
            return

        if self._on_stop:
            self._on_stop()
            await update.message.reply_text(
                "🛑 *Monitoring dihentikan\\.*\n"
                "Bot tetap siaga\\. Gunakan /start untuk mulai lagi, atau /shutdown untuk mematikan bot secara total\\.",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        else:
            await update.message.reply_text("❌ Bot belum siap.")

    async def _cmd_shutdown(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler untuk command /shutdown — matikan bot secara total dari Telegram."""
        if str(update.effective_chat.id) != self.chat_id:
            return

        await update.message.reply_text(
            "🔴 *Mematikan bot secara total...*\n"
            "Proses Python di VPS akan dihentikan\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        if self._on_shutdown:
            self._on_shutdown()

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler untuk command /status — lihat status bot."""
        if str(update.effective_chat.id) != self.chat_id:
            return

        status = {}
        if self._get_status:
            status = self._get_status()

        monitoring = "🟢 Aktif" if status.get("monitoring", False) else "🔴 Tidak aktif"
        uptime = self._format_uptime()

        # Load config untuk tampilkan info
        config = self._load_config()
        interval = config.get("check_interval_minutes", "?")
        city = config.get("location", {}).get("city", "?")

        db_stats = status.get("db_stats", {})
        total = db_stats.get("total_listings", 0)
        notified = db_stats.get("total_notified", 0)
        today = db_stats.get("total_today", 0)

        active_searches = sum(
            1 for s in config.get("searches", []) if s.get("enabled", True)
        )
        total_searches = len(config.get("searches", []))

        text = (
            f"📊 *Status Bot*\n\n"
            f"Status: {monitoring}\n"
            f"⏱️ Uptime: {uptime}\n"
            f"📍 Lokasi: {city}\n"
            f"⏰ Interval: setiap {interval} menit\n\n"
            f"📈 *Statistik*\n"
            f"Total listing ditemukan: {total}\n"
            f"Notifikasi terkirim: {notified}\n"
            f"Ditemukan hari ini: {today}\n\n"
            f"🔍 Kriteria aktif: {active_searches}/{total_searches}\n"
            f"Gunakan /list untuk melihat detail kriteria"
        )

        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

    async def _cmd_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler untuk command /list — lihat semua kriteria pencarian."""
        if str(update.effective_chat.id) != self.chat_id:
            return

        config = self._load_config()
        searches = config.get("searches", [])

        if not searches:
            await update.message.reply_text("📋 Belum ada kriteria pencarian.")
            return

        lines = ["📋 *Daftar Kriteria Pencarian*\n"]
        for i, s in enumerate(searches):
            status = "✅" if s.get("enabled", True) else "❌"
            cond = {
                "new": "Baru", "used": "Bekas", "all": "Semua"
            }.get(s.get("condition", "all"), s.get("condition", "all"))

            min_p = f"Rp {s.get('min_price', 0):,.0f}".replace(",", ".")
            max_p = f"Rp {s.get('max_price', 0):,.0f}".replace(",", ".")

            lines.append(
                f"{status} *{i + 1}.* `{s.get('keyword', '')}`\n"
                f"   💰 {min_p} - {max_p}\n"
                f"   🏷️ Kondisi: {cond}\n"
            )

        lines.append("\nGunakan /add atau /remove untuk mengubah daftar.")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)

    async def _cmd_add(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handler untuk command /add — tambah kriteria baru.
        Format: /add <keyword> <min_price> <max_price> <condition>
        Contoh: /add iPhone 13 3000000 7000000 used
        """
        if str(update.effective_chat.id) != self.chat_id:
            return

        args = context.args
        if not args or len(args) < 4:
            await update.message.reply_text(
                "⚠️ *Format salah\\!*\n\n"
                "Gunakan: `/add <keyword> <min\\_price> <max\\_price> <condition>`\n\n"
                "*Contoh:*\n"
                "`/add iPhone 13 3000000 7000000 used`\n"
                "`/add PS5 4000000 8000000 all`\n\n"
                "Condition: `new`, `used`, atau `all`",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            return

        try:
            # Parsing argumen — keyword bisa berupa beberapa kata
            condition = args[-1].lower()
            if condition not in ("new", "used", "all"):
                await update.message.reply_text("❌ Condition harus: new, used, atau all")
                return

            max_price = int(args[-2])
            min_price = int(args[-3])
            keyword = " ".join(args[:-3])

            if not keyword:
                await update.message.reply_text("❌ Keyword tidak boleh kosong!")
                return

            if min_price < 0 or max_price < 0:
                await update.message.reply_text("❌ Harga tidak boleh negatif!")
                return

            if min_price > max_price:
                await update.message.reply_text("❌ Min price tidak boleh lebih besar dari max price!")
                return

            # Simpan ke config
            config = self._load_config()
            new_search = {
                "keyword": keyword,
                "min_price": min_price,
                "max_price": max_price,
                "condition": condition,
                "enabled": True,
            }
            config.setdefault("searches", []).append(new_search)
            self._save_config(config)

            min_p = f"Rp {min_price:,.0f}".replace(",", ".")
            max_p = f"Rp {max_price:,.0f}".replace(",", ".")
            cond = {"new": "Baru", "used": "Bekas", "all": "Semua"}.get(condition, condition)

            await update.message.reply_text(
                f"✅ Kriteria baru ditambahkan!\n\n"
                f"🔍 Keyword: {keyword}\n"
                f"💰 Harga: {min_p} - {max_p}\n"
                f"🏷️ Kondisi: {cond}\n\n"
                f"Gunakan /list untuk melihat semua kriteria."
            )
            logger.info("New search criteria added via Telegram: %s", keyword)

        except (ValueError, IndexError) as e:
            await update.message.reply_text(
                f"❌ Error parsing argumen: {e}\n"
                f"Format: /add <keyword> <min_price> <max_price> <condition>"
            )

    async def _cmd_remove(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handler untuk command /remove — hapus kriteria.
        Format: /remove <index>
        Contoh: /remove 2
        """
        if str(update.effective_chat.id) != self.chat_id:
            return

        args = context.args
        if not args or len(args) != 1:
            await update.message.reply_text(
                "⚠️ Format: /remove <nomor>\n"
                "Gunakan /list untuk melihat nomor kriteria."
            )
            return

        try:
            index = int(args[0]) - 1  # Convert ke 0-indexed
            config = self._load_config()
            searches = config.get("searches", [])

            if index < 0 or index >= len(searches):
                await update.message.reply_text(
                    f"❌ Nomor tidak valid. Ada {len(searches)} kriteria."
                )
                return

            removed = searches.pop(index)
            config["searches"] = searches
            self._save_config(config)

            await update.message.reply_text(
                f"🗑️ Kriteria dihapus: `{removed.get('keyword', '')}`\n"
                f"Gunakan /list untuk melihat daftar terbaru.",
                parse_mode=ParseMode.MARKDOWN,
            )
            logger.info("Search criteria removed via Telegram: %s", removed.get("keyword"))

        except ValueError:
            await update.message.reply_text("❌ Nomor harus berupa angka!")

    async def _cmd_interval(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handler untuk command /interval — ubah interval pengecekan.
        Format: /interval <menit>
        """
        if str(update.effective_chat.id) != self.chat_id:
            return

        args = context.args
        if not args or len(args) != 1:
            config = self._load_config()
            current = config.get("check_interval_minutes", "?")
            await update.message.reply_text(
                f"⏰ Interval saat ini: {current} menit\n"
                f"Untuk mengubah: /interval <menit>\n"
                f"Contoh: /interval 10"
            )
            return

        try:
            minutes = int(args[0])
            if minutes < 1:
                await update.message.reply_text("❌ Interval minimal 1 menit!")
                return
            if minutes > 1440:
                await update.message.reply_text("❌ Interval maksimal 1440 menit (24 jam)!")
                return

            config = self._load_config()
            old_interval = config.get("check_interval_minutes", "?")
            config["check_interval_minutes"] = minutes
            self._save_config(config)

            await update.message.reply_text(
                f"✅ Interval diubah: {old_interval} → {minutes} menit\n\n"
                f"Perubahan akan aktif pada scan berikutnya."
            )
            logger.info("Interval changed via Telegram: %d minutes", minutes)

        except ValueError:
            await update.message.reply_text("❌ Menit harus berupa angka!")

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler untuk command /help — tampilkan bantuan."""
        if str(update.effective_chat.id) != self.chat_id:
            return

        help_text = (
            "🤖 *Facebook Marketplace Alert Bot*\n\n"
            "*Perintah tersedia:*\n\n"
            "▶️ /start \\- Mulai monitoring\n"
            "⏹️ /stop \\- Hentikan monitoring\n"
            "📊 /status \\- Lihat status bot\n"
            "📋 /list \\- Lihat semua kriteria pencarian\n"
            "➕ /add \\- Tambah kriteria baru\n"
            "   Format: `/add <keyword> <min> <max> <condition>`\n"
            "➖ /remove \\- Hapus kriteria\n"
            "   Format: `/remove <nomor>`\n"
            "⏰ /interval \\- Ubah interval pengecekan\n"
            "   Format: `/interval <menit>`\n"
            "🔴 /shutdown \\- Matikan bot secara total\n"
            "❓ /help \\- Tampilkan bantuan ini\n"
        )

        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN_V2)

    # ========== Utility Methods ==========

    def _load_config(self) -> dict:
        """Load konfigurasi dari file JSON."""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (IOError, json.JSONDecodeError) as e:
            logger.error("Failed to load config: %s", e)
            return {}

    def _save_config(self, config: dict):
        """Simpan konfigurasi ke file JSON."""
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            logger.debug("Config saved to %s", self.config_path)
        except IOError as e:
            logger.error("Failed to save config: %s", e)

    def _format_uptime(self) -> str:
        """Format uptime menjadi string yang readable."""
        delta = datetime.now() - self.start_time
        days = delta.days
        hours, remainder = divmod(delta.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        parts = []
        if days > 0:
            parts.append(f"{days}h")  # hari
        if hours > 0:
            parts.append(f"{hours}j")  # jam
        parts.append(f"{minutes}m")  # menit

        return " ".join(parts)

    # ========== Application Lifecycle ==========

    def build_application(self) -> Application:
        """
        Bangun Telegram Application dengan semua command handlers.

        Returns:
            Configured Application instance
        """
        self.application = (
            Application.builder()
            .token(self.token)
            .build()
        )

        # Register command handlers
        handlers = [
            ("start", self._cmd_start),
            ("stop", self._cmd_stop),
            ("shutdown", self._cmd_shutdown),
            ("exit", self._cmd_shutdown),
            ("status", self._cmd_status),
            ("list", self._cmd_list),
            ("add", self._cmd_add),
            ("remove", self._cmd_remove),
            ("interval", self._cmd_interval),
            ("help", self._cmd_help),
        ]

        for command, handler in handlers:
            self.application.add_handler(CommandHandler(command, handler))

        logger.info("Telegram application built with %d command handlers", len(handlers))
        return self.application

    async def start_polling(self):
        """Mulai polling untuk menerima command dari Telegram."""
        if self.application is None:
            self.build_application()

        logger.info("Starting Telegram bot polling...")
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling(drop_pending_updates=True)

    async def stop_polling(self):
        """Hentikan polling."""
        if self.application is not None:
            logger.info("Stopping Telegram bot polling...")
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()
