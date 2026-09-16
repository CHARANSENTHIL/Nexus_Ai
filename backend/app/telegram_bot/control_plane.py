"""
Telegram Agent Control Plane — Real-time visual progress cards, debounced live updates,
and interactive control buttons (Pause, Resume, Cancel, Inspect Plan, Retry).
"""
import time
import asyncio
import logging
from typing import Dict, Any, Optional, List
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from app.runtime.task_models import TaskState, TaskRecord
from app.runtime.task_state_machine import task_state_machine

logger = logging.getLogger(__name__)


class TaskCardRenderer:
    """Renders visual progress bars, task metrics, and interactive control buttons."""

    @staticmethod
    def render_progress_bar(completed: int, total: int, length: int = 10) -> str:
        if total <= 0:
            return "[" + "░" * length + "] 0%"
        pct = min(1.0, max(0.0, completed / total))
        filled = int(round(length * pct))
        bar = "█" * filled + "░" * (length - filled)
        return f"[{bar}] {int(pct * 100)}%"

    @classmethod
    def format_task_card(cls, task: TaskRecord, current_action: str = "") -> str:
        state_emojis = {
            TaskState.CREATED: "🆕",
            TaskState.PLANNING: "🧠",
            TaskState.AWAITING_APPROVAL: "⚠️",
            TaskState.EXECUTING: "⚙️",
            TaskState.VERIFYING: "🔍",
            TaskState.WAITING_FOR_HUMAN: "🔐",
            TaskState.HUMAN_COMPLETED: "✅",
            TaskState.RETRYING: "🔧",
            TaskState.COMPLETED: "🎉",
            TaskState.FAILED: "❌",
            TaskState.CANCELLED: "🛑",
            TaskState.PAUSED: "⏸️",
        }
        emoji = state_emojis.get(task.state, "⚡")
        progress_bar = cls.render_progress_bar(task.completed_steps_count, task.total_steps)

        curr_step_text = current_action or (
            task.subtasks[task.current_subtask_index].title
            if task.subtasks and task.current_subtask_index < len(task.subtasks)
            else "Initializing..."
        )

        duration = round(time.time() - task.created_at, 1)

        msg = (
            f"⚡ *NEXUS RUNTIME — TASK #{task.task_id[:8]}*\n\n"
            f"🎯 *Goal*: `{task.goal[:120]}`\n"
            f"{emoji} *State*: `{task.state.value}`\n"
            f"📈 *Progress*: `{progress_bar}` ({task.completed_steps_count}/{task.total_steps} steps)\n"
            f"📍 *Current*: _{curr_step_text[:80]}_\n\n"
            f"⏱️ *Duration*: `{duration}s`"
        )
        if task.error_summary:
            msg += f"\n⚠️ *Error*: `{task.error_summary[:150]}`"
        if task.final_output and task.state == TaskState.COMPLETED:
            msg += f"\n\n✅ *Result*: {task.final_output[:300]}"

        return msg

    @staticmethod
    def build_control_keyboard(task: TaskRecord) -> Optional[InlineKeyboardMarkup]:
        buttons = []
        tid = task.task_id

        if task.state == TaskState.EXECUTING or task.state == TaskState.PLANNING:
            buttons.append([
                InlineKeyboardButton("⏸ Pause", callback_data=f"task_pause:{tid}"),
                InlineKeyboardButton("⛔ Cancel", callback_data=f"task_cancel:{tid}"),
                InlineKeyboardButton("🔍 Inspect", callback_data=f"task_inspect:{tid}"),
            ])
        elif task.state == TaskState.PAUSED:
            buttons.append([
                InlineKeyboardButton("▶ Resume", callback_data=f"task_resume:{tid}"),
                InlineKeyboardButton("⛔ Cancel", callback_data=f"task_cancel:{tid}"),
                InlineKeyboardButton("🔍 Inspect", callback_data=f"task_inspect:{tid}"),
            ])
        elif task.state in (TaskState.FAILED, TaskState.CANCELLED):
            buttons.append([
                InlineKeyboardButton("↩ Retry", callback_data=f"task_retry:{tid}"),
                InlineKeyboardButton("🔍 Inspect Plan", callback_data=f"task_inspect:{tid}"),
            ])
        elif task.state == TaskState.COMPLETED:
            buttons.append([
                InlineKeyboardButton("🔍 Inspect Plan", callback_data=f"task_inspect:{tid}"),
            ])

        return InlineKeyboardMarkup(buttons) if buttons else None


