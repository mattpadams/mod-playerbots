"""Provider-agnostic @tool decorator.

Drop-in replacement for ``claude_agent_sdk.tool``.  Attaches metadata to
the decorated function so that each LLM provider can register tools in
its own way (MCP server for Claude, function-calling for OpenAI, etc.).
"""


def tool(name: str, description: str, input_schema: dict):
    """Decorate an async callable as an LLM-invocable tool.

    Usage::

        @tool(
            name="say",
            description="Speak aloud in the game world.",
            input_schema={
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
            },
        )
        async def say(args):
            ...
            return {"content": [{"type": "text", "text": "Done."}]}
    """

    def decorator(fn):
        fn.tool_name = name
        fn.tool_description = description
        fn.tool_input_schema = input_schema
        fn.name = name  # backward compat
        return fn

    return decorator
