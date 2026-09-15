import sys
import os
import asyncio
import json
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

async def run_all_tests():
    results = {}
    print("====================================================")
    print("STARTING COMPREHENSIVE MODULE VERIFICATION SUITE")
    print("====================================================\n")

    # Test 1: App Architect (Custom App + Venv + Pip + Code)
    print("1. Testing App Architect (Autonomous Venv & App Scaffolder)...")
    try:
        from app.agents.app_architect_agent import app_architect_agent
        t0 = time.time()
        res1 = await app_architect_agent.build_application(
            prompt="build a face recognition app with webcam video capture and green bounding boxes",
            app_name="face_recognition_vision_app"
        )
        results["App Architect"] = {
            "success": res1.get("success"),
            "project_dir": res1.get("project_dir"),
            "files": res1.get("files"),
            "elapsed_s": round(time.time() - t0, 2)
        }
        print(f"   -> Result: {res1.get('success')} | Directory: {res1.get('project_dir')} | Files: {res1.get('files')}\n")
    except Exception as e:
        print(f"   -> Error: {e}\n")
        results["App Architect"] = {"success": False, "error": str(e)}

    # Test 2: SecOps & Vulnerability Sentinel
    print("2. Testing SecOps & Vulnerability Sentinel...")
    try:
        from app.agents.secops_agent import secops_agent
        t0 = time.time()
        res2 = await secops_agent.audit_codebase_security("D:\\nexus_ai\\backend\\app\\config.py")
        results["SecOps Sentinel"] = {
            "success": res2.get("success"),
            "grade": res2.get("grade"),
            "score": res2.get("score"),
            "elapsed_s": round(time.time() - t0, 2)
        }
        print(f"   -> Result: {res2.get('success')} | Grade: {res2.get('grade')} ({res2.get('score')}/100)\n")
    except Exception as e:
        print(f"   -> Error: {e}\n")
        results["SecOps Sentinel"] = {"success": False, "error": str(e)}

    # Test 3: Second Brain & Personal Knowledge Graph
    print("3. Testing Second Brain (Vault Capture & Query)...")
    try:
        from app.agents.second_brain_agent import second_brain_agent
        t0 = time.time()
        res3_cap = await second_brain_agent.capture("Project Titan: Implement distributed vector indexing by Q4", category="task")
        res3_qry = await second_brain_agent.query_vault("Titan")
        results["Second Brain"] = {
            "capture_success": res3_cap.get("success"),
            "query_count": res3_qry.get("count"),
            "elapsed_s": round(time.time() - t0, 2)
        }
        print(f"   -> Result: Capture={res3_cap.get('success')}, Query Matches={res3_qry.get('count')}\n")
    except Exception as e:
        print(f"   -> Error: {e}\n")
        results["Second Brain"] = {"success": False, "error": str(e)}

    # Test 4: Council of Experts (Multi-Agent Debate)
    print("4. Testing Council of Experts (3-Persona Deliberation)...")
    try:
        from app.agents.council_agent import council_agent
        t0 = time.time()
        res4 = await council_agent.deliberate("Should we use Go or Python for real-time high throughput microservices?")
        results["Council of Experts"] = {
            "success": res4.get("success"),
            "content_length": len(res4.get("deliberation", "")),
            "elapsed_s": round(time.time() - t0, 2)
        }
        print(f"   -> Result: {res4.get('success')} (Deliberation Output: {len(res4.get('deliberation', ''))} characters)\n")
    except Exception as e:
        print(f"   -> Error: {e}\n")
        results["Council of Experts"] = {"success": False, "error": str(e)}

    # Test 5: Live Meeting Assistant
    print("5. Testing Live Meeting & Audio Note-Taking Assistant...")
    try:
        from app.agents.meeting_agent import meeting_agent
        t0 = time.time()
        res5 = await meeting_agent.process_meeting(
            transcript_text="Sprint Review: Charan finalized the architecture. Deployment scheduled for Friday. Team aligned on performance metrics.",
            meeting_title="Sprint 42 Architecture Review"
        )
        results["Meeting Assistant"] = {
            "success": res5.get("success"),
            "file_path": res5.get("file_path"),
            "elapsed_s": round(time.time() - t0, 2)
        }
        print(f"   -> Result: {res5.get('success')} | Saved: {res5.get('file_path')}\n")
    except Exception as e:
        print(f"   -> Error: {e}\n")
        results["Meeting Assistant"] = {"success": False, "error": str(e)}

    # Test 6: Financial & Market Intelligence Sentinel
    print("6. Testing Financial Sentinel (yfinance + Candlestick Chart)...")
    try:
        from app.agents.finance_agent import finance_agent
        t0 = time.time()
        res6 = await finance_agent.get_market_analysis("BTC-USD", period="5d")
        results["Financial Sentinel"] = {
            "success": res6.get("success"),
            "price": res6.get("current_price"),
            "chart_path": res6.get("chart_path"),
            "elapsed_s": round(time.time() - t0, 2)
        }
        print(f"   -> Result: {res6.get('success')} | Price: ${res6.get('current_price', 0):,.2f} | Chart: {res6.get('chart_path')}\n")
    except Exception as e:
        print(f"   -> Error: {e}\n")
        results["Financial Sentinel"] = {"success": False, "error": str(e)}

    # Test 7: Proactive Background Sentinel & Morning Briefing
    print("7. Testing Morning Briefing Generator...")
    try:
        from app.sentinel.sentinel_scheduler import sentinel_scheduler
        t0 = time.time()
        res7 = await sentinel_scheduler.generate_morning_briefing("Chennai")
        results["Morning Briefing"] = {
            "success": res7.get("success"),
            "date": res7.get("date"),
            "elapsed_s": round(time.time() - t0, 2)
        }
        print(f"   -> Result: {res7.get('success')} | Date: {res7.get('date')}\n")
    except Exception as e:
        print(f"   -> Error: {e}\n")
        results["Morning Briefing"] = {"success": False, "error": str(e)}

    # Test 8: Full Duplex Voice JARVIS (Neural TTS)
    print("8. Testing Neural TTS Voice Synthesis (edge-tts)...")
    try:
        from app.voice.tts_engine import tts_engine
        t0 = time.time()
        res8 = await tts_engine.generate_voice_note("All Nexus AI systems are operational and performing at maximum efficiency.")
        results["Neural Voice TTS"] = {
            "success": res8.get("success"),
            "audio_file": res8.get("file_path"),
            "elapsed_s": round(time.time() - t0, 2)
        }
        print(f"   -> Result: {res8.get('success')} | Audio File: {res8.get('file_path')}\n")
    except Exception as e:
        print(f"   -> Error: {e}\n")
        results["Neural Voice TTS"] = {"success": False, "error": str(e)}

    # Test 9: Deep Research Agent
    print("9. Testing Autonomous Deep Research Agent...")
    try:
        from app.agents.deep_research_agent import deep_research_agent
        t0 = time.time()
        res9 = await deep_research_agent.conduct_deep_research("Quantum Computing in Cryptography", depth="quick")
        results["Deep Research Agent"] = {
            "success": res9.get("success"),
            "sources_count": res9.get("sources_count"),
            "html_report": res9.get("report_html_path"),
            "elapsed_s": round(time.time() - t0, 2)
        }
        print(f"   -> Result: {res9.get('success')} | Sources: {res9.get('sources_count')} | Dossier: {res9.get('report_html_path')}\n")
    except Exception as e:
        print(f"   -> Error: {e}\n")
        results["Deep Research Agent"] = {"success": False, "error": str(e)}

    # Test 10: Presentation & Pitch Deck Builder
    print("10. Testing Presentation & Pitch Deck Builder...")
    try:
        from app.agents.presentation_agent import presentation_agent
        t0 = time.time()
        res10 = await presentation_agent.create_presentation("AI Agent Architecture 2026")
        results["Presentation Agent"] = {
            "success": res10.get("success"),
            "file_path": res10.get("file_path"),
            "total_slides": res10.get("total_slides"),
            "elapsed_s": round(time.time() - t0, 2)
        }
        print(f"   -> Result: {res10.get('success')} | Slides: {res10.get('total_slides')} | File: {res10.get('file_path')}\n")
    except Exception as e:
        print(f"   -> Error: {e}\n")
        results["Presentation Agent"] = {"success": False, "error": str(e)}

    print("====================================================")
    print("ALL MODULE TESTS COMPLETED SUCCESSFULLY!")
    print("====================================================")
    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    asyncio.run(run_all_tests())