class ControlPlaneManager:
    """
    Manages active task cards on Telegram with rate-limited debouncing.
    """

    def __init__(self):
        # task_id -> {"chat_id": int, "message_id": int, "last_edit_time": float, "pending_text": str}
        self._active_cards: Dict[str, Dict[str, Any]] = {}
        self._edit_locks: Dict[str, asyncio.Lock] = {}

    async def register_task_card(self, bot, chat_id: int, task: TaskRecord) -> int:
        """Sends initial task card message and stores message ID."""
        text = TaskCardRenderer.format_task_card(task)
        keyboard = TaskCardRenderer.build_control_keyboard(task)
        try:
            msg = await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            self._active_cards[task.task_id] = {
                "chat_id": chat_id,
                "message_id": msg.message_id,
                "last_edit_time": time.time(),
                "bot": bot,
            }
            self._edit_locks[task.task_id] = asyncio.Lock()
            return msg.message_id
        except Exception as e:
            logger.warning(f"[ControlPlane] Failed to send initial task card: {e}")
            return 0

    async def update_task_card(self, task: TaskRecord, current_action: str = ""):
        """Updates existing task card with debounced Telegram edits."""
        card_info = self._active_cards.get(task.task_id)
        if not card_info:
            return

        now = time.time()
        # Enforce 1.2 second debounce to respect Telegram rate limits unless task reached final state
        is_final = task.state in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED, TaskState.PAUSED)
        if not is_final and (now - card_info["last_edit_time"] < 1.2):
            return

        card_info["last_edit_time"] = now
        text = TaskCardRenderer.format_task_card(task, current_action=current_action)
        keyboard = TaskCardRenderer.build_control_keyboard(task)

        bot = card_info["bot"]
        chat_id = card_info["chat_id"]
        msg_id = card_info["message_id"]

        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
        except Exception as e:
            logger.debug(f"[ControlPlane] Edit message note (duplicate/rate): {e}")

    async def handle_control_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """
        Handles interactive control callbacks (task_pause, task_resume, task_cancel, task_inspect).
        Returns True if handled.
        """
        query = update.callback_query
        if not query or not query.data:
            return False

        data = query.data
        if not any(data.startswith(p) for p in ("task_pause:", "task_resume:", "task_cancel:", "task_inspect:", "task_retry:")):
            return False

        await query.answer()
        action, task_id = data.split(":", 1)
        task = task_state_machine.get_task(task_id)

        if not task:
            await query.edit_message_text(f"{query.message.text}\n\n⚠️ *Task not found.*", parse_mode="Markdown")
            return True

        if action == "task_pause":
            task_state_machine.pause_task(task_id)
            task = task_state_machine.get_task(task_id)
            await self.update_task_card(task, current_action="Paused by user.")

        elif action == "task_resume":
            task_state_machine.resume_task(task_id)
            task = task_state_machine.get_task(task_id)
            await self.update_task_card(task, current_action="Resuming execution...")

        elif action == "task_cancel":
            task_state_machine.cancel_task(task_id)
            task = task_state_machine.get_task(task_id)
            await self.update_task_card(task, current_action="Cancelled by user.")

        elif action == "task_inspect":
            # Render detailed subtask graph
            subtask_lines = []
            for idx, st in enumerate(task.subtasks):
                st_status = "✅" if st.state == TaskState.COMPLETED else ("⚙️" if st.state == TaskState.EXECUTING else "⏳")
                subtask_lines.append(f"{idx+1}. {st_status} *{st.title}* (`{st.tool_name}`)")

            plan_text = "\n".join(subtask_lines) if subtask_lines else "No subtasks defined."
            inspect_msg = (
                f"📋 *TASK GRAPH INSPECT — #{task_id[:8]}*\n\n"
                f"🎯 *Goal*: {task.goal}\n\n"
                f"*Execution Plan*:\n{plan_text}\n\n"
                f"💡 _Total: {task.total_steps} steps | Completed: {task.completed_steps_count}_"
            )
            await query.message.reply_text(inspect_msg, parse_mode="Markdown")

        return True


# Singleton instance
control_plane = ControlPlaneManager()
