"""Quick verification script to test OpenRouter configuration and integration."""
from app.config import settings

def verify_config():
    print("Nexus AI — OpenRouter Settings:")
    print(f"  OPENROUTER_API_KEY: {bool(settings.OPENROUTER_API_KEY)} (Length: {len(settings.OPENROUTER_API_KEY)})")
    print(f"  OPENROUTER_MODEL: {settings.OPENROUTER_MODEL}")
    
    # Try importing new packages to confirm no installation issues
    try:
        from langchain_openai import ChatOpenAI
        print("✅ langchain-openai imported successfully!")
    except Exception as e:
        print(f"❌ Failed to import langchain-openai: {e}")

if __name__ == "__main__":
    verify_config()
