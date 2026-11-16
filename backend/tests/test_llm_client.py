from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from app.agents.evaluator import ReportSummary
from app.config import Settings
from app.llm import LLMClient, LLMError, LLMRefusalError
from app.llm.pricing import cost_usd


class FakeMessages:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.kwargs = response, error, None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.response


def make_client(response=None, error=None, **settings):
    messages = FakeMessages(response, error)
    sdk = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    return LLMClient(Settings(**settings), client=sdk), messages


def response(stop_reason="end_turn", parsed=None):
    usage = SimpleNamespace(input_tokens=1000, output_tokens=500, cache_read_input_tokens=2000,
                            cache_creation_input_tokens=None)
    return SimpleNamespace(stop_reason=stop_reason, parsed_output=parsed, model="claude-opus-5-5", usage=usage)


def call(llm):
    return llm.structured(agent="report", prompt="report.v1", messages=[{"role": "user", "content": "x"}],
                          output_model=ReportSummary, effort="low")


def test_success_returns_output_and_cost():
    parsed = ReportSummary(strengths=[], weaknesses=[], summary="ok")
    llm, messages = make_client(response(parsed=parsed))
    result = call(llm)
    assert result.output is parsed
    assert result.usage.cost_usd == pytest.approx((1000 * 4 + 500 * 20 + 2000 * 0.2) / 1e6)
    assert messages.kwargs["model"] == "claude-opus-5-5"
    assert messages.kwargs["output_config"] == {"effort": "low"}
    assert messages.kwargs["fallbacks"] == "default"
    assert messages.kwargs["output_format"] is ReportSummary
    assert "MockMate" in messages.kwargs["system"]


def test_fallbacks_can_be_disabled():
    llm, messages = make_client(response(parsed=ReportSummary(strengths=[], weaknesses=[], summary="")),
                                llm_fallbacks=False)
    call(llm)
    assert "fallbacks" not in messages.kwargs and "betas" not in messages.kwargs


def test_refusal_raises_with_usage():
    llm, _ = make_client(response(stop_reason="refusal"))
    with pytest.raises(LLMRefusalError) as exc:
        call(llm)
    assert exc.value.usage.output_tokens == 500


def test_truncated_output_raises():
    llm, _ = make_client(response(stop_reason="max_tokens"))
    with pytest.raises(LLMError):
        call(llm)


def test_api_error_becomes_llm_error():
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic.InternalServerError("overloaded", response=httpx2.Response(529, request=request), body=None)
    llm, _ = make_client(error=err)
    with pytest.raises(LLMError):
        call(llm)


def test_missing_credentials_becomes_llm_error():
    llm, _ = make_client(error=TypeError("Could not resolve authentication method."))
    with pytest.raises(LLMError):
        call(llm)


def test_other_type_errors_propagate():
    llm, _ = make_client(error=TypeError("bad argument"))
    with pytest.raises(TypeError):
        call(llm)


def test_unknown_model_uses_default_prices():
    assert cost_usd("mystery", 1_000_000, 0, 0, 0) == 4.0
