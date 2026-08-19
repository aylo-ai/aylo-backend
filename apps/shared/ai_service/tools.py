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
    _REGISTRY[name] = Tool(name=name, schema=schema, handler=handler, available=available)


def registered_names() -> List[str]:
    return sorted(_REGISTRY)


def is_openai_store(vector_id) -> bool:
    return bool(vector_id) and str(vector_id).startswith("vs_")


def build_tools(assistant) -> List[Dict[str, Any]]:
    tools: List[Dict[str, Any]] = []

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
    tool = _REGISTRY.get(name)
    if tool is None:
        logger.warning("Model called unknown tool %r", name)
        return {"error": f"Unknown tool: {name}"}

    try:
        return tool.handler(assistant, conversation, args or {})
    except Exception as exc:
        logger.exception("Tool %s failed for conversation %s", name, conversation.id)
        return {"error": f"{name} failed: {exc}"}
