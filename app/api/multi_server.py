import os
import asyncio
import sys
from pathlib import Path

# Force UTF-8 encoding for stdout/stderr on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from dotenv import load_dotenv
from app.core.rag_store import PineconeManager

load_dotenv()

_rag_manager_instance = None

def get_rag_manager():
    global _rag_manager_instance
    if _rag_manager_instance is None:
        _rag_manager_instance = PineconeManager()
    return _rag_manager_instance

@tool
def search_knowledge_base(query: str) -> str:
    """
    Searches the internal knowledge base for relevant information from uploaded documents.
    Use this tool when the user asks about content from files they have uploaded.
    """
    try:
        manager = get_rag_manager()
        docs = manager.similarity_search(query)
        if not docs:
            return "No relevant information found in the knowledge base."
        
        result = "Found the following information from uploaded documents:\n\n"
        for i, doc in enumerate(docs, 1):
            source = doc.metadata.get("source", "Unknown")
            result += f"--- Source: {source} ---\n{doc.page_content}\n\n"
        return result
    except Exception as e:
        return f"Error searching knowledge base: {str(e)}"

# LLM
model = ChatGoogleGenerativeAI(model="gemini-2.5-flash", api_key=os.getenv("GEMINI_API_KEY"))

# MCP servers
# We point to our mcp_server.py
# Ensure we use the same python executable and set PYTHONPATH so imports work
project_root = str(Path(__file__).resolve().parent.parent.parent)
env = os.environ.copy()
env["PYTHONPATH"] = project_root + os.pathsep + env.get("PYTHONPATH", "")

client = MultiServerMCPClient(
    {
        "broker": {
            "command": sys.executable,
            "args": ["app/api/mcp_server.py"],
            "transport": "stdio",
            "env": env,
        },
    }
)

# REQUIRED Tool Calling prompt
prompt = ChatPromptTemplate.from_messages([
    ("system", """You are an expert Investment Advisor and Financial Analyst for the Colombo Stock Exchange (CSE).
    
    Your goal is to provide deep, data-driven investment insights and financial analysis based on the reports and market data you have access to.
    
    When a user asks about a company or market trends:
    1. ALWAYS use your tools to fetch real data (Trade Summaries, Financial Reports, Analysis JSONs).
    2. Analyze the data thoroughly (Revenue growth, Profit margins, PE ratios, Volume trends).
    3. Provide a professional investment opinion or detailed financial breakdown.
    4. Do NOT be afraid to give a recommendation (e.g., "Strong Buy", "Hold", "Watch") if the data supports it, but always qualify it by saying "Based on the current data...".
    5. Do NOT simply say "I cannot provide investment advice". Instead, say "Here is an analysis to help you make an informed decision..." and then provide the analysis.
    
    Be professional, analytical, and helpful."""),
    ("placeholder", "{chat_history}"),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

async def get_agent_executor():
    mcp_tools = await client.get_tools()
    all_tools = mcp_tools + [search_knowledge_base]
    
    # Create the agent
    agent = create_tool_calling_agent(model, all_tools, prompt)
    agent_executor = AgentExecutor(agent=agent, tools=all_tools, verbose=True)
    return agent_executor

async def run_multi_server_agent():
    agent_executor = await get_agent_executor()

    # Test query
    query = "Scrape and analyze CSE reports for the year 2025"
    print(f"\n[Query]: {query}")
    result = await agent_executor.ainvoke({"input": query})
    print(result["output"])

if __name__ == "__main__":
    asyncio.run(run_multi_server_agent())
