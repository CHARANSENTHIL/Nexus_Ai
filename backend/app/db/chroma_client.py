import logging
from app.config import settings

logger = logging.getLogger(__name__)

try:
    import chromadb
except (ImportError, Exception) as e:
    logger.warning(f"ChromaDB could not be imported: {e}")
    chromadb = None

def get_chroma_client():
    if chromadb is None:
        return None
    try:
        client = chromadb.PersistentClient(path=settings.CHROMADB_PATH)
        return client
    except Exception as e:
        logger.warning(f"ChromaDB persistent client creation failed: {e}")
        return None
