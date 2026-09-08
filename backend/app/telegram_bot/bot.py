"""
Telegram Bot — Nexus AI interface.
- Receives natural language goals (no slash commands)
- Validates Telegram user whitelist
- Streams token-by-token responses by live-editing a single message
- Sends structured final summary
- Handles Approve/Reject inline keyboard for dangerous actions
"""
import asyncio
import logging
import time
import uuid
from typing import Optional, AsyncGenerator

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes,
)

from app.config import settings
from app.approval.executor import approval_center

import sys
import os

logger = logging.getLogger(__name__)

# Lazy import to avoid circular deps
_planner = None
_memory_store = None
_lock_fd = None


def acquire_bot_lock() -> bool:
    """Ensure only ONE process runs Telegram bot polling to prevent 409 Conflict errors."""
    global _lock_fd
    lock_file = os.path.join(os.path.dirname(__file__), "telegram_bot.lock")
    try:
        if sys.platform == "win32":
            import msvcrt
            fd = open(lock_file, "w")
            msvcrt.locking(fd.fileno(), msvcrt.LK_NBLCK, 1)
            _lock_fd = fd
            return True
        else:
            import fcntl
            fd = open(lock_file, "w")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            _lock_fd = fd
            return True
    except (IOError, OSError):
        return False



def _get_planner():
    global _planner
    if _planner is None:
        from app.agents.planner import planner_agent
        _planner = planner_agent
    return _planner


def _get_memory():
    global _memory_store
    if _memory_store is None:
        from app.memory.chroma_store import memory_store
        _memory_store = memory_store
    return _memory_store


def is_allowed(user_id: int) -> bool:
    allowed = settings.TELEGRAM_ALLOWED_USER_IDS
    if not allowed:
        return True
    return user_id in allowed



# ── Progress notification helper ──────────────────────────────────────────────
async def send_progress(bot, chat_id: int, message: str):
    try:
        await bot.send_message(chat_id=chat_id, text=message, parse_mode="Markdown")
    except Exception as e:
        logger.warning(f"Markdown send failed ({e}), retrying as plain text")
        try:
            await bot.send_message(chat_id=chat_id, text=message)
        except Exception as e2:
            logger.error(f"Failed to send message even as plain text: {e2}")


# ── Live streaming helper — edits one message as tokens arrive ─────────────────
async def stream_reply(
    bot,
    chat_id: int,
    token_stream: AsyncGenerator[str, None],
    placeholder: str = "✍️ ...",
    min_edit_interval: float = 0.3,
) -> str:
    """
    Sends one initial message, then edits it live as tokens stream in.
    Throttled to ~1 edit per min_edit_interval seconds to stay under
    Telegram's rate limit (30 edits/min per chat).
    Returns the final full text.
    """
    # Send the placeholder message first
    try:
        sent = await bot.send_message(chat_id=chat_id, text=placeholder)
    except Exception as e:
        logger.error(f"[stream_reply] Failed to send placeholder: {e}")
        return placeholder

    msg_id = sent.message_id
    accumulated = ""
    last_edit = 0.0

    async for token in token_stream:
        accumulated += token
        now = time.monotonic()
        if now - last_edit >= min_edit_interval and accumulated.strip():
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text=accumulated,
                )
                last_edit = now
            except Exception as e:
                # Ignore "message not modified" errors (same content)
                if "message is not modified" not in str(e).lower():
                    logger.warning(f"[stream_reply] Edit failed: {e}")

    # Final edit with complete text
    if accumulated.strip() and accumulated != placeholder:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=accumulated,
            )
        except Exception:
            pass

    return accumulated


# ── Approval notification ─────────────────────────────────────────────────────
async def send_approval_request(bot, chat_id: int, message: str, approval_id: str):
    keyboard = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve:{approval_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject:{approval_id}"),
        ]
    ]
    markup = InlineKeyboardMarkup(keyboard)
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=message,
            reply_markup=markup,
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.warning(f"Failed to send approval request: {e}")


