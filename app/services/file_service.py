import os
import sys
import logging
import threading
from typing import Optional
from pathlib import Path

logger = logging.getLogger("J.A.R.V.I.S")

class FileService:
    def __init__(self, groq_service=None):
        self.groq_service = groq_service
        self._observer = None
        self._downloads_path = str(Path.home() / "Downloads")

    def start_watcher(self):
        """Starts a background watchdog observer to monitor the Downloads folder."""
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            class DownloadHandler(FileSystemEventHandler):
                def __init__(self, fs_ref: 'FileService'):
                    self.fs_ref = fs_ref

                def on_created(self, event):
                    if not event.is_directory:
                        filename = os.path.basename(event.src_path)
                        # We only react to common readable completed files
                        if filename.endswith(('.pdf', '.txt', '.csv', '.docx')):
                            logger.info("[FILE_SERVICE] New document detected: %s", filename)
                            print(f"\n[J.A.R.V.I.S] Auto-Trigger: I noticed you just downloaded '{filename}'. Ask me if you'd like me to read or analyze it!\n")

            self._observer = Observer()
            handler = DownloadHandler(self)
            self._observer.schedule(handler, self._downloads_path, recursive=False)
            self._observer.start()
            logger.info("[FILE_SERVICE] Watchdog monitoring active on: %s", self._downloads_path)
            
        except ImportError:
            logger.warning("[FILE_SERVICE] 'watchdog' library not installed.")
        except Exception as e:
            logger.error("[FILE_SERVICE] Watchdog startup failed: %s", e)

    def stop_watcher(self):
        if self._observer:
            self._observer.stop()
            self._observer.join()

    def read_file(self, file_path: str) -> Optional[str]:
        """Reads a file based on its extension (PDF or text)."""
        if not os.path.exists(file_path):
            dl_file = os.path.join(self._downloads_path, file_path)
            if os.path.exists(dl_file):
                file_path = dl_file
            else:
                return "File not found."

        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".pdf":
            return self.read_pdf(file_path)
        
        # Generic text file reading
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read(50000) # 50k char limit for safety
                if f.tell() >= 50000:
                    content += "\n... [Truncated for length]"
                return content
        except Exception as e:
            logger.error("[FILE_SERVICE] Error reading text file: %s", e)
            return f"Error reading file: {e}"

    def read_pdf(self, file_path: str) -> Optional[str]:
        """Extracts text seamlessly from a PDF using pdfplumber."""
        if not os.path.exists(file_path):
            # Attempt to check if the user just supplied filename in Downloads
            dl_file = os.path.join(self._downloads_path, file_path)
            if os.path.exists(dl_file):
                file_path = dl_file
            else:
                return "File not found."

        try:
            import pdfplumber
            text_blocks = []
            with pdfplumber.open(file_path) as pdf:
                for idx, page in enumerate(pdf.pages):
                    page_text = page.extract_text()
                    if page_text:
                        text_blocks.append(page_text)
                    if idx >= 20: # hard limit logic to prevent gigabytes of tokens
                        text_blocks.append("... [Truncated for length]")
                        break
            extracted = "\n".join(text_blocks).strip()
            if not extracted:
                return "The PDF appears to be an image format or is unable to be read as text."
            return extracted
        except ImportError:
            return "Please install pdfplumber: pip install pdfplumber"
        except Exception as e:
            logger.error("[FILE_SERVICE] pdfplumber error: %s", e)
            return f"Error reading PDF: {e}"
