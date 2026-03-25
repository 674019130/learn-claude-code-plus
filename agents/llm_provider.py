"""
LLM Provider abstraction layer.

Supports both Anthropic and OpenAI APIs with a unified interface.
Set PROVIDER=openai or PROVIDER=anthropic in .env to switch.

Anthropic format (native):
  - response.stop_reason == "tool_use"
  - block.type == "tool_use", block.name, block.input, block.id
  - tool_result: {"type": "tool_result", "tool_use_id": ..., "content": ...}

OpenAI format (adapted to match Anthropic):
  - response.stop_reason == "tool_use"  (mapped from finish_reason == "tool_calls")
  - block.type == "tool_use", block.name, block.input, block.id
  - tool_result: same format, internally converted to OpenAI's tool message
"""

import json
import os
from dataclasses import dataclass, field


# -- Unified response objects (match Anthropic's format) --

@dataclass
class ToolUseBlock:
    type: str  # "tool_use"
    id: str
    name: str
    input: dict


@dataclass
class TextBlock:
    type: str  # "text"
    text: str


@dataclass
class LLMResponse:
    content: list  # list of ToolUseBlock | TextBlock
    stop_reason: str  # "tool_use" | "end_turn"
    usage: dict = field(default_factory=dict)


# -- Provider implementations --

class AnthropicProvider:
    def __init__(self):
        from anthropic import Anthropic
        self.client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))

    def create(self, model, system, messages, tools, max_tokens=8000):
        anthropic_tools = _to_anthropic_tools(tools)
        response = self.client.messages.create(
            model=model, system=system, messages=messages,
            tools=anthropic_tools, max_tokens=max_tokens,
        )
        # Already in native format, just return as-is
        return response


class OpenAIProvider:
    def __init__(self):
        from openai import OpenAI
        self.client = OpenAI()  # uses OPENAI_API_KEY from env

    def create(self, model, system, messages, tools, max_tokens=8000):
        oai_tools = _to_openai_tools(tools)
        oai_messages = _to_openai_messages(system, messages)

        response = self.client.chat.completions.create(
            model=model, messages=oai_messages,
            tools=oai_tools if oai_tools else None,
            max_tokens=max_tokens,
        )

        return _from_openai_response(response)


# -- Format converters --

def _to_anthropic_tools(tools):
    """Tools are already in Anthropic format (input_schema), pass through."""
    return tools


def _to_openai_tools(tools):
    """Convert Anthropic tool format to OpenAI function calling format."""
    if not tools:
        return None
    oai_tools = []
    for tool in tools:
        oai_tools.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
            }
        })
    return oai_tools


def _to_openai_messages(system, messages):
    """Convert Anthropic message format to OpenAI format."""
    oai_messages = [{"role": "system", "content": system}]

    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        if role == "assistant":
            # Anthropic: content is a list of blocks (TextBlock, ToolUseBlock)
            if isinstance(content, list):
                text_parts = []
                tool_calls = []
                for block in content:
                    if hasattr(block, "type"):
                        # Anthropic SDK objects
                        if block.type == "text":
                            text_parts.append(block.text)
                        elif block.type == "tool_use":
                            tool_calls.append({
                                "id": block.id,
                                "type": "function",
                                "function": {
                                    "name": block.name,
                                    "arguments": json.dumps(block.input),
                                }
                            })
                    elif isinstance(block, dict):
                        # Our own ToolUseBlock/TextBlock converted to dict
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif block.get("type") == "tool_use":
                            tool_calls.append({
                                "id": block["id"],
                                "type": "function",
                                "function": {
                                    "name": block["name"],
                                    "arguments": json.dumps(block.get("input", {})),
                                }
                            })

                oai_msg = {"role": "assistant", "content": "\n".join(text_parts) if text_parts else None}
                if tool_calls:
                    oai_msg["tool_calls"] = tool_calls
                oai_messages.append(oai_msg)
            else:
                oai_messages.append({"role": "assistant", "content": content})

        elif role == "user":
            # Anthropic: user message with tool_results
            if isinstance(content, list) and content and isinstance(content[0], dict) and content[0].get("type") == "tool_result":
                for result in content:
                    oai_messages.append({
                        "role": "tool",
                        "tool_call_id": result["tool_use_id"],
                        "content": result.get("content", ""),
                    })
            else:
                oai_messages.append({"role": "user", "content": content})
        else:
            oai_messages.append({"role": role, "content": content})

    return oai_messages


def _from_openai_response(response):
    """Convert OpenAI response to Anthropic-compatible LLMResponse."""
    choice = response.choices[0]
    message = choice.message
    content = []

    # Text content
    if message.content:
        content.append(TextBlock(type="text", text=message.content))

    # Tool calls
    if message.tool_calls:
        for tc in message.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}
            content.append(ToolUseBlock(
                type="tool_use",
                id=tc.id,
                name=tc.function.name,
                input=args,
            ))

    # Map stop reason
    stop_reason = "tool_use" if message.tool_calls else "end_turn"

    return LLMResponse(
        content=content,
        stop_reason=stop_reason,
        usage={
            "input_tokens": response.usage.prompt_tokens if response.usage else 0,
            "output_tokens": response.usage.completion_tokens if response.usage else 0,
        }
    )


# -- Factory --

def create_provider():
    """Create the right provider based on PROVIDER env var."""
    provider = os.getenv("PROVIDER", "anthropic").lower()
    if provider == "openai":
        return OpenAIProvider()
    else:
        return AnthropicProvider()