def is_conversational_chat(text: str) -> bool:
    """Detect if input is natural conversational chat vs a PC/system command."""
    t = text.lower().strip()

    # PC/system command keywords — route to planner instead
    pc_keywords = (
        "open", "launch", "start", "close", "quit", "kill",
        "search for folder", "search files", "rename",
        "volume", "brightness", "screenshot", "ocr",
        "sleep", "shutdown", "restart", "lock",
        "organize", "download", "cpu", "ram", "disk",
        "health", "processes", "network", "ping",
        "running", "apps running", "battery",
    )
    if any(k in t for k in pc_keywords):
        return False

    # Greetings
    greetings = (
        "hi", "hello", "hey", "good morning", "good evening",
        "good afternoon", "howdy", "yo", "namaste", "what's up", "sup", "hlo",
    )
    if t in greetings or any(t.startswith(g + " ") for g in greetings):
        return True

    # Casual / conversational phrases
    casual_phrases = (
        "how are you", "who are you", "what can you do", "what's your name",
        "tell me a joke", "tell me about", "tell me",
        "thank you", "thanks", "nice", "cool", "great", "ok", "okay", "bye",
        "what is", "what are", "explain", "why is", "why does",
        "how does", "how do", "who is", "where is",
    )
    if any(p in t for p in casual_phrases):
        return True

    # Question starters
    if t.startswith(("what ", "why ", "how ", "who ", "where ", "explain ", "tell me ", "can you ", "do you ")):
        return True

    # Short messages (≤ 3 words, no file path chars) are likely chat
    if len(t.split()) <= 3 and not any(c in t for c in ("\\", "/", ".", ":")):
        return True

    return False


