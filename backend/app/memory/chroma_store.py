import uuid
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from app.db.chroma_client import get_chroma_client

logger = logging.getLogger(__name__)

class MemoryRecord(BaseModel):
    memory_id: str = Field(...)
    user_id: str = Field(...)
    project_id: str = Field(...)
    session_id: str = Field(...)
    text: str = Field(...)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class MemorySearchResult(BaseModel):
    memory_id: str = Field(...)
    text: str = Field(...)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    distance: float = Field(...)

class ChromaMemoryStore:
    def __init__(self, collection_name: str = "nexus_semantic_memory"):
        self.collection_name = collection_name
        self.client = get_chroma_client()
        self._collection = None
        if self.client is not None:
            try:
                self._collection = self.client.get_or_create_collection(name=self.collection_name)
            except Exception as e:
                logger.warning(f"Failed to get/create ChromaDB collection '{self.collection_name}': {e}")

    def add_memory(
        self,
        user_id: str,
        project_id: str,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = "default",
        memory_id: Optional[str] = None
    ) -> str:
        if not text or not text.strip():
            raise ValueError("Memory text content cannot be empty")

        mem_id = memory_id or str(uuid.uuid4())
        meta = metadata.copy() if metadata else {}
        meta.update({
            "user_id": str(user_id),
            "project_id": str(project_id),
            "session_id": str(session_id or "default"),
            "created_at": datetime.now(timezone.utc).isoformat()
        })

        if self._collection is not None:
            try:
                self._collection.add(
                    ids=[mem_id],
                    documents=[text],
                    metadatas=[meta]
                )
                logger.info(f"Stored memory {mem_id} in ChromaDB")
            except Exception as e:
                logger.error(f"Failed to persist memory {mem_id}: {e}")
        else:
            logger.warning(f"ChromaDB unavailable. Skipped memory persistence for {mem_id}")

        return mem_id

    def search_memory(
        self,
        user_id: str,
        project_id: str,
        query: str,
        top_k: int = 3,
        session_id: Optional[str] = None
    ) -> List[MemorySearchResult]:
        if not query or not query.strip():
            return []

        if self._collection is None:
            logger.warning("ChromaDB collection unavailable; returning empty search results.")
            return []

        where_conditions = [
            {"user_id": str(user_id)},
            {"project_id": str(project_id)}
        ]
        if session_id:
            where_conditions.append({"session_id": str(session_id)})

        where_clause = {"$and": where_conditions}

        try:
            results = self._collection.query(
                query_texts=[query],
                n_results=top_k,
                where=where_clause
            )

            search_results: List[MemorySearchResult] = []
            if results and results.get("ids") and len(results["ids"]) > 0 and len(results["ids"][0]) > 0:
                ids = results["ids"][0]
                documents = results.get("documents", [[]])[0]
                metadatas = results.get("metadatas", [[]])[0]
                distances = results.get("distances", [[]])[0] if results.get("distances") else [0.0] * len(ids)

                for doc_id, doc_text, meta, dist in zip(ids, documents, metadatas, distances):
                    search_results.append(MemorySearchResult(
                        memory_id=doc_id,
                        text=doc_text,
                        metadata=meta or {},
                        distance=float(dist)
                    ))
            return search_results
        except Exception as e:
            logger.error(f"Error querying ChromaDB semantic memory store: {e}")
            return []

    def store(self, document: str, metadata: Optional[Dict[str, Any]] = None, user_id: str = "default", project_id: str = "default") -> str:
        """Convenience method to store a text document."""
        return self.add_memory(user_id=user_id, project_id=project_id, text=document, metadata=metadata)

    def retrieve(self, query: str, n_results: int = 3, user_id: str = "default", project_id: str = "default") -> List[Dict[str, Any]]:
        """Convenience method to retrieve text memories matching query."""
        results = self.search_memory(user_id=user_id, project_id=project_id, query=query, top_k=n_results)
        return [{"document": r.text, "metadata": r.metadata, "id": r.memory_id} for r in results]


# Singleton instance
memory_store = ChromaMemoryStore()
