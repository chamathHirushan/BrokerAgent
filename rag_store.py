import os
from typing import List
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_pinecone import PineconeVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from pinecone import Pinecone, ServerlessSpec
import time

class PineconeManager:
    def __init__(self):
        self.api_key = os.getenv("PINECONE_API_KEY")
        self.index_name = os.getenv("PINECONE_INDEX_NAME", "agentbroker")
        
        # --- LOCAL HUGGING FACE EMBEDDINGS ---
        print("🧠 Loading Local Embedding Model (all-mpnet-base-v2)...")
        self.embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-mpnet-base-v2")
        
        if not self.api_key:
            print("⚠️ PINECONE_API_KEY not found in environment variables.")
            return

        self.pc = Pinecone(api_key=self.api_key)
        
        # Create index if it doesn't exist
        existing_indexes = [index.name for index in self.pc.list_indexes()]
        if self.index_name not in existing_indexes:
            print(f"Creating Pinecone index: {self.index_name}")
            self.pc.create_index(
                name=self.index_name,
                dimension=768, # Dimension for all-mpnet-base-v2
                metric="cosine",
                spec=ServerlessSpec(cloud="aws", region="us-east-1")
            )
            # Wait for index to be ready
            while not self.pc.describe_index(self.index_name).status['ready']:
                time.sleep(1)
        else:
            # Verify dimension compatibility
            index_info = self.pc.describe_index(self.index_name)
            if int(index_info.dimension) != 768:
                print(f"⚠️ CRITICAL WARNING: Index '{self.index_name}' has {index_info.dimension} dimensions. Model uses 768. Uploads WILL fail.")

        self.vector_store = PineconeVectorStore(
            index_name=self.index_name,
            embedding=self.embeddings
        )

    def add_documents(self, documents: List[Document]):
        """Chunk and add documents to Pinecone with robust rate limiting."""
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200
        )
        splits = text_splitter.split_documents(documents)
        
        batch_size = 1
        total_splits = len(splits)
        
        print(f"Processing {total_splits} chunks...")
        
        for i in range(0, total_splits, batch_size):
            batch = splits[i:i + batch_size]
            retries = 0
            max_retries = 3
            
            while retries < max_retries:
                try:
                    self.vector_store.add_documents(batch)
                    print(f"Added chunk {i + 1}/{total_splits}")
                    break 
                except Exception as e:
                    if "429" in str(e):
                        retries += 1
                        wait_time = 10
                        print(f"⚠️ Rate limit hit (429). Retry {retries}/{max_retries} in {wait_time}s...")
                        time.sleep(wait_time)
                    else:
                        print(f"❌ Error adding batch: {e}")
                        raise e
            
            if retries == max_retries:
                raise Exception("Failed to upload batch after multiple retries due to rate limits.")
                    
        print(f"✅ Added {len(splits)} chunks to Pinecone.")

    def similarity_search(self, query: str, k: int = 4) -> List[Document]:
        """Search for similar documents."""
        return self.vector_store.similarity_search(query, k=k)

    def clear_index(self):
        """Clears all vectors from the index."""
        try:
            index = self.pc.Index(self.index_name)
            index.delete(delete_all=True)
            print(f"✅ Index '{self.index_name}' cleared successfully.")
        except Exception as e:
            print(f"❌ Error clearing index: {e}")

    def delete_file(self, filename: str):
        """Deletes all vectors associated with a specific file."""
        try:
            index = self.pc.Index(self.index_name)
            index.delete(filter={"source": filename})
            print(f"✅ Deleted vectors for file: {filename}")
        except Exception as e:
            print(f"❌ Error deleting file '{filename}': {e}")

