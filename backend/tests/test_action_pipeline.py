"""
Unit tests for Action → Observation → Verification pipeline.

Tests:
  - Action / Observation / VerificationResult model creation
  - VerificationEngine dispatch and short-circuit logic
  - ActionPipeline idempotency check
  - RecoveryAgent strategy selection
  - AuditLogger JSONL fallback
"""

import asyncio
import os
import sys
import json
import pytest

# Ensure backend package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.agents.action_observation import (
    Action, Observation, VerificationCheck, VerificationResult, PipelineResult,
    default_timeout, ACTION_TIMEOUTS,
)


# ── Model Tests ─────────────────────────────────────────────────────────────────
class TestActionModel:
    def test_default_id_generated(self):
        a = Action(tool="open_url", arguments={"url": "https://youtube.com"},
                   expected_state={"url_contains": "youtube.com"})
        assert a.id and len(a.id) > 0

    def test_factory_derives_timeout(self):
        a = Action.create("open_url", {"url": "x"}, {"url_contains": "x"})
        assert a.timeout == ACTION_TIMEOUTS["open_url"]

    def test_factory_default_timeout_for_unknown_tool(self):
        a = Action.create("some_custom_tool", {}, {})
        assert a.timeout == ACTION_TIMEOUTS["default"]

    def test_click_timeout(self):
        assert default_timeout("click") == ACTION_TIMEOUTS["click"]
        assert default_timeout("click_coordinates") == ACTION_TIMEOUTS["click"]

    def test_browser_navigate_timeout(self):
        assert default_timeout("browser_navigate") == ACTION_TIMEOUTS["browser_navigate"]


class TestObservationModel:
    def test_default_empty(self):
        obs = Observation()
        assert obs.process_state == {}
        assert obs.errors == []

    def test_with_data(self):
        obs = Observation(
            browser_state={"url": "https://youtube.com", "title": "YouTube"},
            errors=["one error"],
        )
        assert obs.browser_state["url"] == "https://youtube.com"
        assert len(obs.errors) == 1


class TestVerificationResult:
    def test_success_true(self):
        vr = VerificationResult(success=True, confidence=0.95, reason="OK")
        assert vr.success is True

    def test_checks_default_empty(self):
        vr = VerificationResult(success=False, confidence=0.0)
        assert vr.checks == []


class TestPipelineResult:
    def test_skipped_default_false(self):
        pr = PipelineResult(success=True, action_id="abc")
        assert pr.skipped is False
        assert pr.recovered is False
        assert pr.attempt == 0


