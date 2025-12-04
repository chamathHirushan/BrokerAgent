# BrokerAgent

## Project Structure

- **`app/api/`**: API servers (FastAPI, MCP).
- **`app/core/`**: Database & RAG.
- **`app/services/`**: Scraper & Analyzer.
- **`data/`**: Storage.

## Setup

1. **Install Dependencies:**

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   playwright install chromium
   ```

2. **Configuration:**

   Create a `.env` file:

   ```env
   GEMINI_API_KEY=...
   PINECONE_API_KEY=...
   ```

3. **Run:**

   ```powershell
   python -m uvicorn app.api.server:app --reload --host 127.0.0.1 --port 8000
   ```
