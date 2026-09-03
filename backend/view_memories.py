"""
Nexus AI — Memory Viewer Utility
Run this script to view or search all stored memories in ChromaDB.

Usage:
  python view_memories.py            # View all stored memories
  python view_memories.py "chrome"   # Search memories for "chrome"
"""
import sys
import json
from app.memory.chroma_store import memory_store


def main():
    query = " ".join(sys.argv[1:]).strip() if len(sys.argv) > 1 else ""

    if not memory_store._collection:
        print("[!] ChromaDB collection is unavailable.")
        return

    if query:
        print(f"[+] Searching memories matching: '{query}'...\n")
        try:
            raw_res = memory_store._collection.query(query_texts=[query], n_results=10)
            docs = raw_res.get("documents", [[]])[0]
            metas = raw_res.get("metadatas", [[]])[0]
            ids = raw_res.get("ids", [[]])[0]
            print(f"Found {len(ids)} matching records:\n")
            for idx, (doc, meta) in enumerate(zip(docs, metas), 1):
                clean_doc = doc.encode("ascii", "ignore").decode("ascii").strip()
                print(f"[{idx}] Date: {meta.get('created_at', 'N/A')[:19]}")
                print(f"    Goal: {meta.get('goal', 'N/A')}")
                print(f"    Content: {clean_doc[:150]}...\n")
        except Exception as e:
            print(f"[!] Search failed: {e}")
        return

    try:
        data = memory_store._collection.get()
        ids = data.get("ids", [])
        docs = data.get("documents", [])
        metas = data.get("metadatas", [])

        print(f"=== Total Stored Memories in ChromaDB: {len(ids)} ===\n")

        for idx, (mem_id, doc, meta) in enumerate(zip(ids, docs, metas), 1):
            created = meta.get("created_at", "N/A")[:19] if isinstance(meta, dict) else "N/A"
            goal = meta.get("goal", "N/A") if isinstance(meta, dict) else "N/A"
            clean_doc = doc.encode("ascii", "ignore").decode("ascii").strip()
            first_line = clean_doc.split("\n")[0] if clean_doc else ""
            print(f"[{idx:02d}] ID: {mem_id[:8]}... | Date: {created} | Goal: {goal}")
            print(f"     Content: {first_line[:120]}...\n")

        print("=" * 60)
        print("Tip: Search memories by running: python view_memories.py <search_term>")

    except Exception as e:
        print(f"[!] Error fetching memories: {e}")


if __name__ == "__main__":
    main()
