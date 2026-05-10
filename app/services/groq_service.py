"""
groq_service.py
---------------
Core LLM service using Groq with multi-key fallback, repetition detection,
vector-store context retrieval, and both invoke and streaming modes.
"""

import logging
import time
from typing import Iterator, List, Optional

from groq import Groq  # ✅ raw Groq client (thread-safe, no asyncio dependency)
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_groq import ChatGroq

# from app.services.vector_store import VectorStoreService  # Decommissioned
from app.utils.retry import with_retry
from app.utils.time_info import get_time_information
from config import (
    GENERAL_CHAT_ADDENDUM,
    GROQ_API_KEYS,
    GROQ_MODEL,
    JARVIS_SYSTEM_PROMPT,
)

logger = logging.getLogger("J.A.R.V.I.S")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
GROQ_REQUEST_TIMEOUT = 60

ALL_APIS_FAILED_MESSAGE = (
    "I'm unable to process your request at the moment. "
    "All API services are temporarily unavailable. Please try again in a few minutes."
)

_REPEAT_WINDOW = 100
_REPEAT_THRESHOLD = 3
_REPEAT_CHECK_INTERVAL = 200


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------
class AllGroqApisFailedError(Exception):
    """Raised when every configured Groq API key has been exhausted."""


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------
def escape_curly_braces(text: str) -> str:
    """Escape { and } so they are not interpreted as LangChain template vars."""
    if not text:
        return text
    return text.replace("{", "{{").replace("}", "}}")


def _detect_repetition_loop(text: str) -> bool:
    """Return True if the tail phrase of *text* repeats >= _REPEAT_THRESHOLD times."""
    if len(text) < _REPEAT_WINDOW * _REPEAT_THRESHOLD:
        return False
    phrase = text[-_REPEAT_WINDOW:]
    return text.count(phrase) >= _REPEAT_THRESHOLD


def _truncate_at_repetition(text: str) -> str:
    """Truncate *text* just before the second occurrence of its repeating tail."""
    if len(text) < _REPEAT_WINDOW * _REPEAT_THRESHOLD:
        return text
    phrase = text[-_REPEAT_WINDOW:]
    if text.count(phrase) < _REPEAT_THRESHOLD:
        return text
    first = text.find(phrase)
    second = text.find(phrase, first + 1)
    if second > first:
        return text[:second].rstrip()
    return text


def _is_rate_limit_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "429" in str(exc) or "rate limit" in msg or "tokens per day" in msg


def _log_timing(label: str, elapsed: float, extra: str = "") -> None:
    msg = f"[TIMING] {label}: {elapsed:.3f}s"
    if extra:
        msg += f" ({extra})"
    logger.info(msg)


def _mask_api_key(key: str) -> str:
    if not key or len(key) <= 12:
        return "***masked***"
    return f"{key[:8]}...{key[-4:]}"


