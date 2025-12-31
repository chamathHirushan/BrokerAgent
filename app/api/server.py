import uvicorn
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from contextlib import asynccontextmanager
import sys
import io
from pypdf import PdfReader
from pathlib import Path
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.documents import Document

from app.api.multi_server import get_agent_executor, get_rag_manager

# Force UTF-8 encoding for stdout/stderr on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

rag_manager = None
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global rag_manager
    # Initialize the shared instance via multi_server's getter
    rag_manager = get_rag_manager()
    yield
    # Shutdown
    print("Server shutting down. Clearing knowledge base...")
    if rag_manager:
        rag_manager.clear_index()

app = FastAPI(lifespan=lifespan)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Store chat history in memory
chat_history = []

class ChatMessage(BaseModel):
    message: str

class FileDeleteRequest(BaseModel):
    filename: str

@app.post("/delete_file")
async def delete_file(request: FileDeleteRequest):
    try:
        rag_manager.delete_file(request.filename)
        return JSONResponse(content={"message": f"Successfully deleted {request.filename} from knowledge base."})
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    try:
        # Read file content into memory
        content = await file.read()
        
        documents = []
        if file.filename.lower().endswith(".pdf"):
            # Process PDF from memory
            pdf_file = io.BytesIO(content)
            reader = PdfReader(pdf_file)
            for i, page in enumerate(reader.pages):
                text = page.extract_text()
                if text:
                    documents.append(Document(page_content=text, metadata={"source": file.filename, "page": i}))
                    
        elif file.filename.lower().endswith(".txt"):
            # Process Text from memory
            text = content.decode("utf-8")
            documents = [Document(page_content=text, metadata={"source": file.filename})]
        else:
            return JSONResponse(content={"error": "Unsupported file type. Please upload PDF or TXT."}, status_code=400)
            
        # Add to Pinecone
        rag_manager.add_documents(documents)
        
        return JSONResponse(content={"message": f"Successfully processed {file.filename} and added to knowledge base."})
        
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)

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