# ── Helper: Execute tool subtasks and send results ────────────────────────────
async def _execute_subtasks(bot, chat_id, context, user, text, subtasks: list):
    """Execute a list of subtasks from keyword router or classifier directly."""
    planner = _get_planner()

    for subtask in subtasks:
        tool_name = subtask.get("tool", "")
        tool_input = subtask.get("tool_input", {})
        title = subtask.get("title", tool_name)

        tool_fn = planner.tool_registry.get(tool_name)
        if not tool_fn:
            logger.warning(f"[BOT] Unknown tool: {tool_name}")
            await send_progress(bot, chat_id, f"⚠️ Unknown tool: {tool_name}")
            continue

        # Check if approval is needed
        if subtask.get("requires_approval", False):
            async def notify_approval(uid, msg, aid):
                await send_approval_request(bot, chat_id, msg, aid)

            approved = await approval_center.request_approval(
                user_id=str(user.id),
                action_type=tool_name,
                details={"title": title, "tool_input": tool_input},
                notify_fn=notify_approval,
            )
            if not approved:
                await send_progress(bot, chat_id, f"🚫 {title} — rejected.")
                continue

        try:
            from app.agents.planner import _format_tool_result
            if tool_name == "open_url_in_browser" and "url" not in tool_input:
                tool_input["url"] = text

            if tool_name == "run_shell_command":
                from app.agents.self_healing_pipeline import self_healing_pipeline
                cmd = tool_input.get("command", "")
                project_dir = tool_input.get("cwd", "")
                await send_progress(bot, chat_id, f"⚙️ *Executing Task:* `{title}`\nRunning with Self-Healing Engine...")
                sh_res = await self_healing_pipeline.run(
                    command=cmd,
                    goal=text,
                    user_id=str(user.id),
                    project_dir=project_dir,
                    max_retries=3,
                )
                if sh_res["success"]:
                    repair_notes = ""
                    if sh_res.get("repairs_performed"):
                        reps = [f"• {r['action']} (Attempt {r['attempt']})" for r in sh_res["repairs_performed"]]
                        repair_notes = f"\n\n🔧 *Self-Healing Repairs:*\n" + "\n".join(reps)
                    out_text = sh_res.get("output", "").strip() or "Process executed with return code 0."
                    await send_progress(bot, chat_id, f"✅ *{title}*\n\n```\n{out_text[:1200]}\n```{repair_notes}")
                else:
                    err_text = (sh_res.get("error", "") or sh_res.get("output", "Execution failed")).strip()
                    diagnosis_notes = ""
                    if sh_res.get("repairs_performed"):
                        last_rep = sh_res["repairs_performed"][-1]
                        diag = last_rep.get("diagnosis", {})
                        diagnosis_notes = f"\n\n🔍 *Diagnosis:* {diag.get('category', '')}\n*Root Cause:* {diag.get('root_cause', '')}"
                    await send_progress(bot, chat_id, f"❌ *{title}*\n\n```\n{err_text[:1200]}\n```{diagnosis_notes}\n\n*Total Attempts:* {sh_res['attempts']}")
                continue


            fn_to_call = getattr(tool_fn, "func", tool_fn)
            raw_result = await asyncio.to_thread(fn_to_call, **tool_input)
            output = _format_tool_result(tool_name, raw_result)


            # Intercept missing desktop application error and present interactive options
            if tool_name == "open_application" and isinstance(raw_result, dict) and not raw_result.get("success", True) and "not found" in raw_result.get("error", "").lower():
                missing_app = tool_input.get("app_name", text)
                keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("🌐 Open in Chrome", callback_data=f"fallback_browser:{missing_app}"),
                        InlineKeyboardButton("🔍 Search Web", callback_data=f"fallback_search:{missing_app}"),
                    ],
                    [InlineKeyboardButton("❌ Cancel", callback_data="fallback_cancel")],
                ])
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"⚠️ *Application Not Found*\n\nCouldn't find desktop app *'{missing_app}'* installed on Windows.\n\nWould you like me to open it in Chrome browser instead?",
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                )
                continue

            logger.info(f"[BOT] ✅ {tool_name} → {output[:100]}")
            await send_progress(bot, chat_id, f"✅ {output}")


            # Send screenshot photo if applicable
            if "Screenshot captured:" in output:
                import re as _re, os as _os
                match = _re.search(r"Screenshot captured:\s*(.+\.png)", output)
                if match:
                    img_path = match.group(1).strip()
                    if _os.path.exists(img_path):
                        try:
                            with open(img_path, "rb") as photo_file:
                                await bot.send_photo(
                                    chat_id=chat_id, photo=photo_file,
                                    caption="📸 Captured Screenshot"
                                )
                        except Exception as pe:
                            logger.warning(f"Failed to send screenshot: {pe}")
        except Exception as e:
            logger.error(f"[BOT] Tool execution error ({tool_name}): {e}", exc_info=True)
            await send_progress(bot, chat_id, f"❌ {title} failed: {str(e)[:200]}")

    # Store to memory
    try:
        import json
        memory = _get_memory()
        subtasks_json = json.dumps(subtasks)
        await asyncio.to_thread(
            memory.store,
            document=f"Goal: {text}\nResult: executed {len(subtasks)} subtask(s)",
            metadata={"user_id": str(user.id), "goal": text, "subtasks_json": subtasks_json},
            user_id=str(user.id),
        )
    except Exception as me:
        logger.warning(f"[BOT] Failed to save memory: {me}")



