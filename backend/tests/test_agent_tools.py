"""
Unit tests for agent tools — System, Application, and File agents.
Covers ≥10 test cases with mocking to avoid real OS side effects.
"""
import pytest
from unittest.mock import patch, MagicMock, mock_open
from pathlib import Path


# ══════════════════════════════════════════════════════════════
# SYSTEM TOOLS TESTS
# ══════════════════════════════════════════════════════════════

class TestSystemTools:

    def test_get_system_state_fallback(self):
        """get_system_state falls back to psutil when Digital Twin is unreachable."""
        with patch("httpx.get", side_effect=Exception("connection refused")):
            with patch("psutil.cpu_percent", return_value=42.5), \
                 patch("psutil.virtual_memory") as mock_vm, \
                 patch("psutil.disk_usage") as mock_disk, \
                 patch("psutil.sensors_battery", return_value=None), \
                 patch("psutil.net_if_stats", return_value={"eth0": MagicMock()}), \
                 patch("psutil.pids", return_value=list(range(120))):
                mock_vm.return_value = MagicMock(percent=60.0, available=4 * 1024**3)
                mock_disk.return_value = MagicMock(percent=70.0)
                from app.agents.tools.system_tools import get_system_state
                result = get_system_state.invoke({})
                assert result["cpu_percent"] == 42.5
                assert result["ram_percent"] == 60.0
                assert result["process_count"] == 120

    def test_get_running_processes_filter(self):
        """get_running_processes filters by name substring correctly."""
        mock_proc = MagicMock()
        mock_proc.info = {"pid": 1234, "name": "python.exe", "cpu_percent": 1.5, "memory_percent": 0.5}
        with patch("psutil.process_iter", return_value=[mock_proc]):
            from app.agents.tools.system_tools import get_running_processes
            result = get_running_processes.invoke({"name_filter": "python"})
            assert any("python" in p["name"].lower() for p in result)

    def test_get_running_processes_empty_filter(self):
        """get_running_processes with empty filter returns all processes."""
        procs = [
            MagicMock(info={"pid": i, "name": f"proc{i}.exe", "cpu_percent": 0.1, "memory_percent": 0.1})
            for i in range(5)
        ]
        with patch("psutil.process_iter", return_value=procs):
            from app.agents.tools.system_tools import get_running_processes
            result = get_running_processes.invoke({"name_filter": ""})
            assert len(result) == 5

    def test_get_disk_usage_success(self):
        """get_disk_usage returns correct formatted disk stats."""
        mock_usage = MagicMock(total=500 * 1024**3, used=200 * 1024**3, free=300 * 1024**3, percent=40.0)
        with patch("psutil.disk_usage", return_value=mock_usage):
            from app.agents.tools.system_tools import get_disk_usage
            result = get_disk_usage.invoke({"path": "C:\\"})
            assert result["percent_used"] == 40.0
            assert result["free_gb"] == pytest.approx(300.0, abs=0.1)

    def test_kill_process_not_found(self):
        """kill_process returns error when PID doesn't exist."""
        import psutil
        with patch("psutil.Process", side_effect=psutil.NoSuchProcess(pid=9999)):
            from app.agents.tools.system_tools import kill_process
            result = kill_process.invoke({"pid": 9999})
            assert result["success"] is False
            assert "not found" in result["error"]

    def test_check_network_connectivity_success(self):
        """check_network_connectivity returns connected=True on successful ping."""
        mock_result = MagicMock(returncode=0, stdout="Reply from 8.8.8.8")
        with patch("subprocess.run", return_value=mock_result):
            from app.agents.tools.system_tools import check_network_connectivity
            result = check_network_connectivity.invoke({"host": "8.8.8.8"})
            assert result["connected"] is True

    def test_check_network_connectivity_failure(self):
        """check_network_connectivity returns connected=False on failed ping."""
        mock_result = MagicMock(returncode=1, stdout="Request timed out")
        with patch("subprocess.run", return_value=mock_result):
            from app.agents.tools.system_tools import check_network_connectivity
            result = check_network_connectivity.invoke({"host": "192.168.999.999"})
            assert result["connected"] is False


# ══════════════════════════════════════════════════════════════
# APPLICATION TOOLS TESTS
# ══════════════════════════════════════════════════════════════