# ---------------------------------------------------------------------------
# Main service
# ---------------------------------------------------------------------------
class GroqService:
    """Wraps one or more Groq LLM clients with automatic key-rotation fallback."""

    def __init__(self):
        self.llms = [ChatGroq(groq_api_key=k, model_name=GROQ_MODEL, timeout=GROQ_REQUEST_TIMEOUT) for k in GROQ_API_KEYS]
        self._raw_clients = [Groq(api_key=k) for k in GROQ_API_KEYS]
        # self.vector_store_service = vector_store_service  # Decommissioned
        logger.info(
            "Initialized GroqService with %d API key(s) (primary-first fallback)",
            len(GROQ_API_KEYS),
        )

    # ------------------------------------------------------------------
    # Internal: invoke (non-streaming)
    # ------------------------------------------------------------------
    def _invoke_llm(
        self,
        prompt: ChatPromptTemplate,
        messages: list,
        question: str,
        key_start_index: int = 0,
    ) -> str:
        n = len(self.llms)
        last_exc: Optional[Exception] = None
        keys_tried: List[int] = []

        for j in range(n):
            i = (key_start_index + j) % n
            keys_tried.append(i)
            masked_key = _mask_api_key(GROQ_API_KEYS[i])
            logger.info("Trying API key #%d/%d: %s", i + 1, n, masked_key)

            def _invoke_with_key():
                chain = prompt | self.llms[i]
                return chain.invoke({"history": messages, "question": question})

            try:
                response = with_retry(_invoke_with_key, max_retries=2, initial_delay=0.5)

                if i > 0:
                    logger.info(
                        "Fallback successful: API key #%d/%d succeeded: %s",
                        i + 1, n, masked_key,
                    )

                text: str = response.content
                if _detect_repetition_loop(text):
                    logger.warning(
                        "[INVOKE] Repetition loop detected – truncating response (%d chars)", len(text)
                    )
                    text = _truncate_at_repetition(text)
                return text

            except Exception as exc:
                last_exc = exc
                if _is_rate_limit_error(exc):
                    logger.warning("API key #%d/%d rate limited: %s", i + 1, n, masked_key)
                else:
                    logger.warning(
                        "API key #%d/%d failed: %s – %s", i + 1, n, masked_key, str(exc)[:100]
                    )
                if i < n - 1:
                    logger.info("Falling back to next API key…")
                    continue
                break

        masked_all = ", ".join(_mask_api_key(GROQ_API_KEYS[j]) for j in keys_tried)
        logger.error("All %d API key(s) failed. Tried: %s", n, masked_all)
        raise AllGroqApisFailedError(ALL_APIS_FAILED_MESSAGE) from last_exc

    # ------------------------------------------------------------------
    # Internal: stream
    # ------------------------------------------------------------------
    def _stream_llm(
        self,
        prompt: ChatPromptTemplate,
        messages: list,
        question: str,
        key_start_index: int = 0,
    ) -> Iterator[str]:
        n = len(self.llms)
        last_exc: Optional[Exception] = None

        for j in range(n):
            i = (key_start_index + j) % n
            masked_key = _mask_api_key(GROQ_API_KEYS[i])
            logger.info("Streaming with API key #%d/%d: %s", i + 1, n, masked_key)

            try:
                chain = prompt | self.llms[i]
                chunk_count = 0
                first_chunk_time: Optional[float] = None
                stream_start = time.perf_counter()
                accumulated = ""
                last_check_len = 0
                repetition_stopped = False

                for chunk in chain.stream({"history": messages, "question": question}):
                    if hasattr(chunk, "content"):
                        content: str = chunk.content or ""
                    elif isinstance(chunk, dict):
                        content = chunk.get("content", "") or ""
                    else:
                        content = ""

                    if not isinstance(content, str) or not content:
                        continue

                    if first_chunk_time is None:
                        first_chunk_time = time.perf_counter() - stream_start
                        _log_timing("first_chunk", first_chunk_time)

                    chunk_count += 1
                    accumulated += content

                    if len(accumulated) - last_check_len >= _REPEAT_CHECK_INTERVAL:
                        last_check_len = len(accumulated)
                        if _detect_repetition_loop(accumulated):
                            logger.warning(
                                "[STREAM] Repetition loop detected after %d chars – stopping",
                                len(accumulated),
                            )
                            repetition_stopped = True
                            break

                    yield content

                total_stream = time.perf_counter() - stream_start
                _log_timing(
                    "groq_stream_total",
                    total_stream,
                    f"chunks: {chunk_count}" + (", TRUNCATED-REPETITION" if repetition_stopped else ""),
                )

                if i > 0 and chunk_count > 0:
                    logger.info(
                        "Fallback successful: API key #%d/%d streamed: %s", i + 1, n, masked_key
                    )
                return  # success – stop trying further keys

            except Exception as exc:
                last_exc = exc
                if _is_rate_limit_error(exc):
                    logger.warning("API key #%d/%d rate limited: %s", i + 1, n, masked_key)
                else:
                    logger.warning(
                        "API key #%d/%d failed: %s – %s", i + 1, n, masked_key, str(exc)[:100]
                    )
                if i < n - 1:
                    logger.info("Falling back to next API key for stream…")
                    continue
                break

        logger.error("All %d API key(s) failed during stream.", n)
        raise AllGroqApisFailedError(ALL_APIS_FAILED_MESSAGE) from last_exc

    # ------------------------------------------------------------------
    # Internal: prompt builder
    # ------------------------------------------------------------------
    def _build_prompt_and_messages(
        self,
        question: str,
        chat_history: Optional[List[tuple]] = None,
        extra_system_parts: Optional[List[str]] = None,
        mode_addendum: str = "",
    ) -> tuple:
        # Build system message
        time_info = get_time_information()
        system_message = JARVIS_SYSTEM_PROMPT
        system_message += f"\n\nCurrent time and date: {time_info}"

        if extra_system_parts:
            system_message += "\n\n" + "\n\n".join(extra_system_parts)
        if mode_addendum:
            system_message += f"\n\n{mode_addendum}"

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_message),
            MessagesPlaceholder(variable_name="history"),
            ("human", "{question}"),
        ])

        messages: list = []
        if chat_history:
            for human_msg, ai_msg in chat_history:
                messages.append(HumanMessage(content=human_msg))
                messages.append(AIMessage(content=ai_msg))

        logger.info(
            "[PROMPT] System message length: %d chars | History pairs: %d | Question: %.100s",
            len(system_message),
            len(chat_history) if chat_history else 0,
            question,
        )
        return prompt, messages

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get_response(
        self,
        question: str,
        chat_history: Optional[List[tuple]] = None,
        key_start_index: int = 0,
    ) -> str:
        try:
            prompt, messages = self._build_prompt_and_messages(
                question, chat_history, mode_addendum=GENERAL_CHAT_ADDENDUM
            )
            t0 = time.perf_counter()
            result = self._invoke_llm(prompt, messages, question, key_start_index=key_start_index)
            _log_timing("groq_api", time.perf_counter() - t0)
            logger.info(
                "[RESPONSE] General chat | Length: %d chars | Preview: %.120s", len(result), result
            )
            return result
        except AllGroqApisFailedError:
            raise
        except Exception as exc:
            raise Exception(f"Error getting response from Groq: {exc}") from exc

    def stream_response(
        self,
        question: str,
        chat_history: Optional[List[tuple]] = None,
        key_start_index: int = 0,
    ) -> Iterator[str]:
        try:
            prompt, messages = self._build_prompt_and_messages(
                question, chat_history, mode_addendum=GENERAL_CHAT_ADDENDUM
            )
            yield {"_activity": {"event": "context_retrieved", "message": "Retrieved relevant context from knowledge base"}}
            yield from self._stream_llm(prompt, messages, question, key_start_index=key_start_index)
        except AllGroqApisFailedError:
            raise
        except Exception as exc:
            raise Exception(f"Error streaming response from Groq: {exc}") from exc

    def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 1500,
    ) -> str:
        """
        Thread-safe text generation using the raw Groq SDK client.
        Safe to call from background threads (e.g. the wake-word daemon thread)
        because it does NOT use LangChain or asyncio under the hood.
        """
        system = system_prompt or JARVIS_SYSTEM_PROMPT
        n = len(self._raw_clients)

        for i, client in enumerate(self._raw_clients):
            masked_key = _mask_api_key(GROQ_API_KEYS[i])
            try:
                response = client.chat.completions.create(
                    model=GROQ_MODEL,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user",   "content": prompt},
                    ],
                    max_tokens=max_tokens,
                    temperature=0.5,
                )
                result = response.choices[0].message.content or ""
                logger.info(
                    "[GROQ] generate_text OK (key #%d/%d) | %d chars", i + 1, n, len(result)
                )
                return result

            except Exception as exc:
                if _is_rate_limit_error(exc):
                    logger.warning(
                        "[GROQ] generate_text key #%d/%d rate-limited (%s), trying next…",
                        i + 1, n, masked_key,
                    )
                else:
                    logger.warning(
                        "[GROQ] generate_text key #%d/%d failed (%s): %s",
                        i + 1, n, masked_key, str(exc)[:120],
                    )

        logger.error("[GROQ] generate_text — all %d key(s) exhausted.", n)
        return "I'm sorry, I couldn't process that request right now. All API keys are unavailable."