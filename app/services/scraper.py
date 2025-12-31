import asyncio
import re
from pathlib import Path
from typing import List, Set, Optional
from datetime import datetime

import pandas as pd
import aiohttp
import aiofiles
from playwright.async_api import async_playwright, Browser, Page, Playwright

class CSEScraper:
    def __init__(self, target_years: Set[str], output_dir: str, headless: bool = True):
        self.target_years = target_years
        self.output_dir = Path(output_dir)
        self.headless = headless
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None

        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def _ensure_browser(self):
        """Initialize Playwright and Browser if not already running."""
        if not self.playwright:
            self.playwright = await async_playwright().start()
        if not self.browser:
            self.browser = await self.playwright.chromium.launch(headless=self.headless)
    
    async def _ensure_page(self):
        """Ensure a page is available."""
        await self._ensure_browser()
        if not self.page or self.page.is_closed():
            self.page = await self.browser.new_page()

    async def _download_pdf(self, url: str, filename: Path):
        """Download a PDF file from a URL."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        async with aiofiles.open(filename, "wb") as f:
                            await f.write(await resp.read())
                        print(f"Downloaded {filename.name}")
                    else:
                        print(f"Failed to download {url} (status {resp.status})")
        except Exception as e:
            print(f"Error downloading {url}: {e}")

    async def _get_company_reports(self, symbol: str):
        """Navigate to company page and download reports."""
        await self._ensure_page()
        
        self.page.set_default_timeout(60000)
        
        url = f"https://www.cse.lk/pages/company-profile/company-profile.component.html?symbol={symbol}"
        print(f"Processing {symbol}...")
        
        try:
            await self.page.goto(url, timeout=90_000, wait_until="domcontentloaded")

            # Navigate to Financials -> Quarterly Reports
            await self.page.get_by_role("link", name="Financials", exact=True).click()
            await self.page.get_by_role("link", name="Quarterly Reports", exact=True).click()
            
            # Try to wait for network idle, but don't fail if it takes too long
            try:
                await self.page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                print("Network didn't idle, proceeding anyway...")

            # Find links with PDF icon
            pdf_links = self.page.locator("a:has(i.fa.fa-file-pdf-o)")
            count = await pdf_links.count()
            print(f"Found {count} PDF link(s) for {symbol}")

            company_dir = self.output_dir / "quartly_reports" / symbol.replace(".", "_")
            company_dir.mkdir(parents=True, exist_ok=True)

            downloads_count = 0
            for i in range(count):
                link = pdf_links.nth(i)
                abs_url = await link.evaluate("(el) => el.href")

                # Filter by year
                row_text = await link.evaluate(
                    "(el) => (el.closest('tr')?.innerText || el.parentElement?.innerText || '')"
                )
                years_in_text = set(re.findall(r"(20\d{2})", row_text))
                
                if self.target_years and years_in_text and years_in_text.isdisjoint(self.target_years):
                    # Skip if row has a year but not in target set
                    continue

                downloads_count += 1
                base_name = abs_url.split("/")[-1].split("?")[0] or "report.pdf"
                if not base_name.lower().endswith(".pdf"):
                    base_name += ".pdf"
                
                out_file = company_dir / f"{symbol}_{downloads_count:02d}_{base_name}"
                await self._download_pdf(abs_url, out_file)

            print(f"Done {symbol}: downloaded {downloads_count} file(s).")

        except Exception as e:
            print(f"Error processing {symbol}: {e}")

    async def scrape_trade_summary(self) -> Optional[Path]:
        """Scrape and download the trade summary CSV."""
        await self._ensure_page()
        url = "https://www.cse.lk/pages/trade-summary/trade-summary.component.html"
        print("Processing Trade Summary...")
        
        trade_summary_dir = self.output_dir / "tradesummary"
        trade_summary_dir.mkdir(parents=True, exist_ok=True)

        try:
            await self.page.goto(url, timeout=60_000, wait_until="domcontentloaded")
            
            # Select "All" rows
            await self.page.locator("select[name='DataTables_Table_0_length']").select_option("-1")

            # Click the Download button
            await self.page.get_by_role("button", name="Download").click()
            
            # Click CSV and handle download
            async with self.page.expect_download() as download_info:
                await self.page.get_by_text("CSV").click()
            
            download = await download_info.value
            
            # Prepend today's date to the filename
            today_str = datetime.now().strftime("%Y-%m-%d")
            new_filename = f"{today_str}_trade_summary.csv"
            
            save_path = trade_summary_dir / new_filename
            await download.save_as(save_path)
            print(f"Downloaded Trade Summary: {save_path}")
            return save_path

        except Exception as e:
            print(f"Error processing Trade Summary: {e}")
            return None

    async def run(self, symbols: List[str] = []):
        try:
            csv_path = await self.scrape_trade_summary()
            
            symbols_to_process = symbols
            
            if csv_path and csv_path.exists() and len(symbols_to_process) == 0:
                try:
                    df = pd.read_csv(csv_path)
                    df.columns = df.columns.str.strip()
                    
                    # Use pandas string methods to find columns case-insensitively
                    symbol_cols = df.columns[df.columns.str.contains("symbol", case=False)]
                    volume_cols = df.columns[df.columns.str.contains("volume", case=False)]
                    
                    symbol_col = symbol_cols[0] if not symbol_cols.empty else None
                    volume_col = volume_cols[0] if not volume_cols.empty else None
                    
                    if symbol_col:
                        # Filter for symbols containing ".N" (Normal shares)
                        df = df[df[symbol_col].astype(str).str.contains('.N', case=False, regex=False)]

                        if volume_col:
                            df[volume_col] = pd.to_numeric(df[volume_col].astype(str).str.replace(',', ''), errors='coerce')
                            df = df.sort_values(by=volume_col, ascending=False)
                            print(f"Sorted symbols by {volume_col} (highest to lowest).")

                        csv_symbols = df[symbol_col].dropna().astype(str).unique().tolist()
                        print(f"Found {len(csv_symbols)} symbols (Normal shares only) in Trade Summary.")
                        symbols_to_process = csv_symbols
                    else:
                        print(f"Could not find 'Symbol' column in CSV. Available columns: {df.columns.tolist()}")
                        
                except Exception as e:
                    print(f"Error reading Trade Summary CSV: {e}")

            print(f"Starting processing for {len(symbols_to_process)} symbols...")
            for symbol in symbols_to_process:
                await self._get_company_reports(symbol)
        finally:
            await self.close()

    async def close(self):
        if self.page:
            await self.page.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

if __name__ == "__main__":
    # Configuration
    TARGET_YEARS = {"2025", "2024"}
    OUTPUT_DIR = "downloads"

    scraper = CSEScraper(target_years=TARGET_YEARS, output_dir=OUTPUT_DIR, headless=True)
    asyncio.run(scraper.run())
