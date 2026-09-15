"""
Deep Document & PDF Q&A Agent for Nexus AI — Indexes PDF documents and answers complex questions using ChromaDB + Ollama.
"""
import asyncio
import logging
import os
import re
from typing import Any, Dict, List, Optional
import httpx
from pypdf import PdfReader

from app.config import settings
from app.memory.chroma_store import memory_store

logger = logging.getLogger(__name__)


class DocumentQAAgent:
    """Agent that ingests, indexes, and performs semantic Q&A over PDF and text documents."""

    def __init__(self):
        self.ollama_url = settings.get_ollama_url()
        self.model = getattr(settings, "OLLAMA_COMPLEX_MODEL", "qwen3:4b")

    def extract_text_from_pdf(self, pdf_path: str) -> List[Dict[str, Any]]:
        """Extracts text page by page from a PDF document."""
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        pages_data = []
        reader = PdfReader(pdf_path)
        for idx, page in enumerate(reader.pages, 1):
            text = (page.extract_text() or "").strip()
            if text:
                pages_data.append({
                    "page_number": idx,
                    "text": text,
                    "word_count": len(text.split()),
                })
        return pages_data

    def index_document(self, filepath: str, user_id: str = "default") -> int:
        """Extracts text and indexes chunks into ChromaDB."""
        fname = os.path.basename(filepath)
        pages = self.extract_text_from_pdf(filepath)
        indexed_count = 0

        for p in pages:
            page_text = p["text"]
            # Chunk long pages into ~600-word blocks
            words = page_text.split()
            chunk_size = 500
            for i in range(0, max(len(words), 1), chunk_size):
                chunk_str = " ".join(words[i:i + chunk_size])
                if len(chunk_str.strip()) < 20:
                    continue
                doc_text = f"Document: {fname} (Page {p['page_number']})\n{chunk_str}"
                memory_store.store(
                    document=doc_text,
                    metadata={
                        "filename": fname,
                        "filepath": filepath,
                        "page_number": p["page_number"],
                        "user_id": user_id,
                        "type": "document_chunk",
                    },
                    user_id=user_id,
                )
                indexed_count += 1

        logger.info(f"[DocumentQA] Indexed {indexed_count} chunks from {fname} into ChromaDB")
        return indexed_count

    async def analyze_document(self, filepath: str, user_id: str = "default") -> Dict[str, Any]:
        """Generates an executive summary and key insights of a PDF document."""
        fname = os.path.basename(filepath)
        pages = self.extract_text_from_pdf(filepath)
        total_pages = len(pages)
        total_words = sum(p["word_count"] for p in pages)

        # Index in background
        self.index_document(filepath, user_id)

        # Prepare summary prompt with first 3 pages and last page
        sample_text = "\n\n".join([f"--- Page {p['page_number']} ---\n{p['text'][:800]}" for p in pages[:4]])
        system_instruction = (
            "You are an expert Document Intelligence Analyst. Read the document excerpt and produce a concise executive briefing.\n"
            "Format:\n"
            "1. 📌 Overview (2 sentences)\n"
            "2. 🔑 3-4 Key Findings / Takeaways\n"
            "3. 💡 Strategic Value / Conclusions"
        )

        summary = ""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self.ollama_url}/api/generate",
                    json={
                        "model": self.model,
                        "system": system_instruction,
                        "prompt": f"Analyze this document '{fname}':\n\n{sample_text}",
                        "stream": False,
                    },
                )
                if resp.status_code == 200:
                    summary = resp.json().get("response", "").strip()
        except Exception as e:
            logger.warning(f"[DocumentQA] LLM summary note: {e}")

        if not summary:
            summary = (
                f"📌 **Overview**: Document '{fname}' contains {total_pages} page(s) and approximately {total_words} words.\n\n"
                f"🔑 **Key Highlights**:\n"
                f"• Ingested {total_pages} page(s) into ChromaDB for semantic vector retrieval.\n"
                f"• Ready for deep search and instant question answering.\n\n"
                f"💡 **Next Steps**: You can now ask any specific questions about this document."
            )

        return {
            "success": True,
            "filename": fname,
            "filepath": filepath,
            "total_pages": total_pages,
            "total_words": total_words,
            "summary": summary,
        }

    async def ingest_document(
        self,
        filepath: str,
        prompt: Optional[str] = None,
        user_id: str = "default"
    ) -> Dict[str, Any]:
        """Ingests and indexes document into ChromaDB, returns summary & takeaways."""
        analysis = await self.analyze_document(filepath, user_id=user_id)
        if not analysis.get("success"):
            return analysis

        summary_text = analysis.get("summary", "")
        # Extract structured takeaways
        lines = [
            l.strip("-•* ").strip()
            for l in summary_text.splitlines()
            if l.strip().startswith(("-", "•", "*", "1.", "2.", "3.", "4."))
        ]
        takeaways = lines[:4] if lines else [
            f"Indexed {analysis.get('total_pages', 1)} page(s) ({analysis.get('total_words', 0):,} words) into ChromaDB.",
            "Ready for semantic search and Q&A."
        ]

        user_answer = ""
        if prompt and not any(w in prompt.lower() for w in ("mail", "send", "email", "@")):
            qa_res = await self.query_document(prompt, user_id=user_id, filepath=filepath)
            if qa_res.get("success"):
                user_answer = qa_res.get("answer", "")

        return {
            "success": True,
            "filename": analysis.get("filename"),
            "filepath": filepath,
            "total_pages": analysis.get("total_pages", 1),
            "word_count": analysis.get("total_words", 0),
            "summary": summary_text,
            "key_takeaways": takeaways,
            "prompt_answer": user_answer,
        }

    async def query_document(self, query: str, user_id: str = "default", filepath: Optional[str] = None) -> Dict[str, Any]:
        """Performs semantic vector search and answers queries based on document contents."""
        results = memory_store.retrieve(query=query, n_results=4, user_id=user_id)
        relevant_chunks = [r["document"] for r in results if r.get("document")]

        if not relevant_chunks:
            return {
                "success": False,
                "query": query,
                "answer": "No relevant content found in the indexed documents. Please upload or analyze a PDF first.",
            }

        context_str = "\n\n".join(relevant_chunks)
        system_instruction = (
            "You are an expert Document Q&A Agent. Answer the user's question accurately using ONLY the provided document excerpts.\n"
            "Include page references when available. If the information is not in the text, state that clearly."
        )

        answer = ""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self.ollama_url}/api/generate",
                    json={
                        "model": self.model,
                        "system": system_instruction,
                        "prompt": f"Document Context:\n{context_str}\n\nQuestion: {query}",
                        "stream": False,
                    },
                )
                if resp.status_code == 200:
                    answer = resp.json().get("response", "").strip()
        except Exception as e:
            logger.warning(f"[DocumentQA] LLM Q&A note: {e}")

        if not answer:
            answer = f"Based on the indexed document excerpts:\n\n{relevant_chunks[0][:500]}..."

        return {
            "success": True,
            "query": query,
            "answer": answer,
            "sources_count": len(relevant_chunks),
        }


document_qa_agent = DocumentQAAgent()
