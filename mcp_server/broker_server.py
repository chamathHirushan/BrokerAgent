import asyncio
import os
import sys
import re
from pathlib import Path
from typing import List, Set
import pandas as pd

# Force UTF-8 encoding for stdout/stderr on Windows to handle emojis
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# Add parent directory to sys.path to allow importing scraper and analyzer
sys.path.append(str(Path(__file__).parent.parent))

from mcp.server.fastmcp import FastMCP
from scraper import CSEScraper
from analyzer import analyze_pdf

# Initialize FastMCP server
mcp = FastMCP("BrokerAgent")
output_dir: str = "downloads"

@mcp.tool()
async def get_market_trade_summary(symbols: List[str] = []) -> str:
    """
    Retrieves the latest daily trade summary from the Colombo Stock Exchange (CSE).
    
    Use this tool when you need to:
    1. Get current market data like Volume, Price, or Turnover.
    2. Find the top performing companies by volume.
    3. Look up specific trading details for a list of company symbols.
    
    Args:
        symbols: A list of company symbols (e.g. ['JKH', 'SAMP', 'HNB']) to filter the results.
                 If empty, returns the top 50 companies sorted by trading volume.
    """
    print("🚀 Fetching Market Trade Summary...")
    scraper = CSEScraper(target_years=set(), output_dir=output_dir, headless=True)
    
    try:
        csv_path = await scraper.scrape_trade_summary()
        
        if not csv_path or not csv_path.exists():
            return "❌ Failed to download trade summary CSV."
            
        # Read CSV with pandas
        df = pd.read_csv(csv_path)
        
        # Clean up column names
        df.columns = df.columns.str.strip()
        
        # Convert to string/JSON for the agent
        volume_cols = df.columns[df.columns.str.contains("volume", case=False)]
        if not volume_cols.empty:
            vol_col = volume_cols[0]
            # Clean volume column (remove commas)
            df[vol_col] = pd.to_numeric(df[vol_col].astype(str).str.replace(',', ''), errors='coerce')
            df = df.sort_values(by=vol_col, ascending=False)
        
        # Filter by symbols if provided
        if symbols:
            symbol_cols = df.columns[df.columns.str.contains("symbol", case=False)]
            if not symbol_cols.empty:
                sym_col = symbol_cols[0]
                # Create regex pattern for case-insensitive partial match
                pattern = '|'.join([re.escape(s) for s in symbols])
                df = df[df[sym_col].astype(str).str.contains(pattern, case=False, regex=True)]
            
            if df.empty:
                return f"⚠️ No data found for symbols: {', '.join(symbols)}"
            
            return f"✅ Market Trade Summary for requested symbols:\n\n{df.to_markdown(index=False)}"
        
        # Select top 50 rows to keep it reasonable
        top_df = df.head(50)
        
        return f"✅ Market Trade Summary (Top 50 by Volume):\n\n{top_df.to_markdown(index=False)}"
        
    except Exception as e:
        return f"❌ Error processing trade summary: {str(e)}"
    finally:
        await scraper.close()

@mcp.tool()
async def find_company_info(query: str) -> str:
    """
    Finds company details (Symbol, Name, etc.) by searching for a company name or symbol.
    
    Use this tool when:
    1. You have a company name (e.g., "Resus Energy") and need its stock symbol (e.g., "HPWR.N0000").
    2. You have a symbol and need the full company name.
    3. You want to check if a company is listed in the daily trade summary.
    
    Args:
        query: The search string (company name or symbol). Case-insensitive.
    """
    print(f"🚀 Searching for company info: '{query}'...")
    scraper = CSEScraper(target_years=set(), output_dir=output_dir, headless=True)
    
    try:
        csv_path = await scraper.scrape_trade_summary()
        
        if not csv_path or not csv_path.exists():
            return "❌ Failed to download trade summary CSV to perform search."
            
        df = pd.read_csv(csv_path)
        df.columns = df.columns.str.strip()
        
        # Identify relevant columns
        symbol_cols = df.columns[df.columns.str.contains("symbol", case=False)]
        name_cols = df.columns[df.columns.str.contains("company|name", case=False)]
        
        if symbol_cols.empty:
            return "❌ Could not find 'Symbol' column in the trade summary."
            
        sym_col = symbol_cols[0]
        # If we can't find a dedicated name column, we search all columns or just the symbol column
        # But usually there is a 'Company Name' or similar.
        
        # Create a mask for filtering
        mask = pd.Series([False] * len(df))
        
        # Search in Symbol column
        mask |= df[sym_col].astype(str).str.contains(query, case=False, regex=False)
        
        # Search in Name column if it exists
        if not name_cols.empty:
            name_col = name_cols[0]
            mask |= df[name_col].astype(str).str.contains(query, case=False, regex=False)
        
        results = df[mask]
        
        if results.empty:
            return f"⚠️ No companies found matching '{query}'."
            
        top_results = results.head(3)
        return f"✅ Found {len(results)} matches for '{query}':\n\n{top_results.to_markdown(index=False)}"
        
    except Exception as e:
        return f"❌ Error searching for company info: {str(e)}"
    finally:
        await scraper.close()

