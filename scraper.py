"""
scraper.py — Selenium scraper untuk Facebook Marketplace.

Menggunakan headless Chrome untuk scraping listing dari Facebook Marketplace
dengan berbagai teknik anti-detection.
"""

import json
import os
import random
import re
import time
import hashlib
from typing import List, Optional
from urllib.parse import quote_plus, urlencode

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    WebDriverException,
    StaleElementReferenceException,
)
from webdriver_manager.chrome import ChromeDriverManager

from logger_setup import get_logger
from models import Listing, SearchCriteria

logger = get_logger()

# Daftar User-Agent untuk rotasi
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
]


class FacebookMarketplaceScraper:
    """Scraper untuk Facebook Marketplace menggunakan Selenium."""

    MARKETPLACE_BASE_URL = "https://www.facebook.com/marketplace"

    def __init__(
        self,
        email: str,
        password: str,
        cookies_file: str = "cookies.json",
        headless: bool = True,
    ):
        """
        Inisialisasi scraper.

        Args:
            email: Email/username Facebook
            password: Password Facebook
            cookies_file: Path file untuk menyimpan cookies
            headless: Jalankan browser tanpa GUI (untuk VPS)
        """
        self.email = email
        self.password = password
        self.cookies_file = cookies_file
        self.headless = headless
        self.driver: Optional[webdriver.Chrome] = None
        self._is_logged_in = False

    def _get_chrome_options(self) -> Options:
        """Konfigurasi Chrome options dengan anti-detection."""
        options = Options()

        if self.headless:
            options.add_argument("--headless=new")

        # Anti-detection arguments
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--start-maximized")
        options.add_argument("--disable-infobars")
        options.add_argument("--lang=id-ID")

        # Random user agent
        user_agent = random.choice(USER_AGENTS)
        options.add_argument(f"--user-agent={user_agent}")
        logger.debug("Using User-Agent: %s", user_agent[:50])

        # Sembunyikan tanda-tanda automation
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        return options

    def _init_driver(self):
        """Inisialisasi Selenium WebDriver."""
        if self.driver is not None:
            return

        try:
            options = self._get_chrome_options()
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=options)

            # Override navigator.webdriver property
            self.driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {
                    "source": """
                        Object.defineProperty(navigator, 'webdriver', {
                            get: () => undefined
                        });
                        // Override plugins
                        Object.defineProperty(navigator, 'plugins', {
                            get: () => [1, 2, 3, 4, 5]
                        });
                        // Override languages
                        Object.defineProperty(navigator, 'languages', {
                            get: () => ['id-ID', 'id', 'en-US', 'en']
                        });
                    """
                },
            )

            # Set implicit wait
            self.driver.implicitly_wait(10)
            logger.info("Chrome WebDriver initialized successfully")
        except WebDriverException as e:
            logger.error("Failed to initialize WebDriver: %s", e)
            raise

    def _random_delay(self, min_sec: float = 2.0, max_sec: float = 6.0):
        """Delay acak untuk meniru perilaku manusia."""
        delay = random.uniform(min_sec, max_sec)
        time.sleep(delay)

    def _human_type(self, element, text: str):
        """Ketik teks dengan kecepatan yang bervariasi seperti manusia."""
        for char in text:
            element.send_keys(char)
            time.sleep(random.uniform(0.05, 0.2))

    def _save_cookies(self):
        """Simpan cookies ke file JSON."""
        if self.driver is None:
            return
        try:
            cookies = self.driver.get_cookies()
            with open(self.cookies_file, "w", encoding="utf-8") as f:
                json.dump(cookies, f, indent=2)
            logger.debug("Cookies saved to %s", self.cookies_file)
        except (IOError, json.JSONDecodeError) as e:
            logger.warning("Failed to save cookies: %s", e)

    def _load_cookies(self) -> bool:
        """
        Load cookies dari file JSON.

        Returns:
            True jika cookies berhasil di-load
        """
        if not os.path.exists(self.cookies_file):
            return False

        try:
            with open(self.cookies_file, "r", encoding="utf-8") as f:
                cookies = json.load(f)

            # Navigate ke Facebook dulu sebelum set cookies
            self.driver.get("https://www.facebook.com")
            self._random_delay(2, 4)

            for cookie in cookies:
                # Hapus field yang bisa menyebabkan error
                cookie.pop("sameSite", None)
                cookie.pop("expiry", None)
                try:
                    self.driver.add_cookie(cookie)
                except Exception:
                    continue

            logger.info("Cookies loaded from %s", self.cookies_file)
            return True
        except (IOError, json.JSONDecodeError, Exception) as e:
            logger.warning("Failed to load cookies: %s", e)
            return False

    def login(self) -> bool:
        """
        Login ke Facebook. Coba pakai cookies dulu, kalau gagal login manual.

        Returns:
            True jika login berhasil
        """
        self._init_driver()

        # Coba load cookies terlebih dahulu
        if self._load_cookies():
            self.driver.get("https://www.facebook.com")
            self._random_delay(3, 5)

            # Cek apakah sudah login
            if self._check_logged_in():
                logger.info("Login via cookies berhasil")
                self._is_logged_in = True
                return True
            else:
                logger.info("Cookies expired, melakukan login manual...")

        # Login manual
        return self._manual_login()

    def _dismiss_cookie_dialog(self):
        """Dismiss cookie consent dialog jika muncul."""
        cookie_selectors = [
            # Tombol "Allow all cookies" / "Accept all"
            (By.CSS_SELECTOR, '[data-cookiebanner="accept_button"]'),
            (By.CSS_SELECTOR, '[data-testid="cookie-policy-manage-dialog-accept-button"]'),
            (By.XPATH, '//button[contains(text(), "Allow")]'),
            (By.XPATH, '//button[contains(text(), "Izinkan")]'),
            (By.XPATH, '//button[contains(text(), "Accept")]'),
            (By.XPATH, '//button[contains(text(), "Terima")]'),
            (By.XPATH, '//button[contains(text(), "Allow all cookies")]'),
            (By.XPATH, '//button[contains(text(), "Allow essential and optional cookies")]'),
            # Tombol "Decline optional cookies"
            (By.XPATH, '//button[contains(text(), "Decline")]'),
            (By.XPATH, '//button[contains(text(), "Tolak")]'),
            # Generic close buttons
            (By.CSS_SELECTOR, '[aria-label="Close"]'),
            (By.CSS_SELECTOR, '[aria-label="Tutup"]'),
        ]

        for by, selector in cookie_selectors:
            try:
                btn = self.driver.find_element(by, selector)
                if btn.is_displayed():
                    btn.click()
                    logger.info("Cookie dialog dismissed with selector: %s", selector)
                    self._random_delay(2, 3)
                    return True
            except (NoSuchElementException, Exception):
                continue

        return False

    def _find_element_multi(self, selectors: list, timeout: int = 15):
        """
        Cari elemen menggunakan beberapa selector strategy.
        Mengembalikan elemen pertama yang ditemukan.

        Args:
            selectors: List of (By, selector) tuples
            timeout: Timeout dalam detik

        Returns:
            WebElement jika ditemukan, None jika tidak
        """
        end_time = time.time() + timeout
        while time.time() < end_time:
            for by, selector in selectors:
                try:
                    element = self.driver.find_element(by, selector)
                    if element.is_displayed():
                        logger.debug("Element found with selector: %s", selector)
                        return element
                except (NoSuchElementException, StaleElementReferenceException):
                    continue
            time.sleep(0.5)

        return None

    def _manual_login(self) -> bool:
        """Login manual dengan email dan password."""
        try:
            # Pertama, buka halaman utama Facebook untuk handle redirect
            logger.info("Navigating to Facebook...")
            self.driver.get("https://www.facebook.com")
            self._random_delay(3, 5)

            # Screenshot halaman awal untuk debugging
            self._save_debug_screenshot("before_login")
            logger.info("Current URL: %s", self.driver.current_url)
            logger.info("Page title: %s", self.driver.title)

            # Dismiss cookie consent dialog jika ada
            self._dismiss_cookie_dialog()
            self._random_delay(1, 2)

            # Cek apakah sudah di halaman login atau perlu navigate
            if "/login" not in self.driver.current_url:
                logger.info("Navigating to login page...")
                self.driver.get("https://www.facebook.com/login")
                self._random_delay(3, 5)

                # Dismiss cookie dialog lagi jika muncul di halaman login
                self._dismiss_cookie_dialog()
                self._random_delay(1, 2)

            # Screenshot halaman login
            self._save_debug_screenshot("login_page")
            logger.info("Login page URL: %s", self.driver.current_url)

            # Cari email field dengan multiple selectors
            email_selectors = [
                (By.ID, "email"),
                (By.NAME, "email"),
                (By.CSS_SELECTOR, 'input[name="email"]'),
                (By.CSS_SELECTOR, 'input[type="email"]'),
                (By.CSS_SELECTOR, 'input#email'),
                (By.XPATH, '//input[@id="email"]'),
                (By.XPATH, '//input[@name="email"]'),
                (By.XPATH, '//input[@type="text" and @data-testid="royal_email"]'),
            ]

            email_field = self._find_element_multi(email_selectors, timeout=20)
            if not email_field:
                logger.error("Email field not found! Saving debug info...")
                self._save_debug_screenshot("email_field_not_found")
                # Log page source untuk debugging
                self._save_page_source("login_page")
                return False

            logger.info("Email field found, typing email...")
            email_field.clear()
            self._human_type(email_field, self.email)
            self._random_delay(0.5, 1.5)

            # Cari password field
            pass_selectors = [
                (By.ID, "pass"),
                (By.NAME, "pass"),
                (By.CSS_SELECTOR, 'input[name="pass"]'),
                (By.CSS_SELECTOR, 'input[type="password"]'),
                (By.XPATH, '//input[@id="pass"]'),
                (By.XPATH, '//input[@type="password"]'),
            ]

            pass_field = self._find_element_multi(pass_selectors, timeout=10)
            if not pass_field:
                logger.error("Password field not found!")
                self._save_debug_screenshot("pass_field_not_found")
                return False

            logger.info("Password field found, typing password...")
            pass_field.clear()
            self._human_type(pass_field, self.password)
            self._random_delay(0.5, 1.5)

            # Cari dan klik tombol login
            login_selectors = [
                (By.NAME, "login"),
                (By.ID, "loginbutton"),
                (By.CSS_SELECTOR, 'button[name="login"]'),
                (By.CSS_SELECTOR, 'button[type="submit"]'),
                (By.CSS_SELECTOR, 'input[type="submit"]'),
                (By.XPATH, '//button[@name="login"]'),
                (By.XPATH, '//button[@type="submit"]'),
                (By.XPATH, '//button[contains(text(), "Log In")]'),
                (By.XPATH, '//button[contains(text(), "Masuk")]'),
                (By.CSS_SELECTOR, '[data-testid="royal_login_button"]'),
            ]

            login_button = self._find_element_multi(login_selectors, timeout=10)
            if not login_button:
                # Fallback: tekan Enter di password field
                logger.warning("Login button not found, pressing Enter...")
                pass_field.send_keys(Keys.RETURN)
            else:
                logger.info("Login button found, clicking...")
                login_button.click()

            self._random_delay(5, 8)

            # Screenshot setelah klik login
            self._save_debug_screenshot("after_login_click")
            logger.info("Post-login URL: %s", self.driver.current_url)

            # Cek apakah login berhasil
            if self._check_logged_in():
                logger.info("Login manual berhasil!")
                self._save_cookies()
                self._is_logged_in = True
                return True
            else:
                logger.error("Login gagal — mungkin ada checkpoint/2FA")
                logger.error("Current URL: %s", self.driver.current_url)
                self._save_debug_screenshot("login_failed")
                self._save_page_source("login_failed")
                return False

        except Exception as e:
            logger.error("Login error: %s", type(e).__name__)
            logger.error("Error details: %s", str(e)[:500])
            self._save_debug_screenshot("login_error")
            self._save_page_source("login_error")
            return False

    def _save_page_source(self, name: str):
        """Simpan page source HTML untuk debugging."""
        try:
            os.makedirs("debug", exist_ok=True)
            filename = f"debug/{name}_{int(time.time())}.html"
            with open(filename, "w", encoding="utf-8") as f:
                f.write(self.driver.page_source)
            logger.info("Page source saved: %s", filename)
        except Exception as e:
            logger.warning("Failed to save page source: %s", e)

    def _check_logged_in(self) -> bool:
        """Cek apakah user sudah login ke Facebook."""
        try:
            # Cek apakah ada elemen yang menunjukkan sudah login
            # Facebook biasanya redirect ke halaman utama setelah login
            current_url = self.driver.current_url
            page_source = self.driver.page_source.lower()

            # Jika masih di halaman login, berarti belum login
            if "/login" in current_url and "checkpoint" not in current_url:
                return False

            # Cek elemen yang biasa muncul setelah login
            indicators = [
                (By.CSS_SELECTOR, '[aria-label="Facebook"]'),
                (By.CSS_SELECTOR, '[aria-label="Your profile"]'),
                (By.CSS_SELECTOR, '[aria-label="Profil Anda"]'),
                (By.CSS_SELECTOR, '[role="banner"]'),
            ]

            for by, selector in indicators:
                try:
                    self.driver.find_element(by, selector)
                    return True
                except NoSuchElementException:
                    continue

            # Fallback: cek page source
            if "marketplace" in page_source or "feed" in page_source:
                return True

            return False
        except Exception as e:
            logger.warning("Error checking login status: %s", e)
            return False

    def _save_debug_screenshot(self, name: str):
        """Simpan screenshot untuk debugging."""
        try:
            os.makedirs("debug", exist_ok=True)
            filename = f"debug/{name}_{int(time.time())}.png"
            self.driver.save_screenshot(filename)
            logger.debug("Debug screenshot saved: %s", filename)
        except Exception as e:
            logger.warning("Failed to save screenshot: %s", e)

    def _build_marketplace_url(
        self,
        keyword: str,
        city: str = "Jakarta",
        min_price: int = 0,
        max_price: int = 0,
        condition: str = "all",
    ) -> str:
        """
        Bangun URL Facebook Marketplace dengan filter.

        Args:
            keyword: Kata kunci pencarian
            city: Kota/lokasi
            min_price: Harga minimum
            max_price: Harga maksimum
            condition: Kondisi barang ("new", "used", "all")

        Returns:
            URL lengkap untuk Facebook Marketplace
        """
        # Base URL marketplace search
        base = f"{self.MARKETPLACE_BASE_URL}/search"

        params = {
            "query": keyword,
            "sortBy": "creation_time_descend",  # Terbaru dulu
            "exact": "false",
        }

        if min_price > 0:
            params["minPrice"] = str(min_price)
        if max_price > 0:
            params["maxPrice"] = str(max_price)

        # Kondisi barang
        if condition == "new":
            params["itemCondition"] = "new"
        elif condition == "used":
            params["itemCondition"] = "used_good"

        url = f"{base}?{urlencode(params)}"
        logger.debug("Built marketplace URL: %s", url)
        return url

    def _scroll_page(self, scroll_count: int = 3):
        """Scroll halaman ke bawah untuk memuat lebih banyak listing."""
        for i in range(scroll_count):
            self.driver.execute_script(
                "window.scrollTo(0, document.body.scrollHeight);"
            )
            self._random_delay(2, 4)
            logger.debug("Scrolled page (%d/%d)", i + 1, scroll_count)

    def _extract_listing_id(self, url: str) -> str:
        """Extract listing ID dari URL atau generate hash."""
        # Coba extract ID dari URL pattern: /marketplace/item/123456789/
        match = re.search(r"/item/(\d+)", url)
        if match:
            return match.group(1)

        # Fallback: generate hash dari URL
        return hashlib.md5(url.encode()).hexdigest()[:16]

    def _parse_price(self, price_text: str) -> int:
        """
        Parse teks harga menjadi integer.

        Contoh input: "Rp5.000.000", "Rp 3.500.000", "IDR 5000000"
        """
        if not price_text:
            return 0

        # Hapus semua karakter non-digit
        digits = re.sub(r"[^\d]", "", price_text)
        try:
            return int(digits)
        except ValueError:
            return 0

    def scrape_listings(
        self,
        criteria: SearchCriteria,
        city: str = "Jakarta",
        max_listings: int = 30,
    ) -> List[Listing]:
        """
        Scrape listing dari Facebook Marketplace berdasarkan kriteria.

        Args:
            criteria: Kriteria pencarian
            city: Kota/lokasi pencarian
            max_listings: Jumlah maksimal listing yang diambil

        Returns:
            List of Listing objects
        """
        if not self._is_logged_in:
            logger.error("Not logged in! Call login() first.")
            return []

        url = self._build_marketplace_url(
            keyword=criteria.keyword,
            city=city,
            min_price=criteria.min_price,
            max_price=criteria.max_price,
            condition=criteria.condition,
        )

        listings = []

        try:
            logger.info("Scraping: '%s' (city=%s)", criteria.keyword, city)
            self.driver.get(url)
            self._random_delay(4, 7)

            # Cek apakah halaman berhasil dimuat
            if "login" in self.driver.current_url.lower():
                logger.warning("Redirected to login page — session expired")
                self._is_logged_in = False
                return []

            # Scroll untuk memuat lebih banyak listing
            scroll_count = max(1, max_listings // 10)
            self._scroll_page(min(scroll_count, 5))

            # Parse listing items
            listings = self._parse_listing_items(criteria.keyword, max_listings)
            logger.info(
                "Found %d listings for '%s'", len(listings), criteria.keyword
            )

        except TimeoutException:
            logger.warning("Timeout while scraping '%s'", criteria.keyword)
            self._save_debug_screenshot(f"timeout_{criteria.keyword}")
        except WebDriverException as e:
            logger.error("WebDriver error while scraping '%s': %s", criteria.keyword, e)
            self._save_debug_screenshot(f"error_{criteria.keyword}")
        except Exception as e:
            logger.error("Unexpected error scraping '%s': %s", criteria.keyword, e)

        return listings

    def _parse_listing_items(
        self, keyword: str, max_listings: int
    ) -> List[Listing]:
        """
        Parse elemen listing dari halaman yang sudah dimuat.

        Facebook Marketplace menggunakan struktur DOM yang sering berubah,
        jadi kita menggunakan beberapa strategi pencarian.
        """
        listings = []

        # Strategi 1: Cari link yang mengarah ke /marketplace/item/
        try:
            item_links = self.driver.find_elements(
                By.CSS_SELECTOR, 'a[href*="/marketplace/item/"]'
            )

            seen_ids = set()
            for link in item_links[:max_listings * 2]:  # Ambil lebih banyak, filter nanti
                try:
                    href = link.get_attribute("href") or ""
                    listing_id = self._extract_listing_id(href)

                    if listing_id in seen_ids:
                        continue
                    seen_ids.add(listing_id)

                    # Cari parent container untuk mendapat info lengkap
                    listing = self._extract_listing_from_element(
                        link, listing_id, href, keyword
                    )
                    if listing:
                        listings.append(listing)

                    if len(listings) >= max_listings:
                        break

                except StaleElementReferenceException:
                    continue
                except Exception as e:
                    logger.debug("Error parsing listing element: %s", e)
                    continue

        except NoSuchElementException:
            logger.warning("No listing elements found on page")

        # Jika strategi 1 gagal, coba strategi 2
        if not listings:
            listings = self._parse_listings_alternative(keyword, max_listings)

        return listings

    def _extract_listing_from_element(
        self,
        element,
        listing_id: str,
        url: str,
        keyword: str,
    ) -> Optional[Listing]:
        """Extract informasi listing dari elemen DOM."""
        try:
            # Navigasi ke parent container
            # Facebook biasanya membungkus listing dalam beberapa level div
            container = element

            # Coba naik ke parent untuk mendapat lebih banyak info
            for _ in range(5):
                parent = container.find_element(By.XPATH, "./..")
                if parent.tag_name == "body":
                    break
                container = parent

            # Extract teks dari container
            full_text = container.text.strip()
            lines = [l.strip() for l in full_text.split("\n") if l.strip()]

            # Parse informasi dari teks
            title = ""
            price_text = ""
            location = ""
            condition = ""

            for line in lines:
                # Identifikasi harga (biasanya dimulai dengan Rp)
                if re.match(r"^Rp\s?[\d.,]+", line) or re.match(r"^IDR\s?[\d.,]+", line):
                    if not price_text:
                        price_text = line
                # Identifikasi kondisi
                elif line.lower() in ["baru", "new", "bekas", "used", "seperti baru", "baik"]:
                    condition = "new" if line.lower() in ["baru", "new", "seperti baru"] else "used"
                # Identifikasi lokasi (biasanya mengandung nama kota)
                elif any(
                    kota in line.lower()
                    for kota in [
                        "jakarta", "surabaya", "bandung", "medan", "semarang",
                        "makassar", "palembang", "tangerang", "depok", "bekasi",
                        "bogor", "yogyakarta", "malang", "solo", "batam",
                        "kota", "kabupaten", "kec.", "kel.",
                    ]
                ):
                    if not location:
                        location = line
                # Sisanya kemungkinan judul
                elif not title and len(line) > 3 and line != price_text:
                    title = line

            # Jika tidak ada judul yang terdeteksi, gunakan line pertama
            if not title and lines:
                title = lines[0]

            price = self._parse_price(price_text)

            # Cari gambar
            image_url = ""
            try:
                img = container.find_element(By.TAG_NAME, "img")
                image_url = img.get_attribute("src") or ""
            except NoSuchElementException:
                pass

            # Cari waktu posting
            posted_time = ""
            for line in lines:
                if any(
                    w in line.lower()
                    for w in ["menit", "jam", "hari", "minggu", "bulan",
                              "minute", "hour", "day", "week", "month",
                              "baru saja", "just now", "yesterday", "kemarin"]
                ):
                    posted_time = line
                    break

            # Buat clean URL
            clean_url = url.split("?")[0] if url else ""
            if not clean_url.startswith("http"):
                clean_url = f"https://www.facebook.com{clean_url}"

            if not title:
                return None

            return Listing(
                listing_id=listing_id,
                title=title,
                price=price,
                location=location,
                condition=condition,
                url=clean_url,
                image_url=image_url,
                posted_time=posted_time,
                matched_keyword=keyword,
            )

        except Exception as e:
            logger.debug("Error extracting listing info: %s", e)
            return None

    def _parse_listings_alternative(
        self, keyword: str, max_listings: int
    ) -> List[Listing]:
        """
        Strategi alternatif untuk parsing listing.
        Menggunakan pendekatan yang berbeda jika struktur DOM berubah.
        """
        listings = []

        try:
            # Cari semua container yang mungkin berisi listing
            # Facebook sering menggunakan div dengan role="listitem" atau class tertentu
            containers = self.driver.find_elements(
                By.CSS_SELECTOR, '[role="listitem"], [data-testid="marketplace_feed_item"]'
            )

            if not containers:
                # Coba selektor yang lebih umum
                containers = self.driver.find_elements(
                    By.XPATH, '//a[contains(@href, "/marketplace/item/")]/..'
                )

            for container in containers[:max_listings]:
                try:
                    # Cari link
                    links = container.find_elements(
                        By.CSS_SELECTOR, 'a[href*="/marketplace/item/"]'
                    )
                    if not links:
                        continue

                    href = links[0].get_attribute("href") or ""
                    listing_id = self._extract_listing_id(href)

                    listing = self._extract_listing_from_element(
                        container, listing_id, href, keyword
                    )
                    if listing:
                        listings.append(listing)

                except (StaleElementReferenceException, Exception):
                    continue

        except Exception as e:
            logger.debug("Alternative parsing failed: %s", e)

        return listings

    def close(self):
        """Tutup browser dan bersihkan resources."""
        if self.driver is not None:
            try:
                self.driver.quit()
                logger.info("WebDriver closed")
            except Exception as e:
                logger.warning("Error closing WebDriver: %s", e)
            finally:
                self.driver = None
                self._is_logged_in = False

    def restart(self) -> bool:
        """Restart browser session (close dan login ulang)."""
        logger.info("Restarting browser session...")
        self.close()
        self._random_delay(3, 5)
        return self.login()
