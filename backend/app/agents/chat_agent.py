"""Chat Agent — Llama 3 powered conversational AI chatbot module."""
import logging
from typing import AsyncGenerator
import httpx
import json
from app.config import settings

logger = logging.getLogger(__name__)


class ChatAgent:
    """Conversational AI Agent with multi-turn conversation memory & ChromaDB semantic recall."""

    def __init__(self):
        self.ollama_url = None
        self.model = getattr(settings, 'OLLAMA_SIMPLE_MODEL', 'qwen3:1.7b')
        self.history_buffers = {}  # user_name -> list of {"role": str, "content": str}
        self.max_history_length = 10  # Last 10 turns (5 user, 5 assistant)

        try:
            get_url = getattr(settings, "get_ollama_url", None)
            self.ollama_url = get_url() if callable(get_url) else "http://localhost:11434"
        except Exception as e:
            logger.warning(f"Failed to resolve Ollama URL: {e}")
            self.ollama_url = "http://localhost:11434"

    def _get_user_history(self, user_name: str) -> list:
        if user_name not in self.history_buffers:
            self.history_buffers[user_name] = []
        return self.history_buffers[user_name]

    def _append_to_history(self, user_name: str, role: str, content: str):
        buf = self._get_user_history(user_name)
        buf.append({"role": role, "content": content})
        if len(buf) > self.max_history_length:
            self.history_buffers[user_name] = buf[-self.max_history_length:]

    def _get_relevant_memories(self, prompt: str, user_name: str) -> str:
        """Retrieve relevant semantic memories from ChromaDB."""
        try:
            from app.memory.chroma_store import memory_store
            memories = memory_store.retrieve(query=prompt, n_results=2, user_id=user_name)
            if memories:
                lines = [f"- {m['document']}" for m in memories if m.get("document")]
                if lines:
                    return "\nRelevant past memories for " + user_name + ":\n" + "\n".join(lines)
        except Exception as e:
            logger.warning(f"[ChatAgent] Memory retrieval error: {e}")
        return ""

    def _build_system_prompt(self, user_name: str, memory_context: str) -> str:
        return (
            f"You are Nexus AI, an intelligent, friendly, and natural AI assistant created for {user_name}.\n"
            "Respond in a natural, warm, conversational, and helpful manner — like a real intelligent companion.\n"
            "Keep your responses concise, engaging, and friendly."
            f"{memory_context}"
        )

    def _build_prompt(self, prompt: str, user_name: str, memory_context: str = "") -> str:
        history = self._get_user_history(user_name)
        hist_str = ""
        if history:
            hist_str = "\n".join([f"{h['role'].capitalize()}: {h['content']}" for h in history[-6:]]) + "\n"

        return (
            f"You are Nexus AI, an intelligent, friendly, and natural AI assistant created for {user_name}.\n"
            "Respond in a natural, warm, conversational, and helpful manner.\n"
            f"{memory_context}\n\n"
            f"Recent Conversation:\n{hist_str}"
            f"User: {prompt}\n"
            "Nexus AI:"
        )

    async def stream_response(self, prompt: str, user_name: str = "Charan") -> AsyncGenerator[str, None]:
        """
        Stream response tokens one-by-one with full conversational memory.
        Uses local Ollama /api/generate endpoint.
        """
        logger.info("[ChatAgent] Routing conversational chat to local Ollama (with memory)")
        memory_context = self._get_relevant_memories(prompt, user_name)
        full_prompt = self._build_prompt(prompt, user_name, memory_context)
        payload = {
            "model": self.model,
            "prompt": full_prompt,
            "stream": True,
            "options": {"temperature": 0.7},
        }

        full_reply = ""
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=15.0, read=120.0, write=10.0, pool=5.0)
            ) as client:
                async with client.stream(
                    "POST",
                    f"{self.ollama_url}/api/generate",
                    json=payload,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                            token = data.get("response", "")
                            if token:
                                full_reply += token
                                yield token
                            if data.get("done"):
                                break
                        except json.JSONDecodeError:
                            continue

            if full_reply.strip():
                self._append_to_history(user_name, "user", prompt)
                self._append_to_history(user_name, "assistant", full_reply)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            logger.warning(f"[ChatAgent] Ollama not reachable at {self.ollama_url} — yielding offline message")
            yield f"⚠️ Ollama is offline right now. Start it with: `ollama serve`\n\nOnce it's running, ask me again and I'll answer properly!"
        except Exception as e:
            logger.error(f"[ChatAgent] Stream error: {e}")
            yield self._fallback(prompt, user_name)

    async def generate_response(self, prompt: str, user_name: str = "Charan") -> str:
        """Generate full response (non-streaming) — used as fallback."""
        full_text = ""
        try:
            async for token in self.stream_response(prompt, user_name):
                full_text += token
            return full_text.strip() or f"Hey {user_name}! I'm here and ready to help."
        except Exception as e:
            logger.error(f"ChatAgent generation error: {e}")
            return self._fallback(prompt, user_name)

    async def stream_vision_response(self, prompt: str, screenshot_path: str, user_name: str = "Charan") -> AsyncGenerator[str, None]:
        """Stream vision-based response from local Ollama (multimodal) using Gemma 3 4B."""
        import base64
        
        vision_model = getattr(settings, "OLLAMA_VISION_MODEL", "gemma3:4b")
        img_b64 = ""
        if screenshot_path:
            try:
                with open(screenshot_path, "rb") as image_file:
                    img_b64 = base64.b64encode(image_file.read()).decode("utf-8")
            except Exception as e:
                logger.error(f"[ChatAgent] Failed to read screenshot file '{screenshot_path}': {e}")

        logger.info(f"[ChatAgent] Routing vision task to local Ollama ({vision_model})")
        payload = {
            "model": vision_model,
            "prompt": prompt or "Describe what is on this screen in detail.",
            "stream": True,
            "options": {"temperature": 0.2},
        }
        if img_b64:
            payload["images"] = [img_b64]

        full_reply = ""
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=15.0, read=120.0, write=10.0, pool=5.0)
            ) as client:
                async with client.stream(
                    "POST",
                    f"{self.ollama_url}/api/generate",
                    json=payload,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                            token = data.get("response", "")
                            if token:
                                full_reply += token
                                yield token
                            if data.get("done"):
                                break
                        except json.JSONDecodeError:
                            continue

            if full_reply.strip():
                self._append_to_history(user_name, "user", prompt)
                self._append_to_history(user_name, "assistant", full_reply)
        except Exception as e:
            logger.error(f"[ChatAgent] Vision stream error: {e}")
            yield f"⚠️ Vision Model Error: {str(e)}"

    def _fallback(self, prompt: str, user_name: str) -> str:
        t = prompt.lower().strip()
        if any(g in t for g in ("hi", "hello", "hey", "hlo", "namaste")):
            return f"Hey {user_name}! 👋 Great to see you. How can I help you today?"
        elif "how are you" in t:
            return f"I'm doing great, {user_name}! Ready to help you with your PC or answer any questions."
        elif "who are you" in t:
            return "I'm Nexus AI — your personal intelligent desktop AI assistant!"
        else:
            return f"I'm here for you, {user_name}! What would you like to do?"


chat_agent = ChatAgent()




