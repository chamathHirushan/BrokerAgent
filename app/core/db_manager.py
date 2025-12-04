import sqlite3
import json
import os
from pathlib import Path
from typing import Optional, Dict, Any, List

class DatabaseManager:
    def __init__(self, db_path: str = "data/broker_agent.db"):
        self.db_path = db_path
        self._ensure_db_dir()
        self._init_db()

    def _ensure_db_dir(self):
        """Ensure the directory for the database exists."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        """Initialize the database schema."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Table for storing analyzed financial reports
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS financial_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                year TEXT NOT NULL,
                quarter TEXT,
                file_name TEXT UNIQUE NOT NULL,
                content JSON NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()

    def save_report(self, symbol: str, year: str, file_name: str, content: Dict[str, Any], quarter: Optional[str] = None):
        """Save or update a financial report analysis."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO financial_reports (symbol, year, quarter, file_name, content)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(file_name) DO UPDATE SET
                    content = excluded.content,
                    created_at = CURRENT_TIMESTAMP
            ''', (symbol.upper(), year, quarter, file_name, json.dumps(content)))
            conn.commit()
            print(f"💾 Saved analysis for {file_name} to database.")
        except Exception as e:
            print(f"❌ Error saving to DB: {e}")
        finally:
            conn.close()

    def get_reports(self, symbol: str, year: str) -> List[Dict[str, Any]]:
        """Retrieve reports for a specific symbol and year."""
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM financial_reports 
            WHERE symbol = ? AND year = ?
            ORDER BY created_at DESC
        ''', (symbol.upper(), year))
        
        rows = cursor.fetchall()
        conn.close()
        
        results = []
        for row in rows:
            results.append({
                "file_name": row["file_name"],
                "content": json.loads(row["content"]),
                "created_at": row["created_at"]
            })
        return results

# Global instance
# Use environment variable for DB path if available (for Docker)
db_path = os.getenv("DB_PATH", "data/broker_agent.db")
db_manager = DatabaseManager(db_path)
