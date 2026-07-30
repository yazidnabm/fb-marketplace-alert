"""
database.py — SQLite database handler untuk menyimpan listing dan mencegah duplikasi notifikasi.
"""

import sqlite3
import os
from datetime import datetime, timedelta
from typing import Optional

from logger_setup import get_logger
from models import Listing

logger = get_logger()


class Database:
    """Handler untuk SQLite database — anti-duplikat & history tracking."""

    def __init__(self, db_path: str = "marketplace.db"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Buat koneksi ke database."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Buat tabel jika belum ada."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # Tabel listings — menyimpan semua listing yang ditemukan
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS listings (
                    listing_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    price INTEGER,
                    currency TEXT DEFAULT 'IDR',
                    location TEXT,
                    condition TEXT,
                    url TEXT,
                    image_url TEXT,
                    posted_time TEXT,
                    matched_keyword TEXT,
                    found_at TEXT NOT NULL,
                    notified INTEGER DEFAULT 0
                )
            """)

            # Tabel notifications — log notifikasi yang dikirim
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    listing_id TEXT NOT NULL,
                    sent_at TEXT NOT NULL,
                    chat_id TEXT,
                    success INTEGER DEFAULT 1,
                    error_message TEXT,
                    FOREIGN KEY (listing_id) REFERENCES listings(listing_id)
                )
            """)

            # Index untuk query yang sering dipakai
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_listings_found_at
                ON listings(found_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_listings_keyword
                ON listings(matched_keyword)
            """)

            conn.commit()
            logger.info("Database initialized: %s", self.db_path)
        except sqlite3.Error as e:
            logger.error("Error initializing database: %s", e)
            raise
        finally:
            conn.close()

    def is_duplicate(self, listing_id: str) -> bool:
        """
        Cek apakah listing sudah pernah disimpan dan dinotifikasi.

        Args:
            listing_id: ID unik listing dari Facebook

        Returns:
            True jika listing sudah ada dan sudah dinotifikasi
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT notified FROM listings WHERE listing_id = ?",
                (listing_id,)
            )
            row = cursor.fetchone()
            if row is None:
                return False
            return bool(row["notified"])
        finally:
            conn.close()

    def save_listing(self, listing: Listing) -> bool:
        """
        Simpan listing baru ke database.

        Args:
            listing: Objek Listing yang akan disimpan

        Returns:
            True jika berhasil disimpan (listing baru), False jika sudah ada
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            data = listing.to_dict()
            cursor.execute("""
                INSERT OR IGNORE INTO listings
                (listing_id, title, price, currency, location, condition,
                 url, image_url, posted_time, matched_keyword, found_at)
                VALUES
                (:listing_id, :title, :price, :currency, :location, :condition,
                 :url, :image_url, :posted_time, :matched_keyword, :found_at)
            """, data)
            conn.commit()

            if cursor.rowcount > 0:
                logger.debug("Listing saved: %s — %s", listing.listing_id, listing.title)
                return True
            return False
        except sqlite3.Error as e:
            logger.error("Error saving listing %s: %s", listing.listing_id, e)
            return False
        finally:
            conn.close()

    def mark_notified(self, listing_id: str, chat_id: str, success: bool = True,
                      error_message: str = "") -> None:
        """
        Tandai listing sebagai sudah dinotifikasi.

        Args:
            listing_id: ID listing
            chat_id: Chat ID Telegram yang menerima notifikasi
            success: Apakah notifikasi berhasil dikirim
            error_message: Pesan error jika gagal
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # Update status notified di tabel listings
            if success:
                cursor.execute(
                    "UPDATE listings SET notified = 1 WHERE listing_id = ?",
                    (listing_id,)
                )

            # Log ke tabel notifications
            cursor.execute("""
                INSERT INTO notifications (listing_id, sent_at, chat_id, success, error_message)
                VALUES (?, ?, ?, ?, ?)
            """, (
                listing_id,
                datetime.now().isoformat(),
                chat_id,
                1 if success else 0,
                error_message,
            ))

            conn.commit()
        except sqlite3.Error as e:
            logger.error("Error marking notification for %s: %s", listing_id, e)
        finally:
            conn.close()

    def get_stats(self) -> dict:
        """
        Dapatkan statistik database.

        Returns:
            Dictionary dengan statistik: total_listings, total_notified, total_today
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) as count FROM listings")
            total_listings = cursor.fetchone()["count"]

            cursor.execute("SELECT COUNT(*) as count FROM listings WHERE notified = 1")
            total_notified = cursor.fetchone()["count"]

            today = datetime.now().strftime("%Y-%m-%d")
            cursor.execute(
                "SELECT COUNT(*) as count FROM listings WHERE found_at LIKE ?",
                (f"{today}%",)
            )
            total_today = cursor.fetchone()["count"]

            return {
                "total_listings": total_listings,
                "total_notified": total_notified,
                "total_today": total_today,
            }
        finally:
            conn.close()

    def cleanup_old_listings(self, days: int = 30) -> int:
        """
        Hapus listing yang lebih tua dari X hari untuk menghemat storage.

        Args:
            days: Jumlah hari sebelum listing dihapus (default: 30)

        Returns:
            Jumlah listing yang dihapus
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()

            # Hapus notifications terkait dulu
            cursor.execute("""
                DELETE FROM notifications WHERE listing_id IN (
                    SELECT listing_id FROM listings WHERE found_at < ?
                )
            """, (cutoff,))

            # Hapus listings lama
            cursor.execute(
                "DELETE FROM listings WHERE found_at < ?",
                (cutoff,)
            )
            deleted = cursor.rowcount
            conn.commit()

            if deleted > 0:
                logger.info("Cleaned up %d old listings (older than %d days)", deleted, days)
            return deleted
        except sqlite3.Error as e:
            logger.error("Error cleaning up old listings: %s", e)
            return 0
        finally:
            conn.close()
