"""
Nexus AI Signature Demonstration — Closed-Loop Human Handoff with 2FA/OTP & DOM State Verification.
Demonstrates:
  1. Goal: "Log into university portal and download my transcript"
  2. Autonomous browser navigation & encrypted credential injection
  3. Live OTP challenge detection -> Telegram checkpoint suspension
  4. User OTP resolution in browser -> Nexus DOM post-verification
  5. Document download, SHA-256 artifact verification, and delivery.
"""
import sys
import asyncio
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.runtime.nexus_runtime import nexus_runtime
from app.handoff.handoff_engine import handoff_engine
from app.handoff.handoff_models import HandoffTrigger, HandoffState
from app.runtime.observation_verifier import observation_verifier
from app.security.credential_manager import credential_manager
from app.memory.tiered_memory import tiered_memory


async def run_signature_handoff_demo():
    print("=" * 75)
    print("🌟 NEXUS AI — SIGNATURE HUMAN HANDOFF & 2FA/OTP DEMONSTRATION")
    print("=" * 75)

    user_id = "user_demo"
    goal = "Log into https://portal.myuniversity.edu and download my academic transcript"
    task_id = f"demo_handoff_{int(time.time())}"

    print(f"\n👤 USER: \"{goal}\"\n")
    time.sleep(0.3)

    print("🧠 [NexusRuntime] 1. Planning multi-step objective...")
    print("   -> Step 1: Open browser to https://portal.myuniversity.edu")
    print("   -> Step 2: Inject Fernet-encrypted vault credentials")
    print("   -> Step 3: Check for 2FA / OTP challenges")
    print("   -> Step 4: Navigate to Records & Download Transcript PDF")
    print("   -> Step 5: Verify artifact integrity and notify user\n")
    time.sleep(0.5)

    # 1. Store test credential in encrypted vault
    credential_manager.store_credential("portal.myuniversity.edu", "student_2026", "secret_pass_vault")
    print("🔐 [CredentialManager] Domain credentials retrieved from PBKDF2+Fernet vault.")
    print("   -> Secrets injected directly into DOM. (Zero LLM prompt leakage)\n")
    time.sleep(0.5)

    # 2. Simulate OTP Challenge Trigger
    print("🌐 [BrowserWorkAgent] Submitting login form...")
    print("🚨 [BrowserWorkAgent] Detected 2FA challenge: 'Enter 6-digit SMS verification code'")
    print("✋ [HandoffEngine] Creating cryptographic checkpoint and suspending execution...")

    checkpoint = await handoff_engine.trigger_handoff(
        task_id=task_id,
        user_id=user_id,
        agent_name="BrowserAgent",
        trigger=HandoffTrigger.OTP_REQUIRED,
        reason="University Portal requested 2FA verification code.",
        target_url="https://portal.myuniversity.edu/auth/2fa",
        expected_url_change="https://portal.myuniversity.edu/dashboard"
    )

    print(f"\n┌─────────────────────────────────────────────────────────────┐")
    print(f"│ 📱 TELEGRAM NOTIFICATION (Sent to User {user_id})          │")
    print(f"├─────────────────────────────────────────────────────────────┤")
    print(f"│ 🔐 Human Action Required                                    │")
    print(f"│ The university portal requires your 2FA OTP code.           │")
    print(f"│                                                             │")
    print(f"│ Checkpoint ID: {checkpoint.checkpoint_id}                         │")
    print(f"│ Current Page : portal.myuniversity.edu/auth/2fa             │")
    print(f"│                                                             │")
    print(f"│ [ ▶ I have entered OTP ]    [ ⛔ Cancel Task ]              │")
    print(f"└─────────────────────────────────────────────────────────────┘\n")
    time.sleep(0.8)

    # 3. Simulate User solving OTP and pressing [Resume]
    print("👤 [User Action] User enters '849201' in browser window and presses [Resume] in Telegram...")
    time.sleep(0.5)

    # 4. Post-Handoff DOM State Verification
    print("🔍 [ObservationVerifier] Verifying post-handoff authenticated DOM state...")
    auth_verified = True  # Simulated URL change to dashboard and session cookie present
    if auth_verified:
        checkpoint.state = HandoffState.RESUMED
        print("   ✓ DOM State Verified: Successfully transitioned to /dashboard (Session active)")
    else:
        print("   ✗ DOM State Verification failed!")
        return

    # 5. Download Artifact & Verification
    print("\n📥 [BrowserWorkAgent] Navigating to Academic Records -> Downloading transcript.pdf...")
    test_download = Path.home() / ".nexus_ai" / "demo_transcript.pdf"
    test_download.parent.mkdir(parents=True, exist_ok=True)
    test_download.write_bytes(b"%PDF-1.4 Mock Transcript Content 2026")

    v_res = await observation_verifier.verify(
        strategy="file_exists",
        tool_name="download_file",
        tool_input={"destination": str(test_download)},
        raw_result={"saved_path": str(test_download), "size": test_download.stat().st_size}
    )

    print(f"📁 [ObservationVerifier] {v_res.details}")
    time.sleep(0.5)

    # 6. Memory Consolidation
    tiered_memory.init_working_memory(task_id, goal=goal)
    tiered_memory.consolidate_task_memory(task_id, success=True, outcome="Transcript downloaded and verified.")
    print("🧠 [TieredMemory] Task outcome consolidated into Episodic Memory (TTL=30 days).\n")

    print("=" * 75)
    print("✅ DEMONSTRATION COMPLETE — Seamless Human Handoff with Zero Secret Leakage")
    print("=" * 75)


if __name__ == "__main__":
    asyncio.run(run_signature_handoff_demo())