# ── VerificationEngine Tests ────────────────────────────────────────────────────
class TestVerificationEngine:
    """Test the engine without actually connecting to real OS/browser."""

    def test_no_verifiers_applicable_returns_success(self):
        """Action with no expected_state keys → no verifiers apply → success."""
        from app.agents.verifiers import verification_engine
        action = Action(tool="sleep", arguments={"seconds": 1}, expected_state={})
        obs = Observation()
        result = asyncio.run(verification_engine.verify(action, obs))
        assert result.success is True
        assert result.confidence == 0.5

    def test_ocr_verifier_match(self):
        """OCRVerifier finds keyword in pre-populated observation OCR text."""
        from app.agents.verifiers import OCRVerifier
        verifier = OCRVerifier()
        action = Action(tool="type_text", arguments={}, expected_state={"ocr_contains": "marvel"})
        obs = Observation(screen_state={"ocr_text": "Browse Marvel latest video views 2.4M ago"})
        check = asyncio.run(verifier.verify(action, obs))
        assert check is not None
        assert check.passed is True
        assert check.confidence >= 0.7

    def test_ocr_verifier_no_match(self):
        from app.agents.verifiers import OCRVerifier
        verifier = OCRVerifier()
        action = Action(tool="type_text", arguments={}, expected_state={"ocr_contains": "nonexistent_keyword_xyz"})
        obs = Observation(screen_state={"ocr_text": "something completely different"})
        check = asyncio.run(verifier.verify(action, obs))
        assert check is not None
        assert check.passed is False

    def test_ocr_verifier_partial_match_list(self):
        """3 keywords, 2 found → ratio 0.67 → passed (≥0.5)."""
        from app.agents.verifiers import OCRVerifier
        verifier = OCRVerifier()
        action = Action(tool="type_text", arguments={},
                        expected_state={"ocr_contains": ["views", "ago", "missing_word"]})
        obs = Observation(screen_state={"ocr_text": "Marvel Channel 4.2M views 2 days ago"})
        check = asyncio.run(verifier.verify(action, obs))
        assert check.passed is True

    def test_file_verifier_existing_file(self, tmp_path):
        from app.agents.verifiers import FileVerifier
        f = tmp_path / "test_file.txt"
        f.write_text("hello")
        action = Action(tool="run_shell_command", arguments={},
                        expected_state={"file_exists": str(f)})
        obs = Observation()
        check = asyncio.run(FileVerifier().verify(action, obs))
        assert check.passed is True
        assert check.confidence == 1.0

    def test_file_verifier_missing_file(self):
        from app.agents.verifiers import FileVerifier
        action = Action(tool="run_shell_command", arguments={},
                        expected_state={"file_exists": r"C:\does\not\exist\file.txt"})
        obs = Observation()
        check = asyncio.run(FileVerifier().verify(action, obs))
        assert check.passed is False

    def test_not_applicable_returns_none(self):
        from app.agents.verifiers import ProcessVerifier
        action = Action(tool="open_url", arguments={}, expected_state={"url_contains": "x"})
        obs = Observation()
        check = asyncio.run(ProcessVerifier().verify(action, obs))
        assert check is None  # process not in expected_state → not applicable

    def test_engine_short_circuits_on_high_confidence(self):
        """Engine should short-circuit after first passing check with confidence ≥ 0.8."""
        from app.agents.verifiers import verification_engine
        # FileVerifier returns confidence=1.0 → should short-circuit
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name

        action = Action(tool="dummy", arguments={},
                        expected_state={"file_exists": tmp_path})
        obs = Observation()
        result = asyncio.run(verification_engine.verify(action, obs))
        os.unlink(tmp_path)
        assert result.success is True
        assert result.confidence == 1.0
        assert len(result.checks) == 1  # short-circuited after FileVerifier


# ── RecoveryAgent Tests ─────────────────────────────────────────────────────────
class TestRecoveryAgent:
    def test_attempt_1_returns_wait_retry(self):
        from app.agents.recovery_agent import recovery_agent, RecoveryStrategy
        action = Action(tool="open_url", arguments={"url": "https://youtube.com"},
                        expected_state={"url_contains": "youtube.com"})
        obs = Observation()
        decision = asyncio.run(recovery_agent.handle(action, obs, attempt=1))
        assert decision.strategy == RecoveryStrategy.WAIT_RETRY
        assert decision.action is action

    def test_attempt_2_returns_inspect_retry(self):
        from app.agents.recovery_agent import recovery_agent, RecoveryStrategy
        action = Action(tool="click_coordinates", arguments={"x": 100, "y": 200},
                        expected_state={})
        obs = Observation()
        decision = asyncio.run(recovery_agent.handle(action, obs, attempt=2))
        assert decision.strategy == RecoveryStrategy.INSPECT_RETRY

    def test_attempt_3_returns_restart_retry(self):
        from app.agents.recovery_agent import recovery_agent, RecoveryStrategy
        action = Action(tool="open_url", arguments={}, expected_state={})
        obs = Observation()
        decision = asyncio.run(recovery_agent.handle(action, obs, attempt=3))
        assert decision.strategy == RecoveryStrategy.RESTART_RETRY

    def test_attempt_4_returns_escalate(self):
        from app.agents.recovery_agent import recovery_agent, RecoveryStrategy
        action = Action(tool="open_url", arguments={}, expected_state={})
        obs = Observation()
        decision = asyncio.run(recovery_agent.handle(action, obs, attempt=4))
        assert decision.strategy == RecoveryStrategy.ESCALATE