# ── Message handler ───────────────────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not is_allowed(user.id):
        await update.message.reply_text("🚫 Access denied.")
        return

    chat_id = update.effective_chat.id
    text = (update.message.text or "").strip()
    if not text:
        return

    logger.info(f"[BOT] Message from {user.id}: '{text[:80]}'")
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    # ═══════════════════════════════════════════════════════════════════════════
    # EVENT-DRIVEN ARCHITECTURE (Redis Streams Event Bus)
    # ═══════════════════════════════════════════════════════════════════════════
    if getattr(settings, "EVENT_DRIVEN_MODE", False):
        try:
            import uuid
            from app.events.event_bus import event_bus
            from app.events.event_models import EventType, NexusEvent, TaskCreatedPayload
            from app.events.task_tracker import task_tracker

            task_id = f"task_{uuid.uuid4().hex[:8]}"
            await task_tracker.register_task(task_id, str(user.id), text)

            event = NexusEvent(
                event_type=EventType.TASK_CREATED,
                task_id=task_id,
                user_id=str(user.id),
                source_agent="telegram_bot",
                payload=TaskCreatedPayload(command=text, raw_text=text).model_dump(),
            )
            await event_bus.publish(event)
            await send_progress(context.bot, chat_id, f"⚡ *[Event Bus]* Dispatched task `{task_id}` to Redis Streams...\nCommand: `{text}`")

            # Wait for event-driven completion
            result = await task_tracker.wait_for_completion(task_id, timeout=getattr(settings, "TASK_COMPLETION_TIMEOUT", 60.0))
            if result.get("success"):
                out = result.get("final_output", "Task completed.")
                await send_progress(context.bot, chat_id, f"✅ *Task Completed*\n\n{out}")
            else:
                err = result.get("final_output", "Task failed.")
                await send_progress(context.bot, chat_id, f"❌ *Task Failed*\n\n{err}")
            return
        except Exception as eb_err:
            logger.error(f"[BOT] Event-driven handler failed: {eb_err}", exc_info=True)
            await send_progress(context.bot, chat_id, f"⚠️ Event bus error ({eb_err}), falling back to direct mode...")

    # ═══════════════════════════════════════════════════════════════════════════
    # STEP 0: ChromaDB Memory Fast Path — 0.05s Instant Semantic Recall
    # ═══════════════════════════════════════════════════════════════════════════
    try:
        memory = _get_memory()

        memories = await asyncio.to_thread(
            memory.search_memory,
            user_id=str(user.id),
            project_id="default",
            query=text,
            top_k=1
        )
        if memories and len(memories) > 0:
            top_mem = memories[0]
            dist = top_mem.distance
            doc = top_mem.text
            # Highly similar previous matching goal found
            if dist < 0.22 and "Result:" in doc:
                logger.info(f"[BOT] ⚡ CHROMADB MEMORY RECALL ({dist:.3f} distance) → Instant execution")
                
                # Retrieve stored subtasks from metadata
                subtasks_json = top_mem.metadata.get("subtasks_json", "")
                if subtasks_json:
                    import json
                    recalled_subtasks = json.loads(subtasks_json)
                    await send_progress(
                        context.bot, chat_id,
                        f"⚡ *ChromaDB Memory Fast Recall (0.05s)*\nExecuting recalled plan for: '{text}'"
                    )
                    await _execute_subtasks(context.bot, chat_id, context, user, text, recalled_subtasks)
                    return
    except Exception as e:
        logger.warning(f"[BOT] ChromaDB fast recall check: {e}")


    # ═══════════════════════════════════════════════════════════════════════════
    # STEP 1: Keyword Chat Check — instant, FREE, 0ms
    # "hi", "how are you", "what is python", "tell me a joke"
    # ═══════════════════════════════════════════════════════════════════════════

    if is_conversational_chat(text):
        logger.info(f"[BOT] ⚡ KEYWORD CHAT → Ollama stream")
        try:
            from app.agents.chat_agent import chat_agent
            final = await stream_reply(
                context.bot, chat_id,
                chat_agent.stream_response(text, user_name=user.first_name or "Charan"),
            )
            logger.info(f"[BOT] Stream complete: '{final[:60]}'")
        except Exception as e:
            logger.error(f"[BOT] Chat stream error: {e}", exc_info=True)
            await send_progress(context.bot, chat_id, f"Hey {user.first_name or 'there'}! How can I help you?")
        return

    # ═══════════════════════════════════════════════════════════════════════════
    # STEP 2: Keyword Command Router — instant, FREE, 0ms, no LLM needed
    # "open chrome", "check CPU", "lock PC", "set volume to 50"
    # ═══════════════════════════════════════════════════════════════════════════
    from app.agents.planner import IntentRouter
    fast_subtasks = IntentRouter.detect(text)
    if fast_subtasks is not None:
        logger.info(f"[BOT] ⚡ KEYWORD COMMAND → Direct execution ({len(fast_subtasks)} subtask(s), FREE)")
        await _execute_subtasks(context.bot, chat_id, context, user, text, fast_subtasks)
        return

    # ═══════════════════════════════════════════════════════════════════════════
    # STEP 3: Multi-Model Fast Router (Qwen3 1.7B) — intent classification
    # ═══════════════════════════════════════════════════════════════════════════
    try:
        from app.agents.grok_classifier import grok_classifier

        if grok_classifier.available:
            logger.info(f"[BOT] 🔍 FAST ROUTER (Qwen3 1.7B) CLASSIFY: '{text[:50]}'")
            classification = await grok_classifier.classify(text)
            intent = classification.get("intent", "unknown")
            logger.info(f"[BOT] Router intent: {intent}")

            if intent == "chat":
                logger.info(f"[BOT] Fast Router → Chat stream (Qwen3 1.7B)")
                try:
                    from app.agents.chat_agent import chat_agent
                    final = await stream_reply(
                        context.bot, chat_id,
                        chat_agent.stream_response(text, user_name=user.first_name or "Charan"),
                    )
                    logger.info(f"[BOT] Stream complete: '{final[:60]}'")
                except Exception as e:
                    logger.error(f"[BOT] Chat stream error: {e}", exc_info=True)
                    await send_progress(context.bot, chat_id, f"Hey {user.first_name or 'there'}! How can I help you?")
                return

            elif intent in ("simple_task", "command"):
                tool_name = classification.get("tool", "")
                tool_input = classification.get("tool_input", {})
                description = classification.get("description", text)
                logger.info(f"[BOT] Fast Router → Simple Task (Qwen3 1.7B): {tool_name}({tool_input})")

                # Multi-step visual/browser goals must NOT be handled as simple single-tool tasks.
                # Fall through to Step 4 LangGraph Orchestrator for full ActionPipeline loop.
                _multi_step_keywords = (
                    "play", "watch", "channel", "video", "click", "navigate", "type",
                    "search for", "go to", "go to youtube", "tell me when",
                    "and tell me", "and let me know", "and check", "and then",
                    "open chrome", "open browser",
                )
                _is_multi_step = (
                    any(w in text.lower() for w in _multi_step_keywords)
                    or text.lower().count(",") >= 2  # comma-separated multi-step
                    or ("search" in text.lower() and any(w in text.lower()
                        for w in ("youtube", "chrome", "browser", "go to")))
                )
                if _is_multi_step:
                    logger.info(f"[BOT] 🔄 Multi-step browser goal detected → falling through to LangGraph ActionPipeline")
                elif tool_name:
                    subtask = {
                        "tool": tool_name,
                        "tool_input": tool_input,
                        "title": description,
                        "requires_approval": False,
                    }
                    await _execute_subtasks(context.bot, chat_id, context, user, text, [subtask])
                    return


            elif intent == "vision_task":
                logger.info(f"[BOT] Fast Router → Vision Task (Gemma 3 4B)")
                await send_progress(context.bot, chat_id, "📸 Capturing screen and routing to Gemma 3 4B...")
                try:
                    from app.vision.screen_reader import screen_reader
                    screenshot_path = screen_reader.take_screenshot()
                    
                    if screenshot_path and os.path.exists(screenshot_path):
                        try:
                            with open(screenshot_path, "rb") as photo_file:
                                await context.bot.send_photo(
                                    chat_id=chat_id, photo=photo_file,
                                    caption="📸 Captured Desktop Screenshot"
                                )
                        except Exception as pe:
                            logger.warning(f"Failed to post photo to Telegram: {pe}")

                    from app.agents.chat_agent import chat_agent
                    final = await stream_reply(
                        context.bot, chat_id,
                        chat_agent.stream_vision_response(text, screenshot_path, user_name=user.first_name or "Charan"),
                    )
                    logger.info(f"[BOT] Vision analysis complete: '{final[:60]}'")
                except Exception as e:
                    logger.error(f"[BOT] Vision task error: {e}", exc_info=True)
                    await send_progress(context.bot, chat_id, f"❌ Vision Task Failed: {str(e)[:200]}")
                return

            elif intent == "coding_task":
                tool_name = classification.get("tool", "run_shell_command")
                tool_input = classification.get("tool_input", {"command": f"echo Running coding task: {text}"})
                description = classification.get("description", f"Coding task: {text}")
                logger.info(f"[BOT] Fast Router → Coding Task (Phi-4-mini): {tool_name}({tool_input})")

                subtask = {
                    "tool": tool_name,
                    "tool_input": tool_input,
                    "title": description,
                    "requires_approval": tool_name in ("run_shell_command", "delete_file"),
                }
                await _execute_subtasks(context.bot, chat_id, context, user, text, [subtask])
                return

            # intent == "complex_task" or "unknown" → fall through to Step 4 (Qwen3 4B Crew/Planner)
    except Exception as e:
        logger.warning(f"[BOT] Fast Router classifier error: {e}")


    # ═══════════════════════════════════════════════════════════════════════════
    # STEP 4: LangGraph StateGraph Orchestration Engine
    # Complex multi-step tasks requiring multi-agent team or security approval
    # ═══════════════════════════════════════════════════════════════════════════
    try:
        logger.info(f"[BOT] ⚙️ LANGGRAPH STATEGRAPH ORCHESTRATOR for: '{text[:60]}'")
        await send_progress(
            context.bot, chat_id,
            f"⚙️ *LangGraph Orchestrator Activated*\nRouting task through StateGraph nodes..."
        )

        from app.agents.langgraph_orchestrator import execute_nexus_graph
        graph_res = await execute_nexus_graph(text, user_id=str(user.id))

        final_output = graph_res.get("final_output", "✅ Executed via LangGraph.")
        await send_progress(context.bot, chat_id, final_output)

        # Send latest screenshot if available
        try:
            import os
            screenshot_path = "D:\\nexus_ai\\backend\\screenshots\\latest.png"
            if os.path.exists(screenshot_path):
                with open(screenshot_path, "rb") as photo_file:
                    await context.bot.send_photo(
                        chat_id=chat_id, photo=photo_file,
                        caption="📸 Computer Agent Visual Verification"
                    )
        except Exception as pe:
            logger.warning(f"[BOT] Failed to send photo: {pe}")

        return

    except Exception as e:
        logger.error(f"[BOT] LangGraph Orchestrator error: {e}", exc_info=True)
        await send_progress(context.bot, chat_id, f"❌ LangGraph Execution Error: {str(e)[:200]}")

        logger.error(f"Pipeline error for user {user.id}: {e}", exc_info=True)
        await send_progress(
            context.bot, chat_id,
            f"❌ *Pipeline Error*\n\nRoot cause: `{str(e)[:300]}`\n\nPlease try again.",
        )


