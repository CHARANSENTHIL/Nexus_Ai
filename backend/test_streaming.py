"""Quick end-to-end test: verifies Ollama streaming works token by token."""
import asyncio
from app.agents.chat_agent import chat_agent

async def main():
    print("Streaming test: 'tell me about F1'")
    print("-" * 40)
    token_count = 0
    async for token in chat_agent.stream_response("tell me about F1 in 2 sentences", user_name="Charan"):
        print(token, end="", flush=True)
        token_count += 1
    print(f"\n\n[Done] {token_count} tokens streamed.")

asyncio.run(main())
