import asyncio
import json
from config.settings import client



tools = [
    {
        "type": "function",
        "function": {
            "name": "list_schemas",
            "description": "List all schemas in the database",
            "parameters": {
                "type": "object",
                "properties": {},
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_objects",
            "description": "List objects in a schema",
            "parameters": {
                "type": "object",
                "properties": {
                    "schema_name": {"type": "string", "description": "Schema name"},
                    "object_type": {"type": "string", "description": "Object type: 'table', 'view', 'sequence', or 'extension'"}
                },
                "required": ["schema_name", "object_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_object_details",
            "description": "Show detailed information about a database object",
            "parameters": {
                "type": "object",
                "properties": {
                    "schema_name": {"type": "string", "description": "Schema name"},
                    "object_name": {"type": "string", "description": "Object name"},
                    "object_type": {"type": "string", "description": "Object type: 'table', 'view', 'sequence', or 'extension'"}
                },
                "required": ["schema_name", "object_name", "object_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_sql",
            "description": "Execute a SQL query against the database.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "query execute"}
                },
                "required": ["query"]
            }
        }
    },
    {"type": "file_search"}
]