# ── Approval & Fallback callback handler ─────────────────────────────────────────
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_allowed(query.from_user.id):
        await query.edit_message_text("🚫 Access denied.")
        return

    data = query.data or ""
    if data.startswith("fallback_"):
        parts = data.split(":", 1)
        fb_type = parts[0]
        app_target = parts[1] if len(parts) > 1 else ""

        if fb_type == "fallback_browser":
            from app.agents.tools.app_tools import open_url_in_browser
            fn_open = getattr(open_url_in_browser, "func", open_url_in_browser)
            res = fn_open(app_target if app_target.startswith("http") else f"https://www.google.com/search?q={app_target}", browser="chrome")
            await query.edit_message_text(f"🌐 *Opened {app_target} in Chrome Browser*\n{res.get('message', '')}", parse_mode="Markdown")
            try:
                memory = _get_memory()
                memory.store(document=f"Goal: open {app_target}\nResult: opened in chrome", metadata={"user_id": str(query.from_user.id), "goal": app_target})
            except Exception:
                pass
        elif fb_type == "fallback_search":
            from app.agents.tools.app_tools import open_url_in_browser
            fn_open = getattr(open_url_in_browser, "func", open_url_in_browser)
            res = fn_open(f"https://www.google.com/search?q={app_target}", browser="chrome")
            await query.edit_message_text(f"🔍 *Searched {app_target} on Google*\n{res.get('message', '')}", parse_mode="Markdown")
        elif fb_type == "fallback_cancel":
            await query.edit_message_text("❌ Action cancelled.")
        return

    if ":" not in data:
        return

    action, approval_id = data.split(":", 1)
    approved = action == "approve"
    approval_center.resolve_approval(approval_id, approved)

    status = "✅ Approved" if approved else "❌ Rejected"
    await query.edit_message_text(
        f"{status} — Approval ID: `{approval_id}`",
        parse_mode="Markdown",
    )