@mcp.tool()
async def scrape_and_analyze_cse_reports(symbols: List[str] = [], target_years: List[str] = ["2025", "2024"]) -> str:
    """
    Downloads and analyzes detailed financial reports (Quarterly Reports) for specific companies.
    
    Use this tool when you need to:
    1. Perform and save deep fundamental analysis of a company.
    2. Extract financial metrics like Revenue, Profit, Assets, or Liabilities from PDF reports.
    3. Compare financial performance across different years (e.g., 2024 vs 2025).
    
    Args:
        symbols: A list of company symbols (e.g. ['JKH', 'SAMP']) to analyze. 
                 If empty, it will try to analyze reports for ALL companies found in the trade summary (use with caution).
        target_years: List of years to filter reports for (default: ["2025", "2024"]).
    """
    print("🚀 Starting BrokerAgent MCP Task...")

    # 1. Scrape Reports
    print("📥 Step 1: Scraping Reports...")
    scraper = CSEScraper(target_years=set(target_years), output_dir=output_dir, headless=True)
    try:
        await scraper.run(symbols=symbols)
    except Exception as e:
        return f"❌ Scraping failed: {str(e)}"

    # 2. Analyze Reports
    print("🤖 Step 2: Analyzing Reports...")
    downloads_dir = Path(output_dir)
    analysis_dir = Path("analysis_results")
    analysis_dir.mkdir(exist_ok=True)

    # Find all PDFs recursively in the output directory
    pdf_files = list(downloads_dir.rglob("*.pdf"))
    
    if not pdf_files:
        return "⚠️ No PDFs found to analyze after scraping."

    analyzed_count = 0
    for pdf in pdf_files:
        try:
            await analyze_pdf(pdf, analysis_dir)
            analyzed_count += 1
        except Exception as e:
            print(f"❌ Failed to analyze {pdf.name}: {e}")

    return f"✅ Success! Scraped and processed reports. Analyzed {analyzed_count} out of {len(pdf_files)} documents. Results saved in 'analysis_results'."

@mcp.tool()
async def get_financial_analysis_for_symbol(symbol: str, year: str = "2025") -> str:
    """
    Retrieves the analyzed financial data (JSON) for a specific company and year.
    
    Use this tool when:
    1. You need to answer questions about a company's financial performance (e.g. "What was JKH's revenue in 2025?").
    2. You want to read the detailed analysis generated by the 'scrape_and_analyze_cse_reports' tool.
    
    If the analysis files do not exist locally, this tool will AUTOMATICALLY attempt to scrape and analyze the reports 
    for that symbol and year.
    
    Args:
        symbol: The company symbol (e.g. "JKH", "SAMP").
        year: The year to retrieve data for (default: "2025").
    """
    print(f"🚀 Retrieving financial analysis for {symbol} ({year})...")
    analysis_dir = Path("analysis_results")
    
    def get_files():
        if not analysis_dir.exists():
            return []
        # Search for files containing the symbol (case-insensitive) and the year
        return [
            f for f in analysis_dir.glob("*.json") 
            if symbol.lower() in f.name.lower() and year in f.name
        ]

    files = get_files()
    
    if not files:
        print(f"⚠️ No local analysis found for {symbol}. Triggering scrape and analyze...")
        # Call the existing tool to generate the data
        # We pass the symbol and the requested year
        result = await scrape_and_analyze_cse_reports(symbols=[symbol], target_years=[year])
        
        if "❌" in result:
            return f"❌ Could not generate analysis: {result}"
            
        # Try to find the files again after scraping
        files = get_files()
        if not files:
            return f"⚠️ Scraped reports for {symbol}, but no analysis JSON files were generated for {year}. The PDF might not have been readable or found."

    # Read and combine the content of the found JSON files
    output_content = []
    for file_path in files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = f.read()
                output_content.append(f"--- FILE: {file_path.name} ---\n{data}")
        except Exception as e:
            output_content.append(f"❌ Error reading {file_path.name}: {str(e)}")
            
    return f"✅ Found {len(files)} analysis reports for {symbol} ({year}):\n\n" + "\n\n".join(output_content)

if __name__ == "__main__":
    mcp.run(transport="stdio")
