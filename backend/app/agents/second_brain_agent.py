"""Second Brain & Personal Knowledge Graph Agent for Nexus AI.

Maintains an interconnected, Obsidian-compatible local Markdown vault:
- Captures thoughts, ideas, tasks, and bookmarks with YAML metadata & wiki-links [[Topic]].
- Semantically queries vault files and extracts daily task rollups.
"""
import os
import re
import json
import logging
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
import httpx

logger = logging.getLogger(__name__)

VAULT_DIR = Path("D:/nexus_ai/second_brain")
NOTES_DIR = VAULT_DIR / "notes"
TASKS_DIR = VAULT_DIR / "tasks"
JOURNAL_DIR = VAULT_DIR / "journal"

for d in [NOTES_DIR, TASKS_DIR, JOURNAL_DIR]:
    d.mkdir(parents=True, exist_ok=True)


class SecondBrainAgent:
    """Agent managing persistent personal knowledge vault, notes, and task graphs."""

    def __init__(self, vault_path: Path = VAULT_DIR):
        self.vault_path = vault_path

    async def capture(
        self,
        text: str,
        category: str = "auto",
        tags: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Captures a thought, task, note, or reminder and files it into the vault."""
        now = datetime.now()
        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")
        date_str = now.strftime("%Y-%m-%d")

        # 1. Infer category if auto
        inferred_cat = category.lower()
        if inferred_cat == "auto":
            lower_t = text.lower()
            if any(w in lower_t for w in ("todo", "task", "remind", "need to", "must do")):
                inferred_cat = "task"
            elif any(w in lower_t for w in ("idea", "concept", "architecture", "what if")):
                inferred_cat = "idea"
            elif any(w in lower_t for w in ("journal", "today i", "feeling", "daily")):
                inferred_cat = "journal"
            else:
                inferred_cat = "note"

        # 2. Extract title & wikilinks
        first_line = text.strip().split("\n")[0]
        title = re.sub(r"[^a-zA-Z0-9_\-\s]", "", first_line)[:40].strip() or "Untitled_Note"
        filename_safe = title.replace(" ", "_")

        # Extract topics for wikilinks
        words = [w.capitalize() for w in re.findall(r"\b[A-Za-z]{4,}\b", text) if w.lower() not in ("with", "that", "this", "from", "have", "will", "todo")]
        wikilinks = [f"[[{w}]]" for w in set(words[:4])]

        # 3. Create Markdown File
        target_folder = TASKS_DIR if inferred_cat == "task" else (JOURNAL_DIR if inferred_cat == "journal" else NOTES_DIR)
        file_path = target_folder / f"{date_str}_{filename_safe}.md"

        frontmatter = (
            f"---\n"
            f"title: \"{title}\"\n"
            f"created: {timestamp_str}\n"
            f"category: {inferred_cat}\n"
            f"tags: {tags or [inferred_cat]}\n"
            f"---\n\n"
        )

        body = f"# {title}\n\n{text}\n\n---\n**Related Topics**: {' '.join(wikilinks)}\n"
        file_path.write_text(frontmatter + body, encoding="utf-8")
        logger.info(f"[SecondBrain] Captured note to {file_path}")

        return {
            "success": True,
            "title": title,
            "category": inferred_cat,
            "file_path": str(file_path),
            "wikilinks": wikilinks,
            "message": f"Saved {inferred_cat.upper()} '{title}' to Second Brain vault."
        }

    async def query_vault(self, query: str) -> Dict[str, Any]:
        """Searches across all markdown notes in the Second Brain vault."""
        matches = []
        q_lower = query.lower()

        for md_file in self.vault_path.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")
                if q_lower in content.lower():
                    matches.append({
                        "file": md_file.name,
                        "path": str(md_file),
                        "snippet": content[:300]
                    })
            except Exception:
                continue

        return {
            "success": True,
            "query": query,
            "count": len(matches),
            "results": matches[:10]
        }

    async def get_active_tasks(self) -> Dict[str, Any]:
        """Lists active tasks from the tasks vault."""
        tasks = []
        for tf in TASKS_DIR.glob("*.md"):
            try:
                content = tf.read_text(encoding="utf-8", errors="ignore")
                tasks.append({"file": tf.name, "summary": content.splitlines()[0] if content else tf.name})
            except Exception:
                continue

        return {
            "success": True,
            "task_count": len(tasks),
            "tasks": tasks
        }

    capture_thought = capture
    query = query_vault


second_brain_agent = SecondBrainAgent()
