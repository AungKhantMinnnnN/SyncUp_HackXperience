"""Foundry hosted agent (Azure AI Projects SDK) -> standard OpenAI Responses client.

Auth is Entra ID via DefaultAzureCredential — `az login` locally, a service principal
(AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET env vars) on Render. No API key.
`get_openai_client()` returns the plain OpenAI SDK client; calls reference the hosted
agent (SyncUp-Agent) via extra_body, matching the sample on the Foundry agent page.

Rules (see CLAUDE.md): request JSON against a Pydantic schema, temperature 0.1-0.3,
validate + retry 2x, log every call. The model parses and explains; it never computes.
"""

import logging
from functools import lru_cache

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.org import AiInteraction

logger = logging.getLogger("syncup.llm")

# The hosted-agent (agent_reference) Responses path rejects these two things, and it has
# cost us a 400/500 in every feature agent: structured-output params, and chat-style
# message-list input. The guard below normalizes both so a caller can't reintroduce it.
_BANNED_KWARGS = ("text", "response_format")


def _as_prompt(value) -> str:
    """Normalize input to a single string. A chat-style [{role, content}, ...] list is
    flattened to its content joined — the agent path doesn't accept the list shape."""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        parts = []
        for m in value:
            parts.append(str(m.get("content", m)) if isinstance(m, dict) else str(m))
        return "\n\n".join(parts)
    return str(value)


@lru_cache
def get_client():
    """The OpenAI-compatible client, built lazily so the app boots without Foundry
    configured (health check, migrations)."""
    project = AIProjectClient(
        endpoint=settings.foundry_project_endpoint,
        credential=DefaultAzureCredential(),
    )
    return project.get_openai_client()


def agent_response(input, **kwargs):
    """Call the hosted SyncUp agent via the Responses API. Pass `input` as a plain
    string prompt (ask for JSON in the prompt and parse output_text — the agent path
    does NOT support structured-output params like text=/response_format, nor chat-style
    message lists). This function normalizes both defensively. Sync client — call from
    async code via starlette.concurrency.run_in_threadpool.
    """
    for banned in _BANNED_KWARGS:
        if kwargs.pop(banned, None) is not None:
            logger.warning(
                "agent_response: dropped unsupported %r — not allowed with a hosted agent; "
                "ask for JSON in the prompt and parse output_text instead.",
                banned,
            )
    return get_client().responses.create(
        input=_as_prompt(input),
        extra_body={
            "agent_reference": {
                "name": settings.foundry_agent_name,
                "version": settings.foundry_agent_version,
                "type": "agent_reference",
            }
        },
        **kwargs,
    )


def log_interaction(
    db: AsyncSession,
    *,
    feature: str,
    prompt: str,
    resp,
    latency_ms: int | None = None,
    org_id=None,
) -> None:
    """Record one LLM call to ai_interactions — "how do you know the AI is right?"
    (CLAUDE.md). Adds to the caller's session; the caller commits."""
    usage = getattr(resp, "usage", None)
    db.add(
        AiInteraction(
            org_id=org_id,
            feature=feature,
            model=f"{settings.foundry_agent_name}:{settings.foundry_agent_version}",
            prompt=prompt,
            response={"output_text": getattr(resp, "output_text", None)},
            tokens=getattr(usage, "total_tokens", None) if usage is not None else None,
            latency_ms=latency_ms,
        )
    )
