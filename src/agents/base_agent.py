"""
BaseAgent — the abstract base every agent extends (CLAUDE.md §6).

Provides the shared plumbing:
  - call_llm(prompt)          real Anthropic call via ChatAnthropic, with retries
  - run(state)                abstract; each agent implements its own logic
  - log_step(message)         no-op hook (logging intentionally omitted)
  - handle_error(state, err)  consistent error capture into state.errors

Agents contain reasoning; mechanical work (clone/extract/scan/assemble) stays
in plain helper functions, not here.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from src.config.settings import settings
from src.models.graph_state import GraphState


class BaseAgent(ABC):
    """Abstract base for all pipeline agents."""

    # Maps a task-size tier to the configured model id.
    _TIERS = {
        "small": lambda: settings.MODEL_SMALL,
        "medium": lambda: settings.MODEL_MEDIUM,
        "large": lambda: settings.MODEL_LARGE,
    }

    def __init__(self, name: str | None = None, model_tier: str = "medium"):
        """
        model_tier picks which Claude model this agent uses:
          "small"  -> simple/mechanical prompts (Haiku)
          "medium" -> most drafting/summarizing   (Sonnet, default)
          "large"  -> hard reasoning-heavy work   (Opus)
        """
        self.name = name or self.__class__.__name__
        if model_tier not in self._TIERS:
            raise ValueError(
                f"Unknown model_tier '{model_tier}'. Use small | medium | large."
            )
        self.model_tier = model_tier
        self.model_name = self._TIERS[model_tier]()

        # ChatAnthropic is cheap to construct and holds no per-request state.
        llm_kwargs = {
            "model": self.model_name,
            "api_key": settings.ANTHROPIC_API_KEY,
            "timeout": 60,
            "max_retries": 0,  # we do our own retry loop below
        }
        self._llm = ChatAnthropic(**llm_kwargs)

    # ------------------------------------------------------------------ #
    # Abstract API                                                        #
    # ------------------------------------------------------------------ #
    @abstractmethod
    def run(self, state: GraphState) -> GraphState:
        """Execute this agent's work and return the updated state."""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # LLM access                                                          #
    # ------------------------------------------------------------------ #
    def call_llm(self, prompt: str, system: str | None = None) -> str:
        """
        Send a prompt to the LLM and return its text response.

        Retries transient failures up to settings.MAX_RETRIES with exponential
        backoff. Raises the last exception if all attempts fail — callers that
        want soft-failure should wrap this in handle_error().
        """
        messages = []
        if system:
            messages.append(SystemMessage(content=system))
        messages.append(HumanMessage(content=prompt))

        last_error: Exception | None = None
        for attempt in range(1, settings.MAX_RETRIES + 1):
            try:
                response = self._llm.invoke(messages)
                # ChatAnthropic returns an AIMessage; .content is the text.
                content = response.content
                if isinstance(content, list):
                    # Some responses come back as content blocks; join text parts.
                    content = "".join(
                        block.get("text", "") if isinstance(block, dict) else str(block)
                        for block in content
                    )
                return content.strip()
            except Exception as exc:  # noqa: BLE001 - retry on any transient error
                last_error = exc
                if attempt < settings.MAX_RETRIES:
                    time.sleep(2 ** (attempt - 1))  # 1s, 2s, 4s, ...

        # Exhausted retries.
        raise last_error if last_error else RuntimeError("LLM call failed")

    # ------------------------------------------------------------------ #
    # Error handling                                                      #
    # ------------------------------------------------------------------ #
    def log_step(self, message: str) -> None:
        """No-op hook kept for API compatibility (logging omitted)."""
        return None

    def handle_error(self, state: GraphState, error: Exception) -> GraphState:
        """Capture an error into state.errors without crashing the pipeline."""
        entry = {"agent": self.name, "error": str(error), "type": type(error).__name__}
        state.errors.append(entry)
        return state
