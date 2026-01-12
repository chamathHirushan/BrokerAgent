import asyncio
import os
import sys
import re
from pathlib import Path
from typing import List, Set, Optional, Dict, Any
import pandas as pd
from cse_lk import CSEClient, CSEAPIError, CSERateLimitError

# Force UTF-8 encoding for stdout/stderr on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    
from app.core.db_manager import db_manager
import json

from mcp.server.fastmcp import FastMCP
from app.services.scraper import CSEScraper
from app.services.analyzer import analyze_pdf

# Initialize FastMCP server
mcp = FastMCP("BrokerAgent")
output_dir: str = "downloads"

# Initialize global CSE Client
cse_client = CSEClient()

@mcp.tool()
async def get_market_overview() -> str:
    """
    Get a comprehensive snapshot of the market relative to 'Today'.
    Includes market status (Open/Closed), summaries, indices (ASPI, S&P SL20), and top movers.
    """
    try:
        overview = cse_client.get_market_overview()
        
        # Format for LLM
        output = "Market Overview:\n"
        output += f"Status: {overview.get('status', {}).get('marketStatus', 'Unknown')}\n"
        
        aspi = overview.get('aspi', {})
        output += f"ASPI: {aspi.get('value')} ({aspi.get('change')} / {aspi.get('changePercentage')}%)\n"
        
        snp = overview.get('snp_sl20', {})
        output += f"S&P SL20: {snp.get('value')} ({snp.get('change')} / {snp.get('changePercentage')}%)\n"
        
        output += f"\nTop Gainers (Top 5):\n"
        for g in overview.get('top_gainers', []):
            output += f"- {g.symbol}: {g.price} (+{g.changePercentage}%)\n"
            
        return output
    except Exception as e:
        return f"Error fetching market overview: {str(e)}"

@mcp.tool()
async def get_company_profile(symbol: str) -> str:
    """
    Get detailed current information for a specific company using the official API.
    Args:
        symbol: Stock symbol (e.g., 'JKH.N0000').
    """
    try:
        # Resolve symbol if needed
        full_symbol = await resolve_symbol(symbol)
        
        info = cse_client.get_company_info(full_symbol)
        
        return (
            f"Company Profile for {full_symbol}:\n"
            f"Name: {info.name}\n"
            f"Last Traded Price: {info.last_traded_price}\n"
            f"Change: {info.change} ({info.change_percentage}%)\n"
            f"Market Cap: {info.market_cap}\n"
        )
    except Exception as e:
        return f"Error fetching profile for {symbol}: {str(e)}"

