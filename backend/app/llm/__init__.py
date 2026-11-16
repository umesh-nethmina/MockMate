from functools import lru_cache

from app.config import get_settings
from app.llm.client import LLM, LLMClient, LLMError, LLMRefusalError, LLMResult, LLMUsage

__all__ = ["LLM", "LLMClient", "LLMError", "LLMRefusalError", "LLMResult", "LLMUsage", "get_llm"]


@lru_cache
def get_llm() -> LLM:
    """FastAPI dependency; tests override it with a fake."""
    return LLMClient(get_settings())