# ── Photo / Screenshot Upload Handler ─────────────────────────────────────────
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not is_allowed(user.id):
        await update.message.reply_text("🚫 Access denied.")
        return

    chat_id = update.effective_chat.id
    caption = (update.message.caption or "").strip()
    logger.info(f"[BOT] Photo received from {user.id} with caption: '{caption[:80]}'")
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    os.makedirs("screenshots", exist_ok=True)
    temp_img_path = os.path.join("screenshots", f"upload_{int(time.time())}.png")

    try:
        # Download the highest resolution photo
        photo = update.message.photo[-1]
        file_obj = await photo.get_file()
        await file_obj.download_to_drive(custom_path=temp_img_path)
        logger.info(f"[BOT] Photo saved to {temp_img_path}")

        # ── Step 1: OCR Text Extraction ──
        extracted_text = ""
        try:
            from app.vision.screen_reader import screen_reader, TESSERACT_PATH
            from PIL import Image, ImageOps, ImageEnhance
            import pytesseract

            for p in [TESSERACT_PATH, r"C:\Program Files\Tesseract-OCR\tesseract.exe", r"C:\Users\chara_qmka15y\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"]:
                if os.path.exists(p):
                    pytesseract.pytesseract.tesseract_cmd = p
                    break

            with Image.open(temp_img_path) as img:
                # Pass 1: Standard OCR
                t1 = pytesseract.image_to_string(img)
                # Pass 2: High-contrast inverted grayscale (fixes dark mode missed lines)
                gray = ImageOps.grayscale(img)
                inverted = ImageOps.invert(gray)
                enhanced = ImageEnhance.Contrast(inverted).enhance(2.5)
                t2 = pytesseract.image_to_string(enhanced)
                extracted_text = f"{t1}\n{t2}"
        except Exception as ocr_err:
            logger.warning(f"[BOT] OCR extraction error: {ocr_err}")

        combined_prompt = f"{caption}\n\n[Extracted Text from Image]:\n{extracted_text}".strip()
        logger.info(f"[BOT] Extracted text from uploaded image: {extracted_text[:120]}")

        # ── Step 2: Check if this is a LeetCode / Coding Problem Solve Request ──
        lower_caption = caption.lower()
        if any(w in lower_caption for w in ("solve", "leetcode", "code", "problem", "solution", "answer")) or "leetcode" in extracted_text.lower():
            from app.agents.leetcode_agent import leetcode_agent
            await leetcode_agent.load_problem_registry()
            problems = leetcode_agent.extract_problems_from_text(extracted_text, caption=caption)

            if problems:

                await send_progress(
                    context.bot, chat_id,
                    f"🎯 *LeetCode Autonomous Solver Active*\nDetected *{len(problems)} problem(s)* from request.\nNavigating to each page, filling the code, submitting, and progressing..."
                )


                for idx, prob in enumerate(problems, 1):
                    p_title = prob["title"]
                    p_num = prob["number"]
                    await send_progress(
                        context.bot, chat_id,
                        f"⏳ *[{idx}/{len(problems)}] Solving #{p_num} {p_title}...*\nOpening page in Chrome, pasting solution into editor & submitting..."
                    )

                    res = await leetcode_agent.fill_and_submit_on_screen(prob)
                    if res.get("success"):
                        await send_progress(
                            context.bot, chat_id,
                            f"✅ *[{idx}/{len(problems)}] Submitted #{p_num} {p_title}*\nURL: `{res.get('url')}`\n\nMoving to next problem..."
                        )
                    else:
                        await send_progress(
                            context.bot, chat_id,
                            f"⚠️ *[{idx}/{len(problems)}] #{p_num} {p_title} note:* {res.get('error', 'Execution note')}\nURL: `{res.get('url')}`"
                        )

                    await asyncio.sleep(2.0)

                await send_progress(
                    context.bot, chat_id,
                    f"🎉 *LeetCode Batch Completed!* Finished submitting all {len(problems)} problem(s)."
                )
                return


            # Fallback to LLM chat stream
            await send_progress(context.bot, chat_id, "🔍 *Analyzing image content...*")
            from app.agents.chat_agent import chat_agent
            await stream_reply(
                context.bot, chat_id,
                chat_agent.stream_response(combined_prompt, user_name=user.first_name or "Charan"),
            )
            return


        # ── Step 3: General Vision Request (Gemma 3 Vision) ──
        from app.agents.chat_agent import chat_agent
        await stream_reply(
            context.bot, chat_id,
            chat_agent.stream_vision_response(caption or "What is in this image?", temp_img_path, user_name=user.first_name or "Charan"),
        )

    except Exception as e:
        logger.error(f"[BOT] Photo processing error: {e}", exc_info=True)
        await send_progress(context.bot, chat_id, f"❌ Failed to process uploaded image: {str(e)[:200]}")