@mcp.tool()
async def get_intraday_data(symbol: str) -> str:
    """
    Get today's intraday price movement for a stock.
    Args:
        symbol: Stock symbol (e.g., 'JKH.N0000').
    """
    try:
        # Resolve symbol if needed
        full_symbol = await resolve_symbol(symbol)
        
        # Using the workaround identified for chart data
        data = {"symbol": full_symbol, "chartId": "1", "period": "1"}
        chart_data = cse_client._make_request("chartData", data)
        
        if isinstance(chart_data, list):
            # If data is too long, sample it
            if len(chart_data) > 20:
                summary_data = chart_data[::len(chart_data)//20] # Take every ~nth element to get ~20 points
            else:
                summary_data = chart_data
                
            return f"Intraday Chart Data for {full_symbol} (Sampled):\n{json.dumps(summary_data, indent=2)}"
        
        return f"Raw Data: {json.dumps(chart_data)[:500]}..."
        
    except Exception as e:
        return f"Error fetching chart data for {symbol}: {str(e)}"

@mcp.tool()
async def get_latest_announcements() -> str:
    """
    Get the latest financial announcements from the CSE.
    """
    try:
        announcements = cse_client.get_financial_announcements()
        
        if not announcements:
            return "No recent financial announcements found."
            
        output = "Latest Financial Announcements (Top 10):\n"
        for idx, ann in enumerate(announcements[:10], 1):
            output += f"{idx}. {ann.company_name} ({ann.symbol}): {ann.announcement_title} [{ann.date}]\n"
            
        return output
    except Exception as e:
        return f"Error fetching announcements: {str(e)}"
    
async def _get_trade_summary_df() -> Optional[pd.DataFrame]:
    """Helper to scrape and load the trade summary CSV."""
    scraper = CSEScraper(target_years=set(), output_dir=output_dir, headless=True)
    try:
        csv_path = await scraper.scrape_trade_summary()
        if not csv_path or not csv_path.exists():
            return None
        df = pd.read_csv(csv_path)
        df.columns = df.columns.str.strip()
        return df
    except Exception as e:
        print(f"Error getting trade summary: {e}")
        return None
    finally:
        await scraper.close()

@mcp.tool()
async def resolve_symbol(symbol: str) -> str:
    """
    Resolves a symbol to its full format (e.g., 'JKH' -> 'JKH.N0000') using the trade summary.
    """
    symbol = symbol.strip().upper()
    print(f"Resolving symbol: {symbol}...")
    
    df = await _get_trade_summary_df()
    if df is None:
        print("Could not load CSV for symbol resolution.")
        return symbol
        
    symbol_cols = df.columns[df.columns.str.contains("symbol", case=False)]
    if symbol_cols.empty:
        return symbol
    sym_col = symbol_cols[0]
    
    # 1. Check for exact match
    if symbol in df[sym_col].values:
        return symbol
        
    # 2. Check for "starts with" match (e.g. JKH -> JKH.N0000)
    mask = df[sym_col].astype(str).str.startswith(symbol + ".")
    matches = df[mask]
    if not matches.empty:
        found = matches.iloc[0][sym_col]
        print(f"Resolved {symbol} -> {found}")
        return found
        
    # 3. Check for general containment (fuzzy)
    mask = df[sym_col].astype(str).str.contains(symbol, case=False)
    matches = df[mask]
    if not matches.empty:
        found = matches.iloc[0][sym_col]
        print(f"Resolved {symbol} -> {found} (fuzzy match)")
        return found
        
    print(f"Could not resolve {symbol} in CSV. Using as is.")
    return symbol

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
    
    try:
        df = await _get_trade_summary_df()
        
        if df is None:
            return "Error: Failed to download trade summary CSV."
            
        # Convert to string/JSON for the agent
        volume_cols = df.columns[df.columns.str.contains("volume", case=False)]
        if not volume_cols.empty:
            vol_col = volume_cols[0]
            # Clean volume column (remove commas)
            df[vol_col] = pd.to_numeric(df[vol_col].astype(str).str.replace(',', ''), errors='coerce')
            df = df.sort_values(by=vol_col, ascending=False)
        
        # Filter by symbols if provided
        if symbols:
            # We do NOT resolve symbols here because we want to support partial matching (e.g. "JKH" finding "JKH.N0000")
            # The regex logic below handles it.
            
            symbol_cols = df.columns[df.columns.str.contains("symbol", case=False)]
            if not symbol_cols.empty:
                sym_col = symbol_cols[0]
                # Create regex pattern for case-insensitive partial match
                pattern = '|'.join([re.escape(s) for s in symbols])
                df = df[df[sym_col].astype(str).str.contains(pattern, case=False, regex=True)]
            
            if df.empty:
                return f"Warning: No data found for symbols: {', '.join(symbols)}"
            
            return f"Market Trade Summary for requested symbols:\n\n{df.to_markdown(index=False)}"
        
        # Select top 50 rows to keep it reasonable
        top_df = df.head(50)
        
        return f"Market Trade Summary (Top 50 by Volume):\n\n{top_df.to_markdown(index=False)}"
        
    except Exception as e:
        return f"Error processing trade summary: {str(e)}"

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
    
    try:
        df = await _get_trade_summary_df()
        
        if df is None:
            return "Error: Failed to download trade summary CSV to perform search."
            
        # Identify relevant columns
        symbol_cols = df.columns[df.columns.str.contains("symbol", case=False)]
        name_cols = df.columns[df.columns.str.contains("company|name", case=False)]
        
        if symbol_cols.empty:
            return "Error: Could not find 'Symbol' column in the trade summary."
            
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
            return f"Warning: No companies found matching '{query}'."
            
        top_results = results.head(3)
        return f"Found {len(results)} matches for '{query}':\n\n{top_results.to_markdown(index=False)}"
        
    except Exception as e:
        return f"Error searching for company info: {str(e)}"

@mcp.tool()
async def scrape_and_analyze_cse_reports(symbols: List[str] = [], target_years: List[str] = ["2025", "2024"]) -> str:
    """
    Downloads and analyzes detailed financial reports (Quarterly Reports) for specific companies.
    
    Use this tool when you need to:
    1. Perform and save deep fundamental analysis of a company.
    2. Extract financial metrics like Revenue, Profit, Assets, or Liabilities from PDF reports.
    3. Compare financial performance across different years (e.g., 2024 vs 2025).
    
    Args:
        symbols: A list of company symbols (e.g. ['JKH.N0000', 'SAMP.N0000']) to analyze. 
                 The symbols should ideally be in the full CSE format (e.g. 'JKH.N0000'). 
                 If a partial symbol (e.g. 'JKH') is provided, the tool will attempt to resolve it using the latest market data.
                 If empty, it will try to analyze reports for ALL companies found in the trade summary (use with caution).
        target_years: List of years to filter reports for (default: ["2025", "2024"]).
    """
    print("🚀 Starting BrokerAgent MCP Task...")

    # 1. Scrape Reports
    print("📥 Step 1: Scraping Reports...")
    
    # Resolve symbols to full format (e.g. JKH -> JKH.N0000)
    if symbols:
        resolved_symbols = []
        for s in symbols:
            resolved_symbols.append(await resolve_symbol(s))
        symbols = resolved_symbols
        
    scraper = CSEScraper(target_years=set(target_years), output_dir=output_dir, headless=True)
    try:
        await scraper.run(symbols=symbols)
    except Exception as e:
        return f"Error: Scraping failed: {str(e)}"

    # 2. Analyze Reports
    print("🤖 Step 2: Analyzing Reports...")
    downloads_dir = Path(output_dir)
    analysis_dir = Path("analysis_results")
    analysis_dir.mkdir(exist_ok=True)

    # Find all PDFs recursively in the output directory
    pdf_files = list(downloads_dir.rglob("*.pdf"))
    
    if not pdf_files:
        return "Warning: No PDFs found to analyze after scraping."

    analyzed_count = 0
    for pdf in pdf_files:
        try:
            await analyze_pdf(pdf, analysis_dir)
            analyzed_count += 1
        except Exception as e:
            print(f"Failed to analyze {pdf.name}: {e}")

    return f"Success! Scraped and processed reports. Analyzed {analyzed_count} out of {len(pdf_files)} documents. Results saved in 'analysis_results'."

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
        symbol: The company symbol (e.g. "JKH.N0000"). If a partial symbol is provided (e.g. "JKH"), 
                it will be resolved using the latest market data.
        year: The year to retrieve data for (default: "2025").
    """
    # Resolve symbol
    symbol = await resolve_symbol(symbol)
    print(f"🚀 Retrieving financial analysis for {symbol} ({year})...")
    
    # 1. Try Database First
    try:
        reports = db_manager.get_reports(symbol, year)
        
        if reports:
            print(f"Found {len(reports)} reports in database for {symbol} ({year}).")
            output_content = []
            for report in reports:
                output_content.append(f"--- FILE: {report['file_name']} (From DB) ---\n{json.dumps(report['content'], indent=2)}")
            return f"Found {len(reports)} analysis reports for {symbol} ({year}) in database:\n\n" + "\n\n".join(output_content)
            
    except Exception as e:
        print(f"Database lookup failed: {e}. Falling back to file system.")

    # 2. Fallback to File System
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
        print(f"No local analysis found for {symbol}. Triggering scrape and analyze...")
        # Call the existing tool to generate the data
        # We pass the symbol and the requested year
        result = await scrape_and_analyze_cse_reports(symbols=[symbol], target_years=[year])
        
        if "Error" in result or "Failed" in result:
            return f"Error: Could not generate analysis: {result}"
            
        # Try to find the files again after scraping
        # Note: The analyzer now saves to DB, so we could check DB again, 
        # but for simplicity we check files as the analyzer also saves files.
        files = get_files()
        if not files:
            return f"Warning: Scraped reports for {symbol}, but no analysis JSON files were generated for {year}. The PDF might not have been readable or found."

    # Read and combine the content of the found JSON files
    output_content = []
    for file_path in files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = f.read()
                output_content.append(f"--- FILE: {file_path.name} ---\n{data}")
        except Exception as e:
            output_content.append(f"Error reading {file_path.name}: {str(e)}")
            
    return f"Found {len(files)} analysis reports for {symbol} ({year}):\n\n" + "\n\n".join(output_content)

if __name__ == "__main__":
    mcp.run(transport="stdio")
