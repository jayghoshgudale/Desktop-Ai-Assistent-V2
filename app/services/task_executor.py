import logging
import time
import os
import datetime
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import quote, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError

from config import TASK_EXECUTION_TIMEOUT
import asyncio
import app.services.decision_types as decision_types
from app.services.decision_types import (
    INTENT_CAMERA,
    INTENT_CHAT,
    INTENT_CLOSE_WEBCAM,
    INTENT_CONTENT,
    INTENT_GENERATE_IMAGE,
    INTENT_GOOGLE_SEARCH,
    INTENT_OPEN,
    INTENT_OPEN_WEBCAM,
    INTENT_PLAY,
    INTENT_YOUTUBE_SEARCH,
    INTENT_OPEN_APP,
    INTENT_CLOSE_APP,
    INTENT_SYSTEM_CONTROL,
    INTENT_SCREEN_VISION,
    INTENT_READ_FILE,
    INTENT_RUN_CODE,
    INTENT_CALENDAR,
    INTENT_LIST_DIR,
)
from app.services.app_service import AppService
from app.services.system_service import SystemService

logger = logging.getLogger("J.A.R.V.I.S")


@dataclass
class TaskResponse:
    text: str = ""
    wopens: List[str] = field(default_factory=list)
    plays: List[str] = field(default_factory=list)
    images: List[str] = field(default_factory=list)
    contents: List[str] = field(default_factory=list)
    googlesearches: List[str] = field(default_factory=list)
    youtubesearches: List[str] = field(default_factory=list)
    actions: List[dict] = field(default_factory=list)
    calendar_result: Optional[dict] = None
    file_result: Optional[dict] = None
    sandbox_result: Optional[dict] = None
    cam: Optional[dict] = None


