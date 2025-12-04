import os
import asyncio
import json
import re
from pathlib import Path
from typing import List, Dict, Optional
import google.generativeai as genai
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from app.core.db_manager import db_manager

# Load environment variables
load_dotenv()

# Configure Gemini API
GENAI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GENAI_API_KEY:
    print("⚠️ GEMINI_API_KEY not found in environment variables. Please set it in a .env file.")

if GENAI_API_KEY:
    genai.configure(api_key=GENAI_API_KEY)

# --- Pydantic Models ---

class CompanyInfo(BaseModel):
    name: str
    ticker_symbol: str
    report_period: str
    report_end_date: str = Field(..., description="The end date of the reporting period strictly in YYYY-MM-DD format (e.g., 2025-09-30). Do not include any other text.")
    report_type: str
    currency: str
    audit_status: str

class SharePricePerformance(BaseModel):
    period_label: str = Field(..., description="Label for the period, e.g., 'quarter_ended_30_jun_2025'")
    closing_price: float
    highest_price: float
    lowest_price: float
    price_earnings_ratio_annualized: float
    source_note: str

class ValuationMetrics(BaseModel):
    net_assets_per_share_group: float
    price_to_book_status: str
    price_to_book_ratio: float
    float_adjusted_market_capitalization: float
    public_shareholding_percentage: float
    number_of_public_shareholders: int
    compliance_level: str

class MarketData(BaseModel):
    share_price_performance: SharePricePerformance
    valuation_metrics: ValuationMetrics

class FinancialMetric(BaseModel):
    current: float
    previous: float
    change_percentage: float
    signal: str

class Profitability(BaseModel):
    revenue: FinancialMetric
    gross_profit: FinancialMetric
    profit_before_tax: FinancialMetric
    profit_for_period: FinancialMetric

class EPS(BaseModel):
    basic_eps_current: float
    basic_eps_previous: float
    change_percentage: float
    signal: str

class CostOfSales(BaseModel):
    current: float
    change_percentage: float
    note: str

class FinanceCosts(BaseModel):
    current: float
    previous: float
    change_percentage: float
    signal: str

class ExpensesAndEfficiency(BaseModel):
    cost_of_sales: CostOfSales
    finance_costs: FinanceCosts

class FinancialPerformance(BaseModel):
    period_label: str = Field(..., description="Label for the period, e.g., 'group_3_months_ended_...'")
    profitability: Profitability
    earnings_per_share_eps: EPS
    expenses_and_efficiency: ExpensesAndEfficiency

class BalanceSheetAssets(BaseModel):
    total_assets: float
    previous_audited_value: float = Field(..., description="Value at previous audited date")
    signal: str

class BalanceSheetLiabilities(BaseModel):
    total_liabilities: float
    interest_bearing_loans_non_current: float
    short_term_loans_overdrafts: float
    signal: str

class BalanceSheetEquity(BaseModel):
    total_equity: float
    retained_earnings: float
    signal: str

class BalanceSheetStability(BaseModel):
    as_at_date_label: str = Field(..., description="Label for the date, e.g., 'as_at_30_jun_2025'")
    assets: BalanceSheetAssets
    liabilities: BalanceSheetLiabilities
    equity: BalanceSheetEquity

class CashFlowActivity(BaseModel):
    net_cash_flow: float
    status: str
    major_outflows_or_flows: str

class CashFlowAnalysis(BaseModel):
    period_label: str = Field(..., description="Label for the period")
    operating_activities: CashFlowActivity
    investing_activities: CashFlowActivity
    financing_activities: CashFlowActivity
    cash_position_end_of_period: float
    signal: str

class SegmentData(BaseModel):
    name: str = Field(..., description="Name of the segment")
    revenue: float
    profit_before_tax: float
    status: str

class InvestmentDecisionFactors(BaseModel):
    buy_signals: List[str]
    sell_hold_risks: List[str]

