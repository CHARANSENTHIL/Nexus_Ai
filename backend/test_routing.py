from app.telegram_bot.bot import is_conversational_chat

tests = [
    ("tell me about F1", True),
    ("hello", True),
    ("how does python work", True),
    ("open chrome", False),
    ("check my cpu", False),
    ("what is machine learning", True),
    ("take a screenshot", False),
    ("why is the sky blue", True),
    ("hi how are you", True),
    ("set volume to 50", False),
]

all_ok = True
for msg, expected in tests:
    result = is_conversational_chat(msg)
    status = "OK" if result == expected else "FAIL"
    if result != expected:
        all_ok = False
    print(f"[{status}] \"{msg}\" -> {result} (expected {expected})")

print("\nAll OK!" if all_ok else "\nSOME FAILURES!")
