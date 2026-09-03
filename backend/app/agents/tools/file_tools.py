"""File Agent tools — search, move, copy, delete, compress, organize files."""
import os
import shutil
import zipfile
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional
from langchain.tools import tool


@tool
def search_files(directory: str, pattern: str = "*", recursive: bool = True, include_dirs: bool = True) -> List[Dict[str, Any]]:
    """Search for files or folders in a directory matching a glob pattern.
    directory: root directory to search (e.g. C:\\Users\\user\\Downloads)
    pattern: glob pattern (e.g. '*.pdf', '*Antigravity*', 'resume*')
    recursive: whether to search subdirectories
    include_dirs: whether to include folder matches"""
    results = []
    root = Path(directory)
    if not root.exists():
        return [{"error": f"Directory '{directory}' does not exist."}]
    try:
        glob_fn = root.rglob if recursive else root.glob
        for path in glob_fn(pattern):
            if path.is_file() or (include_dirs and path.is_dir()):
                stat = path.stat()
                results.append({
                    "path": str(path),
                    "name": path.name,
                    "is_dir": path.is_dir(),
                    "size_bytes": stat.st_size if path.is_file() else 0,
                    "size_mb": round(stat.st_size / (1024**2), 2) if path.is_file() else 0,
                    "modified": stat.st_mtime,
                    "extension": path.suffix if path.is_file() else "",
                })
        return sorted(results, key=lambda x: x["modified"], reverse=True)[:50]
    except PermissionError as e:
        return [{"error": f"Permission denied: {str(e)}"}]


