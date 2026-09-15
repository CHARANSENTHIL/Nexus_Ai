"""Document Q&A tools for Nexus AI agent ecosystem."""
import asyncio
import concurrent.futures
import logging
from typing import Dict, Any, Optional
from langchain_core.tools import tool

from app.agents.document_qa_agent import document_qa_agent

logger = logging.getLogger(__name__)


@tool
def analyze_document(file_path: str, prompt: Optional[str] = None) -> Dict[str, Any]:
    """
    Ingests and summarizes a PDF or text document, extracting key takeaways, metrics, and structured insights.
    """
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, document_qa_agent.ingest_document(file_path, prompt=prompt)).result()
        else:
            return asyncio.run(document_qa_agent.ingest_document(file_path, prompt=prompt))
    except Exception as e:
        logger.error(f"[DocumentTools] analyze_document failed: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


@tool
def query_document(question: str, file_path: Optional[str] = None, doc_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Queries ingested documents using semantic vector embeddings and local Ollama LLM reasoning.
    """
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, document_qa_agent.query_document(question=question, file_path=file_path, doc_id=doc_id)).result()
        else:
            return asyncio.run(document_qa_agent.query_document(question=question, file_path=file_path, doc_id=doc_id))
    except Exception as e:
        logger.error(f"[DocumentTools] query_document failed: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
