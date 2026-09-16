# 🛡️ Nexus AI Sovereign Security Threat Model

> **Scope**: Security, Isolation, Authorization, and Data Privacy for Local Sovereign AI Agents operating on host operating systems.

---

## 1. Executive Summary & Philosophy

Nexus AI executes multi-step objectives on host operating systems and the web. Because agents have access to shell tools, filesystem APIs, and browser automation, **the model itself can never be trusted with its own authorization boundaries**. 

Our security architecture enforces:
1. **Deterministic Pre-Execution Policy Engine (PolicyEngine)**: Static regex, AST analysis, and privilege gating that intercept actions *before* any subprocess or tool executes.
2. **Zero-Knowledge Credential Vault (CredentialManager)**: Passwords and secrets are stored in a PBKDF2 + AES (Fernet) encrypted vault and injected directly into DOM elements by Playwright — secrets never enter prompt contexts, logs, or vector stores.
3. **Isolated Staging Sandboxes (WorkspaceSandbox)**: Multi-step file edits and code generation are tested and syntax-validated in temporary isolated sandboxes before committing to active repositories.
4. **Human Handoff & Approval Checkpoints (HandoffEngine)**: 2FA/OTP prompts, CAPTCHAs, and high-privilege Level 2/3 operations trigger asynchronous cryptographic checkpoints requiring user confirmation via Telegram.

---

## 2. STRIDE Threat Analysis Matrix

| Threat Category | Attack Vector | Existing Mitigation & Defense | Residual Risk | Automated Test Suite |
| :--- | :--- | :--- | :--- | :--- |
| **Spoofing** | Adversary sends forged command via unauthenticated Telegram chat or API. | Strict user ID whitelist (TELEGRAM_ALLOWED_USER_IDS) and JWT-backed REST authentication. | Compromise of Telegram client account. | ackend/evals/security/test_adversarial_security.py |
| **Tampering** | Prompt injection in web page text attempts to disable antivirus (Set-MpPreference). | Pre-execution PolicyEngine regex blocks all critical defense modifications (Level 4). | Obfuscated PowerShell execution using novel encoding. | SEC-BLK-001 through SEC-BLK-020 |
| **Repudiation** | An agent makes destructive changes without record. | Append-Only Sequence-Numbered ExecutionEventLog (~/.nexus_ai/events.db) with cryptographic hashes. | Physical tampering of local SQLite database file. | 	est_event_log_replay in runtime suite |
| **Information Disclosure** | LLM outputs plaintext passwords or API keys to chat/logs. | Vault credentials are never passed into LLM prompt contexts; injected via Playwright DOM selector. | Memory dumps of active browser process memory. | SEC-SAF-008 & CredentialVaultTest |
| **Denial of Service** | Agent fork-bomb (:(){ :|:& };:) or infinite retry loops. | Bounded Recovery Engine (\_retries = 3$), static pattern block for fork bombs, and CPU timeouts. | Runaway external compiler/process consumption. | SEC-BLK-013 & ResourceLockManager |
| **Elevation of Privilege** | Agent attempts 
unas /user:Administrator or UAC bypass. | Level 4 Privileged operations are hard blocked; destructive Level 3 operations require manual approval. | Zero-day kernel elevation exploit on host OS. | SEC-INJ-004 & PolicyEngine |

---

## 3. Tool Capability Tier Hierarchy

`mermaid
graph TD
    A[Action Requested by Agent] --> B{PolicyEngine Gate}
    B -->|Level 0: Read-Only| C[ALLOW DIRECTLY
get_system_state, search_files, read_page]
    B -->|Level 1: Safe Write| D[ALLOW DIRECTLY
open_app, pptx_create, copy_file]
    B -->|Level 2: Sensitive| E[REQUIRE APPROVAL
send_email, inject_credentials]
    B -->|Level 3: Destructive| F[REQUIRE APPROVAL
delete_file, kill_process, shell_exec]
    B -->|Level 4: Privileged / Malware| G[HARD BLOCKED
Set-MpPreference, reg delete HKLM, fork bombs]
    
    style C fill:#059669,color:#fff
    style D fill:#2563eb,color:#fff
    style E fill:#d97706,color:#fff
    style F fill:#dc2626,color:#fff
    style G fill:#000000,color:#fff
`

---

## 4. Verification & Testing

Every threat vector is tested against our **100-Prompt Adversarial Security Evaluation Suite**:

`powershell
python backend/evals/security/test_adversarial_security.py
`

Results: **100/100 (100.0%) Adversarial Attacks Correctly Intercepted and Classified.**