# ── Voice Note Handler ────────────────────────────────────────────────────────
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles incoming voice notes and audio clips from Telegram."""
    user = update.effective_user
    if not user or not is_allowed(user.id):
        await update.message.reply_text("🚫 Access denied.")
        return

    chat_id = update.effective_chat.id
    voice = update.message.voice or update.message.audio
    if not voice:
        return

    await context.bot.send_chat_action(chat_id=chat_id, action="record_voice")

    temp_audio = tempfile.mktemp(suffix=".oga")
    try:
        new_file = await voice.get_file()
        await new_file.download_to_drive(custom_path=temp_audio)

        # Transcribe voice audio
        from app.voice.transcriber import transcriber
        trans_res = await transcriber.transcribe_file(temp_audio)

        if not trans_res.get("success"):
            err = trans_res.get("error", "Could not understand audio")
            await send_progress(context.bot, chat_id, f"⚠️ *Voice Transcription Failed*\n{err}")
            return

        spoken_text = trans_res.get("text", "").strip()
        logger.info(f"[BOT] Transcribed Telegram voice note from {user.id}: '{spoken_text}'")

        await send_progress(
            context.bot, chat_id,
            f"🎙️ *Heard Voice Command:*\n`\"{spoken_text}\"`\n\nExecuting..."
        )

        # Inject transcribed text into message and forward through full execution pipeline
        update.message.text = spoken_text
        await handle_message(update, context)

    except Exception as e:
        logger.error(f"[BOT] Voice handling error: {e}", exc_info=True)
        await send_progress(context.bot, chat_id, f"❌ Failed to process voice note: {str(e)[:200]}")
    finally:
        if os.path.exists(temp_audio):
            try:
                os.remove(temp_audio)
            except Exception:
                pass


# ── Bot builder ───────────────────────────────────────────────────────────────
def build_telegram_app(token: str) -> Application:
    app = Application.builder().token(token).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    app.add_handler(CallbackQueryHandler(handle_callback))
    return app