class FinancialReportAnalysis(BaseModel):
    company_info: CompanyInfo
    market_data: MarketData
    financial_performance: FinancialPerformance
    balance_sheet_stability: BalanceSheetStability
    cash_flow_analysis: CashFlowAnalysis
    segment_performance: List[SegmentData]
    investment_decision_factors: InvestmentDecisionFactors

# --- Analysis Logic ---

async def analyze_pdf(pdf_path: Path, output_dir: Path):
    print(f"🤖 Analyzing {pdf_path.name}...")
    
    if not GENAI_API_KEY:
        print("❌ Skipping analysis: GEMINI_API_KEY not set.")
        return

    # Upload file to Gemini
    try:
        sample_file = genai.upload_file(path=pdf_path, display_name=pdf_path.name)
        print(f"   File uploaded: {sample_file.display_name}")
    except Exception as e:
        print(f"❌ Error uploading file: {e}")
        return

    # Create the prompt
    prompt = """
    You are an expert financial analyst and data extraction specialist. Your task is to analyze the provided financial report (Interim or Quarterly Financial Statement) and convert the key data points into a structured JSON format.

    Instructions:
    1. Analyze the Document: Read through the Income Statement, Balance Sheet, Cash Flow Statement, and Notes.
    2. Extract Data: Populate the fields in the JSON structure.
    3. Generate Signals: For fields labeled "signal" or "status", interpret the data (e.g., "Strong Top-line Growth", "Negative - Profitability Compressed").
    4. Citations: Cite the source page number for every extracted fact inside the string value where possible.
    5. Consolidate Investment Factors: Populate the investment_decision_factors block.
    """

    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash", 
        system_instruction="You are a helpful financial analyst assistant."
    )

    try:
        result = model.generate_content(
            [sample_file, prompt],
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                response_schema=FinancialReportAnalysis
            )
        )
        
        # Parse and save
        analysis_data = json.loads(result.text)
    
        try:
            symbol = pdf_path.name.split('_')[0]
            
            company_info = analysis_data.get("company_info", {})
            date_formatted = company_info.get("report_end_date", "UNKNOWN_DATE")
            
            filename_base = f"{symbol}_{date_formatted}"
            filename_base = re.sub(r'[<>:"/\\|?*]', '_', filename_base)
            filename = f"{filename_base}_analysis.json"
            
        except Exception as e:
            print(f"⚠️ Could not generate dynamic filename: {e}")
            filename = f"{pdf_path.stem}_analysis.json"

        # Save to JSON
        output_file = output_dir / filename
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(analysis_data, f, indent=2)
            
        print(f"✅ Analysis saved to {output_file}")

        try:
            # Use the same symbol and date we used for the filename
            # This ensures consistency and avoids "UNKNOWN" values
            db_symbol = symbol
            db_date = date_formatted
            
            if db_symbol == "UNKNOWN" or not db_symbol:
                 # Fallback: try to get from filename if the variable is somehow empty
                 parts = filename.split('_')
                 if len(parts) > 0:
                    db_symbol = parts[0].split('.')[0]

            db_manager.save_report(
                symbol=db_symbol,
                report_date=db_date,
                file_name=filename,
                content=analysis_data
            )
            
        except Exception as e:
            print(f"⚠️ Failed to save to database: {e}")

    except Exception as e:
        print(f"❌ Error during analysis: {e}")
    
    finally:
        # Cleanup
        try:
            sample_file.delete()
        except:
            pass

async def main():
    downloads_dir = Path("downloads")
    analysis_dir = Path("analysis_results")
    analysis_dir.mkdir(exist_ok=True)

    # Find all PDFs recursively
    pdf_files = list(downloads_dir.rglob("*.pdf"))
    
    print(f"Found {len(pdf_files)} PDFs to analyze.")
    
    for pdf in pdf_files:
        await analyze_pdf(pdf, analysis_dir)

if __name__ == "__main__":
    asyncio.run(main())
