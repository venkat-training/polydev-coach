"""
PolyDev Coach - Gradient AI Client
Handles all HTTP communication with DigitalOcean Gradient AI agents.
"""
import json
import logging
import re
from typing import Any, Dict

import httpx

from config import settings

logger = logging.getLogger(__name__)

# Timeout for agent calls (agents can be slow on first call)
AGENT_TIMEOUT = 120.0


def _strip_markdown_fences(text: str) -> str:
    """Remove ```json ... ``` wrappers that models sometimes add."""
    text = text.strip()
    # Remove leading ```json or ``` fence
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    # Remove trailing ``` fence
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


async def call_agent(agent_id: str, user_message: str) -> Dict[str, Any]:
    """
    Call a single Gradient AI agent and return parsed JSON response.

    The Gradient AI agent endpoint follows the OpenAI-compatible chat format.
    Docs: https://docs.digitalocean.com/products/gradient-ai-platform/how-to/use-agents/
    """
    url = f"{settings.gradient_base_url}/agents/{agent_id}/chat"
    payload = {
        "messages": [{"role": "user", "content": user_message}],
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {settings.gradient_api_key}",
        "Content-Type": "application/json",
    }

    logger.debug("Calling agent %s | URL: %s", agent_id, url)

    async with httpx.AsyncClient(timeout=AGENT_TIMEOUT) as client:
        try:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Gradient agent %s returned HTTP %s: %s",
                agent_id, exc.response.status_code, exc.response.text
            )
            raise

    data = response.json()

    # Extract text content from OpenAI-compatible response
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        logger.error("Unexpected response shape from agent %s: %s", agent_id, data)
        raise ValueError(f"Unexpected Gradient response shape: {data}") from exc

    # Parse JSON — strip markdown fences if present
    clean = _strip_markdown_fences(content)
    try:
        return json.loads(clean)
    except json.JSONDecodeError as exc:
        logger.error(
            "Agent %s returned non-JSON:\n%s", agent_id, content[:500]
        )
        raise ValueError(
            f"Agent {agent_id} did not return valid JSON. "
            f"Raw response (truncated): {content[:300]}"
        ) from exc


async def call_serverless_inference(prompt: str, model: str = "llama3-70b-instruct") -> str:
    """
    Direct serverless inference (no agent) — used for lightweight tasks.
    Docs: https://docs.digitalocean.com/products/gradient-ai-platform/how-to/use-serverless-inference/
    """
    url = f"{settings.gradient_base_url}/inference/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {
        "Authorization": f"Bearer {settings.gradient_api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=AGENT_TIMEOUT) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()

    data = response.json()
    return data["choices"][0]["message"]["content"]