class TaskExecutor:
    def __init__(self, groq_service=None, vision_service=None, file_service=None, sandbox_service=None, calendar_service=None):
        self.groq_service = groq_service
        self.vision_service = vision_service
        self.file_service = file_service
        self.sandbox_service = sandbox_service
        self.calendar_service = calendar_service
        self.app_service = AppService()
        self.system_service = SystemService()
        logger.info("[TASK] TaskExecutor initialized (Pollinations.ai for images, mss for screen)")

    def execute(
        self,
        intents: List[tuple],
        chat_history: Optional[List[tuple]] = None,
    ) -> TaskResponse:
        response = TaskResponse()
        tasks = []

        for intent_type, payload in intents:
            if intent_type == INTENT_OPEN:
                tasks.append(("wopen", self._do_open, payload))
            elif intent_type == INTENT_PLAY:
                tasks.append(("play", self._do_play, payload))
            elif intent_type == INTENT_GENERATE_IMAGE:
                tasks.append(("image", self._do_generate_image, payload))
            elif intent_type == INTENT_CONTENT:
                tasks.append(("content", lambda p: self._do_content(p, chat_history), payload))
            elif intent_type == INTENT_GOOGLE_SEARCH:
                tasks.append(("google", self._do_google_search, payload))
            elif intent_type == INTENT_YOUTUBE_SEARCH:
                tasks.append(("youtube", self._do_youtube_search, payload))
            elif intent_type == INTENT_OPEN_WEBCAM:
                response.cam = {"action": "open"}
                response.text = "Opening the webcam for you."
            elif intent_type == INTENT_CLOSE_WEBCAM:
                response.cam = {"action": "close"}
                response.text = "Webcam closed."
            elif intent_type == INTENT_CAMERA:
                response.cam = {"action": "open"}
                response.text = (
                    "Opening your webcam. Once it's on, send your message again "
                    "and I'll describe what I see."
                )
            elif intent_type == INTENT_OPEN_APP:
                tasks.append(("open_app", self._do_open_app, payload))
            elif intent_type == INTENT_CLOSE_APP:
                tasks.append(("close_app", self._do_close_app, payload))
            elif intent_type == INTENT_SYSTEM_CONTROL:
                tasks.append(("system_control", self._do_system_control, payload))
            elif intent_type == INTENT_SCREEN_VISION:
                tasks.append(("screen_vision", self._do_screen_vision, payload))
            elif intent_type == INTENT_READ_FILE:
                tasks.append(("read_file", self._do_read_file, payload))
            elif intent_type == INTENT_RUN_CODE:
                tasks.append(("run_code", self._do_run_code, payload))
            elif intent_type == INTENT_CALENDAR:
                tasks.append(("calendar", self._do_calendar, payload))
            elif intent_type == INTENT_LIST_DIR:
                tasks.append(("list_dir", self._do_list_dir, payload))
            elif intent_type == INTENT_CHAT:
                pass

        if not tasks:
            if not response.text and not response.cam:
                response.text = "I'm not sure what you'd like me to do. Could you clarify?"
            return response

        t0 = time.perf_counter()
        failed_tags = []

        try:
            with ThreadPoolExecutor(max_workers=min(6, len(tasks))) as executor:
                futures = {
                    executor.submit(fn, p): (tag, fn, p)
                    for tag, fn, p in tasks
                }
                for future in as_completed(futures, timeout=TASK_EXECUTION_TIMEOUT):
                    tag, fn, payload = futures[future]
                    try:
                        result = future.result()
                        if tag == "wopen" and result:
                            response.wopens.append(result)
                        elif tag == "play" and result:
                            response.plays.append(result)
                        elif tag == "image" and result:
                            response.images.append(result)
                        elif tag == "content" and result:
                            response.contents.append(result)
                        elif tag == "google" and result:
                            response.googlesearches.append(result)
                        elif tag == "youtube" and result:
                            response.youtubesearches.append(result)
                        elif tag == "open_app" and result:
                            if "Failed" in result or "Could not" in result:
                                response.text = result
                            else:
                                response.text = result
                        elif tag == "close_app" and result:
                            response.text = result
                        elif tag == "screen_vision" and result:
                            response.text = result
                        elif tag == "read_file" and isinstance(result, dict):
                            response.file_result = result
                            response.text = f"I've read and analyzed '{result.get('filename')}'. Here is what I found."
                        elif tag == "read_file" and result:
                            response.text = result
                        elif tag == "run_code" and isinstance(result, dict):
                            response.sandbox_result = result
                            response.text = "I've executed the script. Here are the results."
                        elif tag == "run_code" and result:
                            response.text = result
                        elif tag == "calendar" and isinstance(result, dict):
                            response.calendar_result = result
                            response.text = f"I've fetched your {result.get('title', 'calendar')}."
                        elif tag == "calendar" and result:
                            response.text = result
                        elif tag == "system_control" and result:
                            response.actions.append(result)
                            response.text = "Please confirm the system action on your screen."
                    except Exception as e:
                        failed_tags.append(tag)
                        err_msg = str(e)[:100]
                        logger.warning("[TASK] Task %s failed: %s", tag, e)
                        if "content_policy" in err_msg.lower() or "safety" in err_msg.lower():
                            if tag == "image":
                                response.text = (
                                    "I couldn't generate that image — it may violate content guidelines."
                                )
                        elif not response.text:
                            response.text = f"Something went wrong with that task: {err_msg}"

        except FuturesTimeoutError:
            logger.warning("[TASK] Task execution timed out after %ds", TASK_EXECUTION_TIMEOUT)
            if not response.text:
                response.text = "Some tasks took too long. Please try again."

        elapsed = time.perf_counter() - t0
        logger.info(
            "[TASK] Executed %d tasks in %.2fs (failed: %s)",
            len(tasks),
            elapsed,
            failed_tags or "none",
        )

        if not response.text:
            parts = self._build_conversational_response(
                response.wopens,
                response.plays,
                response.images,
                response.contents,
                response.googlesearches,
                response.youtubesearches,
            )
            response.text = parts if parts else "All done."

        return response

    def _url_to_display_name(self, url: str) -> str:
        u = (url or "").lower()
        mapping = {
            "facebook.com": "Facebook",
            "instagram.com": "Instagram",
            "youtube.com": "YouTube",
            "google.com": "Google",
            "netflix.com": "Netflix",
            "twitter.com": "Twitter",
            "x.com": "X",
            "x.com": "X",
            "linkedin.com": "LinkedIn",
            "reddit.com": "Reddit",
            "discord.com": "Discord",
            "spotify.com": "Spotify",
            "tiktok.com": "TikTok",
            "amazon.com": "Amazon",
            "github.com": "GitHub",
            "wikipedia.org": "Wikipedia",
            "stackoverflow.com": "Stack Overflow",
            "medium.com": "Medium",
            "notion.so": "Notion",
            "figma.com": "Figma",
            "canva.com": "Canva",
            "zoom.us": "Zoom",
            "drive.google.com": "Google Drive",
            "jarvisforeveryone.com": "Jarvis for Everyone",
            "graphy.com": "Graphy",
        }
        for key, name in mapping.items():
            if key in u:
                return name
        try:
            parsed = urlparse(url)
            domain = (parsed.netloc or parsed.path or "").replace("www.", "").split(".")[0]
            return domain.title() if domain else "the link"
        except Exception:
            return "the link"

    def _build_conversational_response(
        self,
        wopens: List[str],
        plays: List[str],
        images: List[str],
        contents: List[str],
        googlesearches: List[str],
        youtubesearches: List[str],
    ) -> str:
        parts = []

        if wopens:
            names = [self._url_to_display_name(u) for u in wopens]
            if len(names) == 1:
                parts.append(f"I've opened {names[0]} for you.")
            else:
                last = names[-1]
                rest = ", ".join(names[:-1])
                parts.append(f"I've opened {rest} and {last} for you.")

        if plays:
            parts.append("I've started playing that for you.")

        if images:
            count = len(images)
            parts.append(f"I've generated the image{'s' if count > 1 else ''} for you.")

        if contents:
            parts.append("I've written that for you.")

        if googlesearches or youtubesearches:
            parts.append("I've run the search for you.")

        return " ".join(parts) if parts else "Done."

    def _validate_url(self, url: str) -> Optional[str]:
        if not url or len(url) > 2048:
            return None
        u = url.strip()
        if not u.startswith("http"):
            u = "https://" + u
        try:
            parsed = urlparse(u)
            if parsed.scheme not in ("http", "https"):
                logger.warning("[TASK] Rejected non-http URL: %s", u[:50])
                return None
            return u
        except Exception:
            return None

    def _do_open(self, payload: dict) -> Optional[str]:
        url = payload.get("url", "").strip()
        if not url:
            return None
        return self._validate_url(url)

    def _do_play(self, payload: dict) -> Optional[str]:
        query = (payload.get("query", payload.get("message", "")) or "").strip()[:500]
        if not query:
            return "https://www.youtube.com"
            
        # Try Spotify fallback logic if on Windows
        if os.name == "nt":
            try:
                import webbrowser
                # Check if spotify is running or installed via URI
                # On Windows, startfile with a URI is a good way to trigger the app
                os.startfile(f"spotify:search:{quote(query)}")
                return f"Playing '{query}' on Spotify."
            except Exception as e:
                logger.debug(f"[TASK] Spotify fallback failed: {e}")
        
        # Default to YouTube search
        return f"https://www.youtube.com/results?search_query={quote(query, safe='')}"

    def _do_generate_image(self, payload: dict) -> Optional[tuple]:
        """Returns (url, bytes) or None on failure."""
        prompt = (payload.get("prompt", payload.get("message", "")) or "").strip()
        if not prompt:
            return None
        
        if len(prompt) < 3:
            logger.warning("[TASK] Image prompt too short (< 3 chars)")
            return None
            
        prompt = prompt[:4000]
        t0 = time.perf_counter()
        result = self._generate_pollinations(prompt)
        if result:
            logger.info("[TASK] Pollinations image generated in %.2fs", time.perf_counter() - t0)
            return result
        logger.warning("[TASK] Image generation failed")
        return None
        
    def _do_open_app(self, p: dict) -> str:
        app_name = p.get("app_name", "")
        if not app_name:
            return "No application name provided."
        return self.app_service.open_application(app_name)

    def _do_close_app(self, p: dict) -> str:
        app_name = p.get("app_name", "")
        if not app_name:
            return "No application name provided to close."
        return self.app_service.close_application(app_name)

    def _do_screen_vision(self, p: dict) -> str:
        if not self.vision_service:
            return "Vision service is disabled or missing."
        screenshot_b64 = self.vision_service.take_screenshot()
        if not screenshot_b64:
            return "Failed to take a screenshot."
        prompt = p.get("prompt", p.get("message", "What do you see on this screen?"))
        logger.info("[TASK] Sending screenshot to vision model...")
        return self.vision_service.describe_image(screenshot_b64, prompt)

    def _do_read_file(self, p: dict) -> str:
        if not self.file_service:
            return "File service is disabled or missing."
        file_name = p.get("file_name", p.get("message", "")).strip()
        if not file_name:
            return "What file would you like me to read?"
        logger.info("[TASK] Expanding and reading file for context...")
        content = self.file_service.read_file(file_name)
        if "Error" in content or "not found" in content or "Please install" in content:
            return content
        
        # Determine file type
        file_type = "PDF Document" if file_name.lower().endswith(".pdf") else "Text File"
        
        # If successfully read, return structured payload
        return {
            "filename": os.path.basename(file_name),
            "file_type": file_type,
            "content": content
        }

    def _do_list_dir(self, p: dict) -> str:
        """Lists contents of a directory."""
        path = p.get("path", ".").strip()
        if not os.path.exists(path):
            return f"Directory '{path}' not found."
        
        try:
            items = os.listdir(path)
            # Limit to 50 items for briefness
            display_items = items[:50]
            summary = f"Contents of {os.path.abspath(path)}:\n" + "\n".join([f"- {it}" for it in display_items])
            if len(items) > 50:
                summary += f"\n... and {len(items) - 50} more items."
            return summary
        except Exception as e:
            return f"Error listing directory: {e}"

    def _do_run_code(self, p: dict) -> str:
        if not self.sandbox_service:
            return "Code sandbox is disabled or missing."
            
        prompt = p.get("prompt", p.get("message", "")).strip()
        if not prompt:
            return "Please provide instructions for the code you want to run."
            
        logger.info("[TASK] Generating Python script to execute...")
        sys_prompt = "You are a Python script generator. Write an anonymous, fully self-contained Python 3 script that satisfies the user's request. Output ONLY valid, executable raw Python code without any markdown blocks, backticks, or natural language text. The script will be executed in a headless sandbox environment, so make sure it prints the result to stdout using print(). NO TRUNCATION. NO PLACEHOLDERS."
        
        # We need Groq to output just code.
        code = self.groq_service.generate_text(prompt, system_prompt=sys_prompt, max_tokens=1500)
        
        # Clean up in case groq adds ```python
        code = code.replace("```python", "").replace("```", "").strip()
        
        logger.info("[TASK] Executing generated Python script via Sandbox...")
        raw_result = self.sandbox_service.run_python_code(code)
        
        # Return structured sandbox result for frontend card
        return {
            "stdout": raw_result.get("stdout", ""),
            "stderr": raw_result.get("stderr", ""),
            "exit_code": raw_result.get("exit_code", 0)
        }

    def _do_calendar(self, p: dict) -> str:
        if not self.calendar_service:
            return "Calendar service missing or credentials not found."
            
        prompt = p.get("prompt", p.get("message", "")).strip()
        
        classification_prompt = f"Does the following request ask for today's agenda/events or are they trying to schedule a new event?\nUser: '{prompt}'\nAnswer strictly with either 'AGENDA' or 'SCHEDULE'."
        route = self.groq_service.generate_text(classification_prompt, max_tokens=10).upper()
        
        if "AGENDA" in route:
            logger.info("[TASK] Fetching Calendar Agenda...")
            return self.calendar_service.get_todays_agenda() # Now returns structured dict
        else:
            logger.info("[TASK] Attempting to Schedule Event on Calendar...")
            today = datetime.date.today().isoformat()
            extract_prompt = f"Extract the event title, start time, and end time from this request: '{prompt}'. Return exactly in this format separated by pipes, using ISO 8601 for times (e.g. 2026-04-23T15:00:00Z for UTC). If end time is not specified, assume 1 hour after start. Today's date is {today}.\nFormat: Title | Start Time | End Time"
            details = self.groq_service.generate_text(extract_prompt, max_tokens=100)
            parts = [x.strip() for x in details.split('|')]
            if len(parts) >= 3:
                return self.calendar_service.schedule_event(parts[0], parts[1], parts[2])
            else:
                return "Failed to parse scheduling details from your request."

    def _do_system_control(self, p: dict) -> dict:
        command = p.get("command", "sleep").lower()
        return {"type": "confirm", "action_id": "sys_"+command, "data": {"type": "system", "command": command}}

    def _generate_pollinations(self, prompt: str) -> Optional[tuple]:
        """Download the generated image and return (url, bytes), or None on failure."""
        import httpx

        encoded_prompt = quote(prompt, safe="")
        api_url = (
            f"https://image.pollinations.ai/prompt/{encoded_prompt}"
            f"?model=flux&width=1024&height=1024&nologo=true&private=true&enhance=true&safe=false"
        )
        logger.info("[TASK] Fetching Pollinations image: %s", api_url[:120])

        for attempt in range(3):
            try:
                with httpx.Client(timeout=60, follow_redirects=True) as client:
                    resp = client.get(api_url)
                    if resp.status_code == 200 and resp.content:
                        content_type = resp.headers.get("content-type", "")
                        if "image" in content_type or len(resp.content) > 1000:
                            logger.info(
                                "[TASK] Pollinations image fetched (%d bytes)", len(resp.content)
                            )
                            return (api_url, resp.content)
                    logger.warning(
                        "[TASK] Pollinations attempt %d: status=%d", attempt + 1, resp.status_code
                    )
            except Exception as e:
                logger.warning("[TASK] Pollinations attempt %d failed: %s", attempt + 1, e)
            time.sleep(2)

        return None

    def _do_content(
        self, payload: dict, chat_history: Optional[List[tuple]] = None
    ) -> Optional[str]:
        prompt = (payload.get("prompt", payload.get("message", "")) or "").strip()
        if not prompt or not self.groq_service:
            return None
        content_question = (
            f"Write the following. Be thorough and well-structured. "
            f"Return only the requested content, no preamble.\n\n{prompt}"
        )
        try:
            out = self.groq_service.get_response(
                question=content_question,
                chat_history=chat_history or [],
                key_start_index=0,
            )
            if not out or len(out.strip()) < 10:
                logger.warning("[TASK] Content generation returned empty or very short result")
                return None
            return out
        except Exception as e:
            logger.warning("[TASK] Content generation error: %s", e)
            return None

    def _do_google_search(self, payload: dict) -> Optional[str]:
        query = (payload.get("query", payload.get("message", "")) or "").strip()[:500]
        if not query:
            return None
        return f"https://www.google.com/search?q={quote(query, safe='')}"

    def _do_youtube_search(self, payload: dict) -> Optional[str]:
        query = (payload.get("query", payload.get("message", "")) or "").strip()[:500]
        if not query:
            return "https://www.youtube.com"
        return f"https://www.youtube.com/results?search_query={quote(query, safe='')}"
