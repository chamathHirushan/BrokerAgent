import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import sys
from pathlib import Path
from langchain_core.messages import HumanMessage, AIMessage

# Add parent directory to sys.path
sys.path.append(str(Path(__file__).parent))

from multi_server import get_agent_executor

# Force UTF-8 encoding for stdout/stderr on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

app = FastAPI()

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Store chat history in memory
chat_history = []

class ChatMessage(BaseModel):
    message: str

@app.get("/", response_class=HTMLResponse)
async def read_root():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.post("/chat")
async def chat(chat_message: ChatMessage):
    user_input = chat_message.message
    
    try:
        # Get the agent executor
        agent_executor = await get_agent_executor()
        
        # Invoke the agent
        result = await agent_executor.ainvoke({
            "input": user_input,
            "chat_history": chat_history
        })
        
        response_text = result["output"]
        
        # Update history
        chat_history.append(HumanMessage(content=user_input))
        chat_history.append(AIMessage(content=response_text))
        
        return JSONResponse(content={"response": response_text})
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(content={"response": f"Error: {str(e)}"}, status_code=500)

@app.post("/reset")
async def reset():
    global chat_history
    chat_history = []
    return {"status": "cleared"}

if __name__ == "__main__":
    print("Starting BrokerAgent Web Client on http://localhost:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)
