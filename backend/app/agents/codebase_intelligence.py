"""
Codebase Intelligence Layer — AST-based symbol indexer, dependency grapher, and targeted code retriever.
Enables autonomous software engineering without flooding LLM context with full file dumps.
"""
import ast
import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class SymbolInfo:
    def __init__(self, name: str, kind: str, file_path: str, start_line: int, end_line: int, docstring: str = "", signature: str = ""):
        self.name = name
        self.kind = kind  # "function", "class", "method", "variable", "import"
        self.file_path = file_path
        self.start_line = start_line
        self.end_line = end_line
        self.docstring = docstring
        self.signature = signature

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "docstring": self.docstring,
            "signature": self.signature,
        }


class CodebaseIntelligence:
    """
    Indexes files, extracts AST symbols, resolves dependencies, and returns targeted snippets.
    """

    def __init__(self, root_dir: Optional[str] = None):
        self.root_dir = Path(root_dir) if root_dir else Path(os.getcwd())
        self._symbols: Dict[str, List[SymbolInfo]] = {}  # symbol_name -> list of SymbolInfo
        self._file_symbols: Dict[str, List[SymbolInfo]] = {}  # file_path -> list of SymbolInfo
        self._file_imports: Dict[str, Set[str]] = {}  # file_path -> set of imported module names
        self._file_mtimes: Dict[str, float] = {}

    def scan_repository(self, target_dir: Optional[str] = None, max_files: int = 500) -> Dict[str, Any]:
        """Index all python files in the directory tree."""
        base_dir = Path(target_dir) if target_dir else self.root_dir
        indexed_count = 0
        skipped_count = 0

        ignore_dirs = {".git", ".venv", "venv", "__pycache__", "node_modules", "dist", "build", ".pytest_cache"}

        for root, dirs, files in os.walk(base_dir):
            dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith(".")]
            for file in files:
                if file.endswith(".py"):
                    full_path = Path(root) / file
                    try:
                        self.index_file(str(full_path))
                        indexed_count += 1
                        if indexed_count >= max_files:
                            break
                    except Exception as e:
                        logger.debug(f"[CodebaseIntelligence] Error indexing {full_path}: {e}")
                        skipped_count += 1
            if indexed_count >= max_files:
                break

        return {
            "root": str(base_dir),
            "indexed_files": indexed_count,
            "total_symbols": sum(len(syms) for syms in self._symbols.values()),
            "skipped_files": skipped_count,
        }

    def index_file(self, file_path: str):
        """Parse AST of a single Python file and extract symbols and imports."""
        p = Path(file_path)
        if not p.exists() or not p.is_file():
            return

        mtime = p.stat().st_mtime
        if file_path in self._file_mtimes and self._file_mtimes[file_path] == mtime:
            return  # Cache valid

        try:
            source = p.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=file_path)
        except Exception as e:
            logger.debug(f"[CodebaseIntelligence] Parse error in {file_path}: {e}")
            return

        self._file_mtimes[file_path] = mtime
        file_symbols: List[SymbolInfo] = []
        imports: Set[str] = set()

        lines = source.splitlines()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module)

            elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                doc = ast.get_docstring(node) or ""
                start_l = node.lineno
                end_l = getattr(node, "end_lineno", start_l + len(node.body))
                sig_line = lines[start_l - 1].strip() if start_l <= len(lines) else ""
                sym = SymbolInfo(
                    name=node.name,
                    kind="async_function" if isinstance(node, ast.AsyncFunctionDef) else "function",
                    file_path=file_path,
                    start_line=start_l,
                    end_line=end_l,
                    docstring=doc[:200],
                    signature=sig_line,
                )
                file_symbols.append(sym)
                self._add_symbol(sym)

            elif isinstance(node, ast.ClassDef):
                doc = ast.get_docstring(node) or ""
                start_l = node.lineno
                end_l = getattr(node, "end_lineno", start_l + len(node.body))
                sig_line = lines[start_l - 1].strip() if start_l <= len(lines) else ""
                sym = SymbolInfo(
                    name=node.name,
                    kind="class",
                    file_path=file_path,
                    start_line=start_l,
                    end_line=end_l,
                    docstring=doc[:200],
                    signature=sig_line,
                )
                file_symbols.append(sym)
                self._add_symbol(sym)

                # Collect methods inside class
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        m_doc = ast.get_docstring(item) or ""
                        m_start = item.lineno
                        m_end = getattr(item, "end_lineno", m_start + len(item.body))
                        m_sig = lines[m_start - 1].strip() if m_start <= len(lines) else ""
                        m_sym = SymbolInfo(
                            name=f"{node.name}.{item.name}",
                            kind="method",
                            file_path=file_path,
                            start_line=m_start,
                            end_line=m_end,
                            docstring=m_doc[:200],
                            signature=m_sig,
                        )
                        file_symbols.append(m_sym)
                        self._add_symbol(m_sym)

        self._file_symbols[file_path] = file_symbols
        self._file_imports[file_path] = imports

    def _add_symbol(self, sym: SymbolInfo):
        if sym.name not in self._symbols:
            self._symbols[sym.name] = []
        self._symbols[sym.name].append(sym)

    def find_symbol(self, query: str) -> List[Dict[str, Any]]:
        """Search indexed symbols by exact name or substring."""
        if not self._symbols:
            self.scan_repository()

        query_lower = query.lower()
        results = []
        for name, sym_list in self._symbols.items():
            if query_lower in name.lower():
                for s in sym_list:
                    results.append(s.to_dict())
        return results[:25]

    def get_file_outline(self, file_path: str) -> List[Dict[str, Any]]:
        """Get structural outline of all functions, classes, and methods in a file."""
        self.index_file(file_path)
        symbols = self._file_symbols.get(file_path, [])
        return [s.to_dict() for s in symbols]

    def get_symbol_source(self, file_path: str, symbol_name: str) -> Optional[str]:
        """Extract exact source code lines for a specific symbol without loading whole file."""
        self.index_file(file_path)
        symbols = self._file_symbols.get(file_path, [])
        for sym in symbols:
            if sym.name == symbol_name:
                try:
                    lines = Path(file_path).read_text(encoding="utf-8").splitlines()
                    extracted = lines[sym.start_line - 1 : sym.end_line]
                    return "\n".join(extracted)
                except Exception as e:
                    logger.error(f"[CodebaseIntelligence] Failed reading symbol source: {e}")
                    return None
        return None

    def find_referencing_files(self, symbol_name: str) -> List[str]:
        """Find files that import or reference a symbol name."""
        referencing = []
        for file_path, imports in self._file_imports.items():
            if any(symbol_name in imp for imp in imports):
                referencing.append(file_path)
        return referencing


# Global singleton
codebase_intelligence = CodebaseIntelligence(root_dir="D:\\nexus_ai\\backend")
