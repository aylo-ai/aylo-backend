"""Fixtures and fake OpenAI objects shared by the agent tests.

`make_response` mirrors the shape the Responses API returns closely enough that the
agent cannot tell the difference, which keeps every test offline and free.
"""
import json
from types import SimpleNamespace
from typing import Any, Dict, Iterable, Optional, Tuple

import httpx
from openai import APIStatusError, BadRequestError, RateLimitError

from apps.assistant.models import Assistant, Conversation
from shared.addons.enums import ConversationStatuses


def make_assistant(**overrides) -> Assistant:
    defaults = {
        "name": "Repli Bot",
        "company_name": "Repli",
        "system_prompt": "You sell phones.",
        "fallback_message": "Sorry, please try again shortly.",
        "vector_id": "vs_test",
        "web_search_tool": False,
    }
    defaults.update(overrides)
    return Assistant.objects.create(**defaults)


def make_conversation(assistant, **overrides) -> Conversation:
    defaults = {
        "assistant": assistant,
        "status": ConversationStatuses.OPEN.value,
        "platform": "telegram",
        "user_id": "12345",
        "username": "customer",
    }
    defaults.update(overrides)
    return Conversation.objects.create(**defaults)


def make_response(
    response_id: str = "resp_1",
    text: Optional[str] = None,
    function_calls: Iterable[Tuple[str, Dict[str, Any], str]] = (),
    input_tokens: int = 100,
    output_tokens: int = 20,
    cached_tokens: int = 0,
) -> SimpleNamespace:
    """Build a fake Response. `function_calls` is (name, args, call_id) triples."""
    output = [
        SimpleNamespace(
            type="function_call", name=name, arguments=json.dumps(args), call_id=call_id
        )
        for name, args, call_id in function_calls
    ]

    if text is not None:
        output.append(
            SimpleNamespace(
                type="message",
                role="assistant",
                content=[SimpleNamespace(type="output_text", text=text)],
            )
        )

    return SimpleNamespace(
        id=response_id,
        output=output,
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_tokens_details=SimpleNamespace(cached_tokens=cached_tokens),
        ),
    )


def _http_response(status: int) -> httpx.Response:
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    return httpx.Response(status, request=request)


def bad_request(message: str) -> BadRequestError:
    return BadRequestError(message, response=_http_response(400), body=None)


def rate_limited() -> RateLimitError:
    return RateLimitError("slow down", response=_http_response(429), body=None)


def server_error() -> APIStatusError:
    return APIStatusError("upstream boom", response=_http_response(503), body=None)