@tool
def move_file(source: str, destination: str) -> Dict[str, Any]:
    """Move a file from source path to destination path.
    If destination is a directory, file is moved into it.
    DANGEROUS action for important files — may require approval."""
    src = Path(source)
    dst = Path(destination)
    if not src.exists():
        return {"success": False, "error": f"Source file not found: {source}"}
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return {"success": True, "message": f"Moved '{source}' → '{destination}'"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def copy_file(source: str, destination: str) -> Dict[str, Any]:
    """Copy a file from source to destination path."""
    src = Path(source)
    dst = Path(destination)
    if not src.exists():
        return {"success": False, "error": f"Source not found: {source}"}
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(str(src), str(dst), dirs_exist_ok=True)
        else:
            shutil.copy2(str(src), str(dst))
        return {"success": True, "message": f"Copied '{source}' → '{destination}'"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def delete_file(path: str) -> Dict[str, Any]:
    """Delete a file or directory at the given path.
    DANGEROUS — always requires explicit user approval before execution."""
    target = Path(path)
    if not target.exists():
        return {"success": False, "error": f"Path not found: {path}"}
    try:
        if target.is_dir():
            shutil.rmtree(str(target))
            return {"success": True, "message": f"Directory '{path}' deleted."}
        else:
            target.unlink()
            return {"success": True, "message": f"File '{path}' deleted."}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def compress_files(source_paths: List[str], output_zip: str) -> Dict[str, Any]:
    """Create a ZIP archive from a list of file/folder paths.
    source_paths: list of file or folder paths to compress
    output_zip: full path of the output .zip file"""
    out = Path(output_zip)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(str(out), "w", zipfile.ZIP_DEFLATED) as zf:
            for src in source_paths:
                p = Path(src)
                if p.is_file():
                    zf.write(str(p), p.name)
                elif p.is_dir():
                    for file in p.rglob("*"):
                        if file.is_file():
                            zf.write(str(file), str(file.relative_to(p.parent)))
        size_mb = round(out.stat().st_size / (1024**2), 2)
        return {
            "success": True,
            "output": str(out),
            "size_mb": size_mb,
            "message": f"Archive created: {output_zip} ({size_mb} MB)",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def list_directory(directory: str, show_hidden: bool = False) -> List[Dict[str, Any]]:
    """List contents of a directory with file sizes and types."""
    root = Path(directory)
    if not root.exists():
        return [{"error": f"Directory not found: {directory}"}]
    entries = []
    try:
        for entry in root.iterdir():
            if not show_hidden and entry.name.startswith("."):
                continue
            stat = entry.stat()
            entries.append({
                "name": entry.name,
                "path": str(entry),
                "is_dir": entry.is_dir(),
                "size_bytes": stat.st_size if entry.is_file() else 0,
                "extension": entry.suffix if entry.is_file() else "",
            })
        return sorted(entries, key=lambda x: (not x["is_dir"], x["name"]))
    except PermissionError:
        return [{"error": f"Permission denied for: {directory}"}]


@tool
def get_file_hash(file_path: str, algorithm: str = "sha256") -> Dict[str, Any]:
    """Compute a cryptographic hash (md5, sha1, sha256) of a file for integrity verification."""
    p = Path(file_path)
    if not p.is_file():
        return {"error": f"File not found: {file_path}"}
    hashers = {"md5": hashlib.md5, "sha1": hashlib.sha1, "sha256": hashlib.sha256}
    hasher = hashers.get(algorithm.lower(), hashlib.sha256)()
    try:
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
        return {"file": file_path, "algorithm": algorithm, "hash": hasher.hexdigest()}
    except Exception as e:
        return {"error": str(e)}


@tool
def organize_downloads(downloads_dir: str = None) -> Dict[str, Any]:
    """AI-classify and organize files in the Downloads folder into subfolders by type.
    Categories: Documents, Images, Videos, Audio, Archives, Code, Other"""
    if not downloads_dir:
        downloads_dir = str(Path.home() / "Downloads")
    root = Path(downloads_dir)
    if not root.exists():
        return {"success": False, "error": f"Downloads directory not found: {downloads_dir}"}

    categories = {
        "Documents": [".pdf", ".doc", ".docx", ".txt", ".xlsx", ".pptx", ".csv", ".odt"],
        "Images": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".ico"],
        "Videos": [".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm"],
        "Audio": [".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a"],
        "Archives": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"],
        "Code": [".py", ".js", ".ts", ".html", ".css", ".json", ".xml", ".yaml", ".sh", ".bat"],
    }

    moved = []
    errors = []
    for file in root.iterdir():
        if not file.is_file():
            continue
        ext = file.suffix.lower()
        target_cat = "Other"
        for cat, exts in categories.items():
            if ext in exts:
                target_cat = cat
                break
        target_dir = root / target_cat
        target_dir.mkdir(exist_ok=True)
        target_path = target_dir / file.name
        try:
            shutil.move(str(file), str(target_path))
            moved.append({"file": file.name, "category": target_cat})
        except Exception as e:
            errors.append({"file": file.name, "error": str(e)})

    return {
        "success": True,
        "organized": len(moved),
        "errors": len(errors),
        "moved": moved,
        "error_details": errors,
        "message": f"Organized {len(moved)} files in {downloads_dir}",
    }


@tool
def rename_file(source_path: str, new_name: str) -> Dict[str, Any]:
    """Rename a file or directory at source_path to new_name."""
    src = Path(source_path)
    if not src.exists():
        return {"success": False, "error": f"Path not found: {source_path}"}
    try:
        dst = src.parent / new_name
        src.rename(dst)
        return {"success": True, "message": f"Renamed '{src.name}' → '{new_name}' at {dst}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def search_and_rename_folder(search_name: str, new_name: str, root_dir: str = r"C:\Users\chara_qmka15y") -> Dict[str, Any]:
    """Search for a folder by name across the PC and rename it to new_name."""
    root = Path(root_dir)
    if not root.exists():
        # Fallback to current user home
        root = Path.home()

    found = []
    try:
        for p in root.rglob(f"*{search_name}*"):
            if p.is_dir():
                found.append(p)
    except Exception as e:
        pass

    if not found:
        return {"success": False, "error": f"No folder matching '{search_name}' found in {root}."}

    renamed = []
    for target in found:
        try:
            new_path = target.parent / new_name
            target.rename(new_path)
            renamed.append(f"Renamed folder '{target.name}' → '{new_name}' at `{new_path}`")
        except Exception as e:
            renamed.append(f"Failed to rename '{target.name}': {e}")

    return {"success": True, "message": "\n".join(renamed)}
