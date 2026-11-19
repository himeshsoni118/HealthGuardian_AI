import re
import time
from datetime import datetime
from playwright.sync_api import sync_playwright
from database import get_db_connection, init_db


class LabPriceScraper:
    def __init__(self, city="Jaipur"):
        self.city = city.lower()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        self.labs = {
            "Dr B Lal Clinical Laboratory": f"https://blallab.com/{self.city}/lab-test",
            "Dr Lal PathLabs": f"https://www.lalpathlabs.com/book-a-test/{self.city}",
            "Redcliffe Labs": f"https://redcliffelabs.com/{self.city}/tests",
        }

    def scrape_all(self):
        init_db()
        print(f"🚀 Scraping ALL tests for {self.city.title()}...")
        all_data = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=self.headers["User-Agent"])

            for lab_name, url in self.labs.items():
                print(f"📋 Scraping {lab_name}...")
                page = context.new_page()
                try:
                    page.goto(url, timeout=30000, wait_until="domcontentloaded")
                    time.sleep(3)

                    # Scroll to load everything
                    for _ in range(30):
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        time.sleep(1.5)

                    body_text = page.locator("body").inner_text()

                    # Improved regex for test + price
                    matches = re.finditer(
                        r"([A-Z][A-Za-z0-9\s\(\)/\.,-]{15,150}?)\s*"
                        r"(?:₹|Rs\.?)\s*(\d{1,3}(?:,\d{3})*)",
                        body_text,
                        re.IGNORECASE,
                    )

                    seen = set()
                    count = 0
                    for m in matches:
                        # Take only the first line to strip embedded UI text
                        raw_name = m.group(1).strip().split('\n')[0].strip().upper()
                        test_name = re.sub(r'\s+', ' ', raw_name)  # collapse whitespace
                        price_str = m.group(2).replace(",", "")
                        try:
                            price = int(price_str)
                        except:
                            continue
                        if (
                            price < 100
                            or price > 50000
                            or test_name in seen
                        ):
                            continue

                        has_offer = any(
                            k in body_text.lower()
                            for k in ["off", "discount", "%", "new10"]
                        )
                        offer_text = "Offer detected" if has_offer else None

                        all_data.append(
                            (
                                lab_name,
                                self.city.title(),
                                test_name,
                                price,
                                has_offer,
                                offer_text,
                            )
                        )
                        seen.add(test_name)
                        count += 1

                    print(f"   ✅ {count} tests saved from {lab_name}")

                except Exception as e:
                    print(f"   ❌ {lab_name} failed: {str(e)[:80]}")
                finally:
                    page.close()
                    time.sleep(3)

            browser.close()

        # Save to DB
        conn = get_db_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        for row in all_data:
            cursor.execute(
                """
                INSERT OR REPLACE INTO lab_prices 
                (lab_name, city, test_name, price_inr, has_offer, offer_text, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (*row, now),
            )
        conn.commit()
        conn.close()
        print(f"✅ Total {len(all_data)} tests stored in lab_prices.db")
