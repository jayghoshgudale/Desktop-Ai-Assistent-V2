import time
import struct
import logging
import threading
import numpy as np
from typing import Optional

logger = logging.getLogger("J.A.R.V.I.S")


class AudioListenerService:
    def __init__(self, groq_service=None):
        self.groq_service = groq_service
        self.on_event = None
        self._running = False
        self._thread = None
        self.oww_model = None
        self.pa = None
        self.audio_stream = None
        self.whisper_model = None
        self.sample_rate = 16000
        self.chunk_size = 1280

        # ── State flags ───────────────────────────────────────────────────────
        # True  → currently recording / processing a command (mic is "open")
        # False → idle, waiting for wake word
        self._busy = False

        # Allows the frontend mic button to also trigger command recording
        self._manual_trigger = threading.Event()

    # ─────────────────────────────────────────────────────────────────────────
    # Public control
    # ─────────────────────────────────────────────────────────────────────────

    def start_listening(self):
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop_listening(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def trigger_manual(self):
        """Call this when the user clicks the mic button in the frontend."""
        if not self._busy:
            self._manual_trigger.set()

    # ─────────────────────────────────────────────────────────────────────────
    # Init
    # ─────────────────────────────────────────────────────────────────────────

    def _init_models(self):
        try:
            import pyaudio
            from openwakeword.model import Model

            logger.info("[AUDIO_LISTENER] Loading OpenWakeWord model (hey_jarvis)...")
            self.oww_model = Model(
                wakeword_models=["hey_jarvis"],
                inference_framework="onnx"
            )

            from faster_whisper import WhisperModel
            logger.info("[AUDIO_LISTENER] Loading offline WhisperModel (tiny.en)...")
            self.whisper_model = WhisperModel("tiny.en", device="cpu", compute_type="int8")

            self.pa = pyaudio.PyAudio()
            self.audio_stream = self.pa.open(
                rate=self.sample_rate,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=self.chunk_size
            )
            return True

        except ImportError as e:
            logger.error(
                "[AUDIO_LISTENER] Missing dependency: %s. "
                "Run: pip install openwakeword faster-whisper pyaudio", e
            )
            return False
        except Exception as e:
            logger.error("[AUDIO_LISTENER] Failed to init audio models: %s", e)
            return False

    # ─────────────────────────────────────────────────────────────────────────
    # Recording — stops automatically on silence (max 10 s)
    # ─────────────────────────────────────────────────────────────────────────

    def _record_until_silence(self, silence_threshold=500, silence_duration=1.5):
        """
        Records from the mic until the user stops speaking (silence for
        `silence_duration` seconds) or 10 seconds have elapsed.
        Returns a float32 numpy array normalised to [-1, 1].
        """
        frames = []
        silent_chunks = 0
        max_silent_chunks = int((self.sample_rate / self.chunk_size) * silence_duration)

        logger.info("[AUDIO_LISTENER] 🎙  Recording voice command...")

        start_time = time.time()
        while self._running and (time.time() - start_time) < 10.0:
            pcm = self.audio_stream.read(self.chunk_size, exception_on_overflow=False)
            pcm_unpacked = struct.unpack_from("h" * self.chunk_size, pcm)
            frames.extend(pcm_unpacked)

            rms = np.sqrt(np.mean(np.array(pcm_unpacked, dtype=np.float32) ** 2))
            if rms < silence_threshold:
                silent_chunks += 1
            else:
                silent_chunks = 0  # voice detected — reset silence counter

            if silent_chunks > max_silent_chunks:
                logger.info("[AUDIO_LISTENER] Silence detected — stopping recording.")
                break

        return np.array(frames, dtype=np.float32) / 32768.0

    # ─────────────────────────────────────────────────────────────────────────
    # Process one command: transcribe → respond → broadcast → go idle
    # ─────────────────────────────────────────────────────────────────────────

    def _process_voice_command(self):
        """
        Full pipeline for one voice command:
          1. Record until silence
          2. Transcribe with Whisper
          3. Send to Groq and get a response
          4. Fire on_event so the frontend can show / speak the result
          5. Return → caller resets wake-word model and goes back to idle
        """
        self._busy = True
        try:
            # ── 1. Record ────────────────────────────────────────────────────
            audio_data = self._record_until_silence()

            # Too short → treat as noise, ignore
            if len(audio_data) < self.sample_rate * 0.5:
                logger.info("[AUDIO_LISTENER] Command too short — ignored.")
                return

            # ── 2. Transcribe ────────────────────────────────────────────────
            logger.info("[AUDIO_LISTENER] Transcribing...")
            segments, _ = self.whisper_model.transcribe(audio_data, beam_size=1)
            transcription = "".join(seg.text for seg in segments).strip()

            if not transcription:
                logger.info("[AUDIO_LISTENER] Empty transcription — ignored.")
                return

            print(
                f"\n====== J.A.R.V.I.S WAKE-WORD TRIGGER ======\n"
                f"Command : {transcription}\n"
                f"Thinking..."
            )

            # ── 3. Generate response ─────────────────────────────────────────
            prompt = (
                f"The user just spoke to you via wake-word: '{transcription}'. "
                "Give a concise, conversational answer."
            )
            result = self.groq_service.generate_text(prompt, max_tokens=150)

            print(f"\n[J.A.R.V.I.S] → {result}\n" + "=" * 44 + "\n")

            # ── 4. Broadcast to frontend ─────────────────────────────────────
            if self.on_event:
                self.on_event({
                    "event": "wake_detected",
                    "transcription": transcription,
                    "response": result,
                })

        except Exception as e:
            logger.error("[AUDIO_LISTENER] Error processing voice command: %s", e)

        finally:
            # ── 5. Always go back to idle ────────────────────────────────────
            self._busy = False
            logger.info("[AUDIO_LISTENER] ✅ Done. Back to listening for 'Hey Jarvis'...")

    # ─────────────────────────────────────────────────────────────────────────
    # Main loop
    # ─────────────────────────────────────────────────────────────────────────

    def _run_loop(self):
        if not self._init_models():
            self._running = False
            return

        logger.info(
            "[AUDIO_LISTENER] Active — listening for 'Hey Jarvis' or manual mic trigger."
        )

        try:
            while self._running:

                # ── Manual mic-button trigger ────────────────────────────────
                if self._manual_trigger.is_set():
                    self._manual_trigger.clear()
                    logger.info("[AUDIO_LISTENER] 🖱  Manual mic trigger received.")
                    self._process_voice_command()
                    self.oww_model.reset()
                    continue

                # ── Wake-word detection ──────────────────────────────────────
                # While busy (processing a command) keep draining the mic so
                # the buffer doesn't overflow, but skip wake-word scoring.
                pcm = self.audio_stream.read(self.chunk_size, exception_on_overflow=False)

                if self._busy:
                    continue  # mic is already "open" — don't double-trigger

                audio_np = np.frombuffer(pcm, dtype=np.int16)
                prediction = self.oww_model.predict(audio_np)

                for mdl_name, score in prediction.items():
                    # score may be a numpy array (one value per frame in the chunk)
                    peak = float(score[-1]) if hasattr(score, "__len__") else float(score)

                    if peak > 0.5:
                        print(f"\n[J.A.R.V.I.S] Yes? I'm listening… (model={mdl_name}, score={peak:.2f})")

                        # Notify frontend that mic is now open
                        if self.on_event:
                            self.on_event({"event": "wake_word_detected", "model": mdl_name})

                        self._process_voice_command()

                        # Reset model state — prevents the same activation from
                        # firing again on the very next chunk
                        self.oww_model.reset()
                        break  # don't check other models after a trigger

        finally:
            if self.audio_stream is not None:
                self.audio_stream.close()
            if self.pa is not None:
                self.pa.terminate()
            logger.info("[AUDIO_LISTENER] Stopped.")