import logging
import threading
import time
from typing import Optional

logger = logging.getLogger("J.A.R.V.I.S")

class ClipboardService:
    def __init__(self, groq_service):
        self.groq_service = groq_service
        self.on_event = None
        self._hotkey_thread = None
        self._running = False
        
    def start_hotkey_listener(self):
        """Starts a background thread to listen for a global hotkey."""
        self._running = True
        self._hotkey_thread = threading.Thread(target=self._listener_loop, daemon=True)
        self._hotkey_thread.start()

    def _listener_loop(self):
        try:
            import keyboard
            
            # Use Ctrl+Alt+C so we don't override standard copy
            # The lambda is triggered natively when the hotkey is pressed.
            keyboard.add_hotkey('ctrl+alt+c', self._handle_hotkey, suppress=True)
            logger.info("[CLIPBOARD] Global hotkey Ctrl+Alt+C registered for J.A.R.V.I.S Auto-Trigger.")
            
            while self._running:
                time.sleep(1)
        except ImportError:
            logger.warning("[CLIPBOARD] 'keyboard' library not installed.")
        except Exception as e:
            logger.error("[CLIPBOARD] Hotkey binding failed (Admin rights needed?): %s", e)

    def _handle_hotkey(self):
        """Callback for when the global hotkey is pressed."""
        logger.info("[CLIPBOARD] Global hotkey detected! Reading clipboard...")
        text = self.read_clipboard()
        if not text:
            print("\n[J.A.R.V.I.S] (Clipboard is empty!)\n")
            return
            
        print(f"\n====== J.A.R.V.I.S AUTO-TRIGGER (Clipboard) ======\nCopied: {text[:50]}...\nThinking...")
        
        # Fire off autonomous inference
        prompt = f"The user just copied this text to their clipboard. Explain, summarize, or debug it quickly:\n\n{text}"
        
        def _run_inference():
            try:
                result = self.groq_service.generate_text(prompt, max_tokens=300)
                if self.on_event:
                    self.on_event({"event": "clipboard_detected", "text": text, "response": result})
                print(f"\n[J.A.R.V.I.S] -> {result}\n==================================================\n")
            except Exception as e:
                print(f"\n[J.A.R.V.I.S] -> Error analyzing clipboard: {e}\n")
                
        # Run in thread so the hotkey thread doesn't block
        threading.Thread(target=_run_inference, daemon=True).start()

    def read_clipboard(self) -> Optional[str]:
        """Reads and returns the current plain-text system clipboard content."""
        try:
            import pyperclip
            text = pyperclip.paste()
            if text and len(text.strip()) > 0:
                return text.strip()
            return None
        except Exception as e:
            logger.error("[CLIPBOARD] Failed to read clipboard: %s", e)
            return None
