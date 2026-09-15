"""
Intelligent Email Workflow Agent for Nexus AI.
Coordinates local file discovery, Git context extraction, LLM email composition,
security approval checks, and n8n Gmail / SMTP dispatch.
"""
import os
import re
import glob
import json
import logging
import asyncio
import subprocess
import time
from datetime import datetime
from typing import Dict, Any, List, Optional
import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class IntelligentEmailAgent:
    """Agent that prepares intelligent context-aware emails and dispatches them via n8n."""

    def __init__(self):
        self.n8n_url = getattr(settings, "N8N_URL", "http://localhost:5678")

    def find_local_attachments(self, query: str, search_roots: Optional[List[str]] = None) -> List[str]:
        """
        Scans Downloads, Documents, and project directories for files matching query keywords.
        Only attaches images if images/photos are specifically mentioned in the request.
        """
        STOP_WORDS = {
            "the", "and", "for", "with", "from", "that", "this", "search", "download", "image",
            "images", "photo", "photos", "picture", "pictures", "file", "files", "send", "email",
            "mail", "please", "can", "you", "nexus", "attach", "attachment", "attachments", "report",
            "presentation", "document", "documents", "project", "gmail", "com", "make", "create",
            "topic", "about"
        }

        query_lower = query.lower()
        is_image_req = any(w in query_lower for w in ("image", "images", "photo", "photos", "picture", "pictures", "wallpaper"))
        is_presentation_req = any(w in query_lower for w in ("ppt", "pptx", "presentation", "slides", "powerpoint"))

        # 1. If images are specifically requested, look in ~/Downloads/nexus_images
        if is_image_req:
            nexus_images_dir = os.path.expanduser("~/Downloads/nexus_images")
            if os.path.exists(nexus_images_dir):
                recent_images = []
                for root, _, files in os.walk(nexus_images_dir):
                    for f in files:
                        fp = os.path.join(root, f)
                        if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
                            recent_images.append(fp)
                if recent_images:
                    recent_images.sort(key=lambda x: os.path.getmtime(x), reverse=True)
                    return recent_images[:4]

        # 2. General targeted file search
        keywords = [
            k.lower() for k in re.findall(r"[a-zA-Z0-9_\-]+", query)
            if len(k) >= 3 and k.lower() not in STOP_WORDS
        ]

        # Allowed extensions depending on request
        if is_presentation_req:
            target_exts = (".pptx", ".ppt", ".pdf", ".html")
        elif is_image_req:
            target_exts = (".jpg", ".jpeg", ".png", ".webp")
        else:
            target_exts = (".pptx", ".pdf", ".docx", ".zip", ".png", ".jpg", ".txt", ".py")

        if not search_roots:
            search_roots = [
                os.path.expanduser("~/Downloads"),
                os.path.expanduser("~/Documents"),
                os.path.expanduser("~/Desktop"),
                r"D:\Projects",
                r"D:\nexus_ai",
            ]

        found_files = []
        for root in search_roots:
            if not os.path.exists(root):
                continue
            for dirpath, _, filenames in os.walk(root):
                # Skip .git, node_modules, .venv, .gemini
                if any(ignored in dirpath for ignored in (".git", "node_modules", ".venv", "__pycache__", ".gemini")):
                    continue
                for fname in filenames:
                    fname_lower = fname.lower()
                    stem = os.path.splitext(fname_lower)[0]
                    # Check if matching query keywords in filename stem
                    if any(k in stem for k in keywords) and fname_lower.endswith(target_exts):
                        found_files.append(os.path.join(dirpath, fname))
                        if len(found_files) >= 5:
                            return found_files

        return found_files

    def get_git_project_summary(self, repo_path: str = r"D:\nexus_ai") -> str:
        """Extracts recent git commit logs and modified files to provide rich context in emails."""
        try:
            cmd = 'git log -n 3 --pretty=format:"* %s (%cr)"'
            res = subprocess.run(cmd, cwd=repo_path, shell=True, capture_output=True, text=True, timeout=5)
            if res.returncode == 0 and res.stdout.strip():
                return f"Recent Project Milestones:\n{res.stdout.strip()}"
        except Exception:
            pass
        return ""

    async def plan_and_draft_email(
        self,
        user_prompt: str,
        user_name: str = "Charan",
        recipient_override: str = "",
        subject_override: str = "",
        body_override: str = "",
    ) -> Dict[str, Any]:
        """
        Analyzes the user's intent, discovers relevant attachments, gathers Git/task updates,
        and dynamically synthesizes the email subject, recipient, and body.
        """
        lower_p = user_prompt.lower()

        # 1. Infer recipient
        recipient = recipient_override or "professor@university.edu"
        if not recipient_override:
            if "sir" in lower_p or "prof" in lower_p or "teacher" in lower_p:
                recipient = "professor@university.edu"
            elif "team" in lower_p or "colleague" in lower_p:
                recipient = "team@company.internal"
            elif "client" in lower_p:
                recipient = "client@partner.com"

            email_match = re.search(r"[\w\.-]+@[\w\.-]+\.\w+", user_prompt)
            if email_match:
                recipient = email_match.group(0)

        # 2. Discover attachments on local disk
        attachments = []
        if any(w in lower_p for w in ("report", "pdf", "presentation", "ppt", "file", "project", "doc", "document", "image", "photo")):
            attachments = self.find_local_attachments(user_prompt)

        # 3. Gather Git context if team update
        git_context = ""
        if any(w in lower_p for w in ("update", "progress", "milestone", "today's", "status")):
            git_context = self.get_git_project_summary()

        # 4. Generate Subject and Body
        if subject_override and body_override:
            subject = subject_override
            body = body_override
        elif "leave" in lower_p or "sick" in lower_p or "vacation" in lower_p or "absence" in lower_p:
            subject = subject_override or "Leave Application / Absence Request"
            body = body_override or (
                f"Dear Sir/Madam,\n\n"
                f"I am writing to formally request a leave of absence regarding my upcoming schedule.\n"
                f"I will ensure that all my key responsibilities and priorities are updated, and I will be reachable via email if urgent attention is required.\n\n"
                f"Thank you for your understanding and consideration.\n\n"
                f"Best regards,\n{user_name}"
            )
        elif "report" in lower_p or "professor" in lower_p:
            subject = subject_override or "Project Submission & Progress Report"
            body = body_override or (
                f"Dear Professor,\n\n"
                f"Please find attached our latest project report for your review and evaluation.\n"
                f"We have completed the required milestones and integrated the automated workflows.\n\n"
                f"Please let us know if any further changes or presentations are required.\n\n"
                f"Sincerely,\n{user_name}"
            )
        elif "update" in lower_p or "team" in lower_p:
            subject = subject_override or f"Project Status & Update — {datetime.now().strftime('%B %d, %Y')}"
            body = body_override or (
                f"Hi Team,\n\n"
                f"Here is the latest progress update for our project:\n\n"
                f"{git_context or 'All planned core sprint features have been successfully developed and tested.'}\n\n"
                f"The documentation and artifacts are attached for your reference.\n\n"
                f"Best regards,\n{user_name}"
            )
        else:
            subject = subject_override or f"Nexus AI Task Delivery: {user_prompt[:40]}"
            body = body_override or (
                f"Hello,\n\n"
                f"Here is the automated output generated by Nexus AI for your request:\n"
                f"\"{user_prompt}\"\n\n"
                f"Best regards,\n{user_name}"
            )

        attachment_names = [os.path.basename(a) for a in attachments]

        return {
            "to": recipient,
            "subject": subject,
            "body": body,
            "attachments": attachments,
            "attachment_names": attachment_names,
            "risk_level": "MEDIUM" if attachments else "LOW",
            "prompt": user_prompt,
        }

    async def dispatch_to_n8n(self, draft: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sends the approved email. Tries n8n webhook first, then falls back to
        direct SMTP via Gmail with attachments.
        """
        webhook_url = f"{self.n8n_url}/webhook/send-email"
        payload = {
            "to": draft.get("to"),
            "subject": draft.get("subject"),
            "body": draft.get("body"),
            "attachments": draft.get("attachments", []),
            "timestamp": datetime.now().isoformat(),
        }

        # Try n8n webhook first
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                res = await client.post(webhook_url, json=payload)
                if res.status_code in (200, 201):
                    logger.info(f"[EmailAgent] Dispatched to n8n webhook successfully: {res.status_code}")
                    return {
                        "success": True,
                        "engine": "n8n_gmail",
                        "message": f"Email sent to {draft.get('to')} via n8n Gmail workflow.",
                        "recipient": draft.get("to"),
                        "subject": draft.get("subject"),
                        "attachments": draft.get("attachment_names", []),
                    }
        except Exception as e:
            logger.debug(f"[EmailAgent] n8n webhook offline ({e}), falling back to SMTP...")

        # Fallback: Direct SMTP via Gmail
        return await self._send_via_smtp(draft)

    async def _send_via_smtp(self, draft: Dict[str, Any]) -> Dict[str, Any]:
        """Send email directly via SMTP (Gmail) with attachment support."""
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        from email.mime.base import MIMEBase
        from email import encoders

        smtp_host = getattr(settings, "SMTP_HOST", "smtp.gmail.com")
        smtp_port = getattr(settings, "SMTP_PORT", 587)
        smtp_user = getattr(settings, "SMTP_USER", "")
        smtp_password = getattr(settings, "SMTP_PASSWORD", "")
        sender_email = getattr(settings, "SENDER_EMAIL", smtp_user)
        sender_name = getattr(settings, "SENDER_NAME", "Nexus AI")

        if not smtp_user or not smtp_password:
            logger.warning("[EmailAgent] SMTP credentials not configured")
            return {
                "success": False,
                "engine": "smtp",
                "error": "SMTP credentials not configured in settings.",
            }

        recipient = draft.get("to", "")
        subject = draft.get("subject", "Nexus AI Email")
        body = draft.get("body", "")
        attachments = draft.get("attachments", [])

        try:
            msg = MIMEMultipart()
            msg["From"] = f"{sender_name} <{sender_email}>"
            msg["To"] = recipient
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain"))

            # Attach files with auto-compression for large images to fit Gmail's 25MB limit
            attached_names = []
            total_bytes = 0
            for filepath in attachments:
                if os.path.exists(filepath):
                    actual_path = filepath
                    try:
                        fsize = os.path.getsize(filepath)
                        # Auto-compress images > 1.2MB using Pillow
                        if fsize > 1.2 * 1024 * 1024 and filepath.lower().endswith((".jpg", ".jpeg", ".png")):
                            try:
                                from PIL import Image
                                img = Image.open(filepath)
                                if img.mode in ("RGBA", "P"):
                                    img = img.convert("RGB")
                                img.thumbnail((1920, 1920), Image.Resampling.LANCZOS)
                                opt_path = filepath + ".opt.jpg"
                                img.save(opt_path, "JPEG", quality=85, optimize=True)
                                actual_path = opt_path
                            except Exception as pe:
                                logger.warning(f"[EmailAgent] Image compression skipped: {pe}")

                        # Strict 24MB total attachment budget for Gmail SMTP
                        if fsize > 24 * 1024 * 1024:
                            logger.warning(f"[EmailAgent] File {filepath} ({fsize / (1024*1024):.1f}MB) exceeds Gmail limit")
                            return {
                                "success": False,
                                "engine": "smtp",
                                "error": f"Attachment '{os.path.basename(filepath)}' ({fsize / (1024*1024):.1f} MB) exceeds Gmail's 25 MB limit. Please use a file smaller than 25 MB."
                            }

                        if total_bytes + fsize > 24 * 1024 * 1024:
                            logger.info(f"[EmailAgent] Skipping {filepath} — exceeds total attachment budget")
                            continue

                        with open(actual_path, "rb") as f:
                            part = MIMEBase("application", "octet-stream")
                            part.set_payload(f.read())
                        encoders.encode_base64(part)
                        fname = os.path.basename(filepath)
                        part.add_header("Content-Disposition", f"attachment; filename={fname}")
                        msg.attach(part)
                        attached_names.append(fname)
                        total_bytes += fsize
                    except Exception as ae:
                        logger.warning(f"[EmailAgent] Failed to attach {filepath}: {ae}")

            # Send via SMTP with TLS and explicit SSL context
            def _do_send():
                import ssl
                context = ssl.create_default_context()
                last_err = None
                for attempt in range(1, 4):
                    server = None
                    try:
                        server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
                        server.ehlo()
                        server.starttls(context=context)
                        server.ehlo()
                        server.login(smtp_user, smtp_password)
                        server.sendmail(sender_email, recipient, msg.as_string())
                        logger.info(f"[EmailAgent] Email successfully sent via SMTP to {recipient} (attempt {attempt})")
                        try:
                            server.quit()
                        except Exception:
                            pass
                        return
                    except Exception as ex:
                        last_err = ex
                        logger.warning(f"[EmailAgent] SMTP attempt {attempt} failed: {ex}")
                        if server:
                            try:
                                server.close()
                            except Exception:
                                pass
                        time.sleep(1.5)
                if last_err:
                    raise last_err

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _do_send)

            return {
                "success": True,
                "engine": "smtp_gmail",
                "message": f"Email sent to {recipient} via Gmail SMTP.",
                "recipient": recipient,
                "subject": subject,
                "attachments": attached_names,
            }

        except Exception as e:
            logger.error(f"[EmailAgent] SMTP send failed: {e}", exc_info=True)
            return {
                "success": False,
                "engine": "smtp",
                "error": f"SMTP send failed: {e}",
                "recipient": recipient,
                "subject": subject,
            }


# Singleton instance
email_agent = IntelligentEmailAgent()
