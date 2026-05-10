"""
realtime_service.py
-------------------
Extends GroqService with real-time web search via Tavily and smart query
extraction using a fast lightweight Groq model.
"""

import logging
import os
import time
from typing import Any, Dict, Iterator, List, Optional, Tuple

from tavily import TavilyClient

from app.services.groq_service import AllGroqApisFailedError, GroqService, escape_curly_braces
# from app.services.vector_store import VectorStoreService  # Decommissioned
from app.utils.retry import with_retry
from config import GROQ_API_KEYS, GROQ_MODEL, INTENT_CLASSIFY_MODEL, REALTIME_CHAT_ADDENDUM

logger = logging.getLogger("J.A.R.V.I.S")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
GROQ_REQUEST_TIMEOUT_FAST = 15

_QUERY_EXTRACTION_PROMPT = (
    "You are a search query optimizer. Convert the user's message into a clean, "
    "focused web search query (max 10 words). Rules:\n"
    "- Remove filler words (you know, like, something, can you, tell me, search)\n"
    "- Add specifics: dates (today, 2026), event names, full names\n"
    "- For sports: include league name, team names, 'live score today'\n"
    "- For people: include full name + what user wants to know\n"
    "- Resolve references (him, that, it) from conversation history\n"
    "Output ONLY the search query. Nothing else."
)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------
class RealtimeGroqService(GroqService):
    """GroqService extended with Tavily web search for real-time queries."""

    def __init__(self) -> None:
        super().__init__()

        # Tavily client
        tavily_api_key = os.getenv("TAVILY_API_KEY", "")
        if tavily_api_key:
            self.tavily_client: Optional[TavilyClient] = TavilyClient(api_key=tavily_api_key)
            logger.info("Tavily search client initialised successfully")
        else:
            self.tavily_client = None
            logger.warning("TAVILY_API_KEY not set. Realtime search will be unavailable.")

        # Fast LLM for query extraction / intent classification
        if GROQ_API_KEYS:
            from langchain_groq import ChatGroq  # local import to avoid circular deps

            self._fast_llm = ChatGroq(
                groq_api_key=GROQ_API_KEYS[0],
                model_name=INTENT_CLASSIFY_MODEL,
                temperature=0.0,
                max_tokens=50,
                request_timeout=GROQ_REQUEST_TIMEOUT_FAST,
            )
        else:
            self._fast_llm = None

    # ------------------------------------------------------------------
    # Query extraction
    # ------------------------------------------------------------------
    def _extract_search_query(
        self, question: str, chat_history: Optional[List[tuple]] = None
    ) -> str:
        """Distil *question* into a focused web-search query string."""
        if not self._fast_llm:
            return question

        q = question.strip()
        q_lower = q.lower()

        filler_phrases = (
            " it ", " that ", " him ", " you know ", " her ", " them ",
            "can you ", " tell me ", " something ", " like ", " going on ",
            " search ", " right now ", " please ",
        )
        has_filler = any(p in q_lower for p in filler_phrases)

        # Short, clean queries can be used as-is
        if len(q) <= 30 and not has_filler:
            return q

        try:
            t0 = time.perf_counter()

            history_context = ""
            if chat_history:
                recent = chat_history[-3:]
                parts: List[str] = []
                for human, assistant in recent:
                    parts.append(f"User: {human[:200]}")
                    parts.append(f"Assistant: {assistant[:200]}")
                history_context = "\n".join(parts)

            if history_context:
                full_prompt = (
                    f"{_QUERY_EXTRACTION_PROMPT}\n\n"
                    f"Recent conversation:\n{history_context}\n\n"
                    f"User's latest message: {question}\n\n"
                    f"Search query:"
                )
            else:
                full_prompt = (
                    f"{_QUERY_EXTRACTION_PROMPT}\n\n"
                    f"User's message: {question}\n\n"
                    f"Search query:"
                )

            response = self._fast_llm.invoke(full_prompt)
            extracted: str = response.content.strip().strip('"').strip("'")

            if extracted and 3 <= len(extracted) <= 200:
                logger.info(
                    "[REALTIME] Query extraction: '%s' -> '%s' (%.3fs)",
                    question[:80], extracted[:80], time.perf_counter() - t0,
                )
                return extracted

            logger.warning("[REALTIME] Query extraction returned unusable result – using raw question")
            return question

        except Exception as exc:
            logger.warning("[REALTIME] Query extraction failed (%s) – using raw question", exc)
            return question

    # ------------------------------------------------------------------
    # Tavily search
    # ------------------------------------------------------------------
    def search_tavily(
        self, query: str, num_results: int = 5
    ) -> Tuple[str, Optional[Dict]]:
        """Run a Tavily web search and return (formatted_text, raw_payload)."""
        if not self.tavily_client:
            logger.warning("Tavily client not initialised – TAVILY_API_KEY not set.")
            return "", None

        if not query or not str(query).strip():
            return "", None

        try:
            t0 = time.perf_counter()
            response = with_retry(
                lambda: self.tavily_client.search(
                    query=query,
                    search_depth="fast",
                    max_results=num_results,
                    include_answer=True,
                    include_raw_content=False,
                ),
                max_retries=3,
                initial_delay=1.0,
            )

            results: List[Dict] = response.get("results", [])
            ai_answer: str = response.get("answer", "")

            if not results and not ai_answer:
                logger.warning("No Tavily search results for query: %s", query)
                return "", None

            payload: Dict = {
                "query": query,
                "answer": ai_answer,
                "results": [
                    {
                        "title": r.get("title", "No title"),
                        "content": (r.get("content") or "")[:300],
                        "url": r.get("url", ""),
                        "score": round(float(r.get("score", 0)), 2),
                    }
                    for r in results[:num_results]
                ],
            }

            parts: List[str] = [f"=== WEB SEARCH RESULTS FOR: {query} ===\n"]
            if ai_answer:
                parts.append(
                    f"AI-SYNTHESIZED ANSWER (use this as your primary source):\n{ai_answer}\n"
                )
            if results:
                parts.append("INDIVIDUAL SOURCES:")
                for idx, result in enumerate(results[:num_results], start=1):
                    title = result.get("title", "No title")
                    content = result.get("content", "")
                    url = result.get("url", "")
                    score = result.get("score", 0)
                    parts.append(f"\n[Source {idx}] (relevance: {score:.2f})")
                    parts.append(f"Title: {title}")
                    if content:
                        parts.append(f"Content: {content}")
                    if url:
                        parts.append(f"URL: {url}")
            parts.append("\n=== END SEARCH RESULTS ===")

            formatted = "\n".join(parts)
            logger.info(
                "[TAVILY] %d results, AI answer: %s, formatted: %d chars (%.3fs)",
                len(results),
                "yes" if ai_answer else "no",
                len(formatted),
                time.perf_counter() - t0,
            )
            return formatted, payload

        except Exception as exc:
            logger.error("Error performing Tavily search: %s", exc)
            return "", None

    # ------------------------------------------------------------------
    # Public: pre-fetch (for parallel execution patterns)
    # ------------------------------------------------------------------
    def prefetch_web_search(
        self, question: str, chat_history: Optional[List[tuple]] = None
    ) -> Tuple[str, Optional[Dict]]:
        """Extract query and run Tavily search; useful for parallel pre-fetching."""
        try:
            t0 = time.perf_counter()
            search_query = self._extract_search_query(question, chat_history)
            logger.info(
                "[REALTIME] Pre-fetch: extracted query '%s' in %.3fs",
                search_query[:60], time.perf_counter() - t0,
            )
            formatted_results, payload = self.search_tavily(search_query, num_results=5)
            if formatted_results:
                logger.info(
                    "[REALTIME] Pre-fetch: Tavily returned %d chars in %.3fs total",
                    len(formatted_results), time.perf_counter() - t0,
                )
            return formatted_results or "", payload
        except Exception as exc:
            logger.warning("[REALTIME] Pre-fetch failed: %s", exc)
            return "", None

    # ------------------------------------------------------------------
    # Public: non-streaming response
    # ------------------------------------------------------------------
    def get_response(
        self,
        question: str,
        chat_history: Optional[List[tuple]] = None,
        key_start_index: int = 0,
    ) -> str:
        try:
            search_query = self._extract_search_query(question, chat_history)
            logger.info("[REALTIME] Searching Tavily for: %s", search_query)

            formatted_results, _ = self.search_tavily(search_query, num_results=5)
            if formatted_results:
                logger.info("[REALTIME] Tavily returned results (length: %d chars)", len(formatted_results))
            else:
                logger.warning("[REALTIME] Tavily returned no results for: %s", search_query)

            extra_parts = [escape_curly_braces(formatted_results)] if formatted_results else None
            prompt, messages = self._build_prompt_and_messages(
                question, chat_history,
                extra_system_parts=extra_parts,
                mode_addendum=REALTIME_CHAT_ADDENDUM,
            )

            t0 = time.perf_counter()
            response_content = self._invoke_llm(
                prompt, messages, question, key_start_index=key_start_index
            )
            logger.info("[TIMING] groq_api: %.3fs", time.perf_counter() - t0)
            logger.info(
                "[RESPONSE] Realtime chat | Length: %d chars | Preview: %.120s",
                len(response_content), response_content,
            )
            return response_content

        except AllGroqApisFailedError:
            raise
        except Exception as exc:
            logger.error("Error in realtime get_response: %s", exc, exc_info=True)
            raise

    # ------------------------------------------------------------------
    # Public: streaming response (with internal search)
    # ------------------------------------------------------------------
    def stream_response(
        self,
        question: str,
        chat_history: Optional[List[tuple]] = None,
        key_start_index: int = 0,
    ) -> Iterator[Any]:
        try:
            yield {"_activity": {"event": "extracting_query", "message": "Extracting search query..."}}

            search_query = self._extract_search_query(question, chat_history)
            logger.info("[REALTIME] Searching Tavily for: %s", search_query)

            yield {
                "_activity": {
                    "event": "searching_web",
                    "query": search_query,
                    "message": f"Searching web for: {search_query}",
                }
            }

            formatted_results, payload = self.search_tavily(search_query, num_results=5)
            num_results = len(payload.get("results", [])) if payload else 0

            if formatted_results:
                logger.info("[REALTIME] Tavily returned results (length: %d chars)", len(formatted_results))
                yield {
                    "_activity": {
                        "event": "search_completed",
                        "message": f"Search completed: {num_results} results, {len(formatted_results)} chars of context",
                    }
                }
            else:
                logger.warning("[REALTIME] Tavily returned no results for: %s", search_query)
                yield {"_activity": {"event": "search_completed", "message": "No search results found"}}

            if payload:
                yield {"_search_results": payload}

            extra_parts = [escape_curly_braces(formatted_results)] if formatted_results else None
            prompt, messages = self._build_prompt_and_messages(
                question, chat_history,
                extra_system_parts=extra_parts,
                mode_addendum=REALTIME_CHAT_ADDENDUM,
            )

            yield from self._stream_llm(prompt, messages, question, key_start_index=key_start_index)
            logger.info("[REALTIME] Stream completed for: %s", search_query)

        except AllGroqApisFailedError:
            raise
        except Exception as exc:
            logger.error("Error in realtime stream_response: %s", exc, exc_info=True)
            raise

    # ------------------------------------------------------------------
    # Public: streaming response (with pre-fetched search results)
    # ------------------------------------------------------------------
    def stream_response_with_prefetched(
        self,
        question: str,
        chat_history: Optional[List[tuple]] = None,
        formatted_results: Optional[str] = None,
        payload: Optional[Dict] = None,
        key_start_index: int = 0,
    ) -> Iterator[Any]:
        try:
            extra_parts = [escape_curly_braces(formatted_results)] if formatted_results else None
            prompt, messages = self._build_prompt_and_messages(
                question, chat_history,
                extra_system_parts=extra_parts,
                mode_addendum=REALTIME_CHAT_ADDENDUM,
            )
            yield from self._stream_llm(prompt, messages, question, key_start_index=key_start_index)
            logger.info("[REALTIME] Stream completed (pre-fetched results)")

        except AllGroqApisFailedError:
            raise
        except Exception as exc:
            logger.error(
                "Error in realtime stream_response_with_prefetched: %s", exc, exc_info=True
            )
            raise