"""
models.py — Data classes untuk listing Facebook Marketplace
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Listing:
    """Representasi satu listing dari Facebook Marketplace."""
    listing_id: str
    title: str
    price: int
    currency: str = "IDR"
    location: str = ""
    condition: str = ""  # "new", "used", atau kosong
    url: str = ""
    image_url: str = ""
    posted_time: str = ""
    matched_keyword: str = ""
    found_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def format_price(self) -> str:
        """Format harga ke format Rupiah: Rp 5.000.000"""
        return f"Rp {self.price:,.0f}".replace(",", ".")

    def format_condition(self) -> str:
        """Terjemahkan kondisi ke Bahasa Indonesia."""
        mapping = {
            "new": "Baru",
            "used": "Bekas",
            "": "Tidak diketahui",
        }
        return mapping.get(self.condition.lower(), self.condition)

    def to_telegram_caption(self) -> str:
        """Format listing menjadi caption Telegram yang informatif."""
        lines = [
            f"📦 *{self._escape_md(self.title)}*",
            f"💰 {self.format_price()}",
            f"📍 {self._escape_md(self.location)}" if self.location else None,
            f"🏷️ Kondisi: {self.format_condition()}" if self.condition else None,
            f"🕐 {self._escape_md(self.posted_time)}" if self.posted_time else None,
            f"🔍 Keyword: _{self._escape_md(self.matched_keyword)}_" if self.matched_keyword else None,
            "",
            f"🔗 [Lihat Listing]({self.url})" if self.url else None,
        ]
        return "\n".join(line for line in lines if line is not None)

    def to_dict(self) -> dict:
        """Konversi ke dictionary untuk penyimpanan database."""
        return {
            "listing_id": self.listing_id,
            "title": self.title,
            "price": self.price,
            "currency": self.currency,
            "location": self.location,
            "condition": self.condition,
            "url": self.url,
            "image_url": self.image_url,
            "posted_time": self.posted_time,
            "matched_keyword": self.matched_keyword,
            "found_at": self.found_at,
        }

    @staticmethod
    def _escape_md(text: str) -> str:
        """Escape karakter khusus untuk Markdown V2 Telegram."""
        special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#',
                         '+', '-', '=', '|', '{', '}', '.', '!']
        for char in special_chars:
            text = text.replace(char, f"\\{char}")
        return text


@dataclass
class SearchCriteria:
    """Representasi satu kriteria pencarian."""
    keyword: str
    min_price: int = 0
    max_price: int = 999999999
    condition: str = "all"  # "new", "used", atau "all"
    enabled: bool = True

    def matches_listing(self, listing: Listing) -> bool:
        """Cek apakah listing cocok dengan kriteria ini."""
        # Cek harga
        if listing.price < self.min_price or listing.price > self.max_price:
            return False

        # Cek kondisi
        if self.condition != "all" and listing.condition:
            if listing.condition.lower() != self.condition.lower():
                return False

        return True

    def to_display_string(self, index: int) -> str:
        """Format kriteria untuk ditampilkan di Telegram."""
        status = "✅" if self.enabled else "❌"
        cond = {"new": "Baru", "used": "Bekas", "all": "Semua"}.get(
            self.condition, self.condition
        )
        min_p = f"Rp {self.min_price:,.0f}".replace(",", ".")
        max_p = f"Rp {self.max_price:,.0f}".replace(",", ".")
        return (
            f"{status} *{index}*\\. `{self.keyword}`\n"
            f"   💰 {min_p} \\- {max_p}\n"
            f"   🏷️ Kondisi: {cond}"
        )