class TestApplicationTools:

    def test_open_application_success(self):
        """open_application successfully launches a process."""
        mock_proc = MagicMock(pid=5678)
        with patch("subprocess.Popen", return_value=mock_proc), \
             patch("time.sleep"):
            from app.agents.tools.app_tools import open_application
            result = open_application.func(app_name="notepad", args="")
            assert result["success"] is True
            assert result["pid"] == 5678

    def test_open_application_not_found(self):
        """open_application returns error when executable not found."""
        with patch("subprocess.Popen", side_effect=FileNotFoundError):
            from app.agents.tools.app_tools import open_application
            result = open_application.func(app_name="nonexistent_app_xyz", args="")
            assert result["success"] is False
            assert "not found" in result["error"]

    def test_close_application_success(self):
        """close_application terminates matching processes."""
        mock_proc = MagicMock()
        mock_proc.info = {"pid": 1111, "name": "notepad.exe"}
        with patch("psutil.process_iter", return_value=[mock_proc]):
            from app.agents.tools.app_tools import close_application
            result = close_application.invoke({"app_name": "notepad"})
            assert result["success"] is True
            assert len(result["closed"]) >= 1

    def test_close_application_not_running(self):
        """close_application returns error when no matching process found."""
        with patch("psutil.process_iter", return_value=[]):
            from app.agents.tools.app_tools import close_application
            result = close_application.invoke({"app_name": "nonexistent_app"})
            assert result["success"] is False

    def test_run_shell_command_success(self):
        """run_shell_command captures stdout on success."""
        mock_result = MagicMock(returncode=0, stdout="hello world", stderr="")
        with patch("subprocess.run", return_value=mock_result):
            from app.agents.tools.app_tools import run_shell_command
            result = run_shell_command.invoke({"command": "echo hello world", "timeout": 10})
            assert result["success"] is True
            assert "hello" in result["stdout"]

    def test_run_shell_command_timeout(self):
        """run_shell_command handles timeout gracefully."""
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("sleep", 5)):
            from app.agents.tools.app_tools import run_shell_command
            result = run_shell_command.invoke({"command": "sleep 999", "timeout": 5})
            assert result["success"] is False
            assert "timed out" in result["error"]


# ══════════════════════════════════════════════════════════════
# FILE TOOLS TESTS
# ══════════════════════════════════════════════════════════════

class TestFileTools:

    def test_search_files_nonexistent_dir(self):
        """search_files returns error for a directory that doesn't exist."""
        from app.agents.tools.file_tools import search_files
        result = search_files.invoke({
            "directory": "C:\\DoesNotExist_xyz_123",
            "pattern": "*",
            "recursive": False,
        })
        assert any("not exist" in str(r.get("error", "")) for r in result)

    def test_list_directory_success(self, tmp_path):
        """list_directory returns entries for an existing directory."""
        (tmp_path / "file1.txt").write_text("hello")
        (tmp_path / "file2.py").write_text("print()")
        (tmp_path / "subdir").mkdir()
        from app.agents.tools.file_tools import list_directory
        result = list_directory.invoke({"directory": str(tmp_path), "show_hidden": False})
        names = [e["name"] for e in result]
        assert "file1.txt" in names
        assert "file2.py" in names
        assert "subdir" in names

    def test_copy_file_success(self, tmp_path):
        """copy_file copies a file to destination."""
        src = tmp_path / "source.txt"
        src.write_text("test content")
        dst = tmp_path / "dest.txt"
        from app.agents.tools.file_tools import copy_file
        result = copy_file.invoke({"source": str(src), "destination": str(dst)})
        assert result["success"] is True
        assert dst.read_text() == "test content"

    def test_copy_file_missing_source(self, tmp_path):
        """copy_file returns error when source doesn't exist."""
        from app.agents.tools.file_tools import copy_file
        result = copy_file.invoke({
            "source": str(tmp_path / "nonexistent.txt"),
            "destination": str(tmp_path / "dest.txt"),
        })
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_compress_files_success(self, tmp_path):
        """compress_files creates a valid ZIP archive."""
        f1 = tmp_path / "a.txt"
        f1.write_text("content a")
        f2 = tmp_path / "b.txt"
        f2.write_text("content b")
        out_zip = tmp_path / "archive.zip"
        from app.agents.tools.file_tools import compress_files
        result = compress_files.invoke({
            "source_paths": [str(f1), str(f2)],
            "output_zip": str(out_zip),
        })
        assert result["success"] is True
        assert out_zip.exists()

    def test_get_file_hash_sha256(self, tmp_path):
        """get_file_hash returns a valid SHA256 hash for a file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("nexus ai test")
        from app.agents.tools.file_tools import get_file_hash
        result = get_file_hash.invoke({"file_path": str(test_file), "algorithm": "sha256"})
        assert "hash" in result
        assert len(result["hash"]) == 64  # SHA256 = 64 hex chars

    def test_get_file_hash_missing_file(self, tmp_path):
        """get_file_hash returns error for nonexistent file."""
        from app.agents.tools.file_tools import get_file_hash
        result = get_file_hash.invoke({
            "file_path": str(tmp_path / "missing.txt"),
            "algorithm": "sha256",
        })
        assert "error" in result

    def test_delete_file_success(self, tmp_path):
        """delete_file removes a file successfully."""
        target = tmp_path / "delete_me.txt"
        target.write_text("bye")
        from app.agents.tools.file_tools import delete_file
        result = delete_file.invoke({"path": str(target)})
        assert result["success"] is True
        assert not target.exists()

    def test_organize_downloads(self, tmp_path):
        """organize_downloads moves files into correct category subfolders."""
        (tmp_path / "report.pdf").write_text("pdf")
        (tmp_path / "photo.jpg").write_bytes(b"\xff\xd8\xff")
        (tmp_path / "script.py").write_text("print()")
        from app.agents.tools.file_tools import organize_downloads
        result = organize_downloads.invoke({"downloads_dir": str(tmp_path)})
        assert result["success"] is True
        assert result["organized"] == 3
        assert (tmp_path / "Documents" / "report.pdf").exists()
        assert (tmp_path / "Images" / "photo.jpg").exists()
        assert (tmp_path / "Code" / "script.py").exists()