# ── AuditLogger Tests ───────────────────────────────────────────────────────────
class TestAuditLogger:
    def test_jsonl_fallback_writes_record(self, tmp_path):
        from app.agents.audit_logger import AuditLogger
        logger = AuditLogger()
        import app.agents.audit_logger as audit_mod
        original_path = audit_mod.AUDIT_LOG_PATH
        test_path = str(tmp_path / "test_audit.jsonl")
        audit_mod.AUDIT_LOG_PATH = test_path
        # Force PostgreSQL to be marked unavailable so we go to JSONL
        logger._pg_available = False

        action = Action(tool="open_url", arguments={"url": "https://youtube.com"},
                        expected_state={"url_contains": "youtube.com"})
        obs = Observation(browser_state={"url": "https://youtube.com"})
        vr = VerificationResult(success=True, confidence=0.95,
                                checks=[], reason="BrowserVerifier confirmed")
        asyncio.run(logger.log(action, obs, vr, latency_ms=234, attempt=0))

        audit_mod.AUDIT_LOG_PATH = original_path  # restore

        assert os.path.exists(test_path)
        with open(test_path) as f:
            record = json.loads(f.readline())
        assert record["tool"] == "open_url"
        assert record["success"] is True
        assert record["confidence"] == 0.95
        assert record["latency_ms"] == 234


# ── ActionPipeline Idempotency Tests ────────────────────────────────────────────
class TestActionPipelineIdempotency:
    def test_url_idempotency_skip(self):
        from app.agents.action_pipeline import _already_satisfied
        action = Action(tool="open_url", arguments={"url": "https://youtube.com"},
                        expected_state={"url_contains": "youtube.com"})
        obs = Observation(browser_state={"url": "https://www.youtube.com/results?search_query=marvel"})
        result = asyncio.run(_already_satisfied(action, obs))
        assert result is True  # already on youtube.com

    def test_url_no_skip_when_different_url(self):
        from app.agents.action_pipeline import _already_satisfied
        action = Action(tool="open_url", arguments={"url": "https://youtube.com"},
                        expected_state={"url_contains": "youtube.com"})
        obs = Observation(browser_state={"url": "https://google.com"})
        result = asyncio.run(_already_satisfied(action, obs))
        assert result is False

    def test_process_idempotency_skip(self):
        from app.agents.action_pipeline import _already_satisfied
        action = Action(tool="open_application", arguments={"app_name": "chrome"},
                        expected_state={"process": "chrome"})
        obs = Observation(process_state={"running_names": ["chrome.exe", "notepad.exe"]})
        result = asyncio.run(_already_satisfied(action, obs))
        assert result is True

    def test_build_youtube_actions_count(self):
        from app.agents.action_pipeline import build_youtube_actions
        actions = build_youtube_actions("marvel latest video")
        assert len(actions) >= 5  # must have all 5 steps
        assert actions[0].tool == "open_url"
        assert "youtube.com" in actions[0].arguments["url"]
        # Last action should verify playback
        assert actions[-1].description.lower().find("video") != -1


# ── Compound Goal Detection Tests ───────────────────────────────────────────────
class TestCompoundGoalDetection:
    """Verify _is_compound_goal correctly identifies multi-step prompts."""

    def _check(self, text: str) -> bool:
        import sys
        sys.path.insert(0, "D:\\nexus_ai\\backend")
        from app.agents.planner import _is_compound_goal
        return _is_compound_goal(text.lower())

    def test_open_chrome_go_to_youtube_search_tell_me(self):
        """The exact failing scenario from the user's screenshot."""
        assert self._check(
            "Open Chrome, go to YouTube, search for Python tutorials, and tell me when the results are ready"
        ) is True

    def test_search_for_with_youtube(self):
        assert self._check("search for python tutorials on youtube") is True

    def test_go_to_combined_with_search(self):
        assert self._check("go to youtube and search for marvel") is True

    def test_and_tell_me_marker(self):
        assert self._check("open spotify and tell me what's playing") is True

    def test_two_commas_means_multi_step(self):
        assert self._check("open chrome, navigate to reddit, find the top post") is True

    def test_simple_open_not_compound(self):
        """Single open command with no secondary action should NOT be compound."""
        assert self._check("open chrome") is False

    def test_play_video_compound(self):
        assert self._check("play the latest video from marvel") is True

    def test_watch_channel_compound(self):
        assert self._check("watch the linus tech tips channel") is True
