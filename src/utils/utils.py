import json
import uuid


def create_ndjson_str(obj: dict) -> str:
    """
    Converts the object to Newline-delimited JSON (ndjson) format.
    e.g. {"name": "Alice"} -> '{"name": "Alice"}\n'
    Args:
        obj (dict): The JSON object.
    Returns:
        str: A stringified Newline-delimited JSON.
    """
    return f"{json.dumps(obj)}\n"


def create_session_id() -> str:
    """
    Generates a new session ID.
    Returns:
        str: A new session ID.
    """
    return str(uuid.uuid4())
