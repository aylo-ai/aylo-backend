"""Agent tool registry: mechanism only, no knowledge of any app.

Apps register their own tools at ``AppConfig.ready()`` (see
``apps/assistant/ai_tools.py``). This module never imports an app model, which is
what lets `shared` sit underneath every app instead of alongside them.

Two rules hold the tool layer together:

1. Tools are assembled per assistant, at call time. An assistant with no knowledge
   base never receives `file_search`, so it cannot call it and cannot crash on it.
2. A handler never raises. Failures come back to the model as `{"error": ...}` so it
   can apologise or try something else, instead of killing the whole turn.
"""
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

MAX_SUMMARY_MESSAGES = 20

Handler = Callable[[Any, Any, Dict[str, Any]], Dict[str, Any]]
Predicate = Callable[[Any], bool]


@dataclass(frozen=True)
class Tool:
    name: str
    schema: Dict[str, Any]
    handler: Handler
    # Whether this assistant may use the tool. None means "always".
    available: Optional[Predicate] = None

    def is_available_for(self, assistant) -> bool:
        if self.available is None:
            return True
        try:
            return bool(self.available(assistant))
        except Exception:
            logger.exception("Availability check for tool %s failed", self.name)
            return False


_REGISTRY: Dict[str, Tool] = {}


def register(name: str, schema: Dict[str, Any], handler: Handler,
             available: Optional[Predicate] = None) -> None:
    """Register one tool. Registering the same name twice replaces it.

    Called from ``AppConfig.ready()``, which Django may run more than once in a
    test process, so replacement has to be the defined behaviour rather than an
    error.
    """
    _REGISTRY[name] = Tool(name=name, schema=schema, handler=handler, available=available)


def registered_names() -> List[str]:
    return sorted(_REGISTRY)


def is_openai_store(vector_id) -> bool:
    """Whether this id is an OpenAI vector store rather than a legacy Gemini one.

    Assistants migrated from Gemini hold names like `fileSearchStores/abc-123`,
    which OpenAI rejects outright. Treating those as "no knowledge base" keeps the
    assistant answering while its files are re-indexed, instead of failing every turn.
    """
    return bool(vector_id) and str(vector_id).startswith("vs_")


def build_tools(assistant) -> List[Dict[str, Any]]:
    """Assemble the tool list this assistant is actually allowed to use."""
    tools: List[Dict[str, Any]] = []

    # Provider-native tools; not registrable, they have no handler of ours.
    if is_openai_store(assistant.vector_id):
        tools.append({"type": "file_search", "vector_store_ids": [assistant.vector_id]})
    elif assistant.vector_id:
        logger.warning(
            "Assistant %s has a non-OpenAI vector_id (%s); file_search disabled until "
            "`manage.py migrate_knowledge_bases` re-indexes its files",
            assistant.id, assistant.vector_id,
        )
    else:
        logger.info("Assistant %s has no vector_id; file_search not offered", assistant.id)

    if assistant.web_search_tool:
        tools.append({"type": "web_search"})

    for name in registered_names():
        tool = _REGISTRY[name]
        if tool.is_available_for(assistant):
            tools.append(tool.schema)

    return tools


def execute(name: str, assistant, conversation, args: Dict[str, Any]) -> Dict[str, Any]:
    """Run a tool by name. Always returns a dict; never raises."""
    tool = _REGISTRY.get(name)
    if tool is None:
        logger.warning("Model called unknown tool %r", name)
        return {"error": f"Unknown tool: {name}"}

    try:
        return tool.handler(assistant, conversation, args or {})
    except Exception as exc:
        logger.exception("Tool %s failed for conversation %s", name, conversation.id)
        return {"error": f"{name} failed: {exc}"}
