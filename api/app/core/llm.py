"""Foundry hosted agent (Azure AI Projects SDK) -> standard OpenAI Responses client.

Auth is Entra ID via DefaultAzureCredential — `az login` locally, a service principal
(AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET env vars) on Render. No API key.
`get_openai_client()` returns the plain OpenAI SDK client; calls reference the hosted
agent (SyncUp-Agent) via extra_body, matching the sample on the Foundry agent page.

Rules (see CLAUDE.md): request JSON against a Pydantic schema, temperature 0.1-0.3,
validate + retry 2x, log every call. The model parses and explains; it never computes.
"""

from functools import lru_cache

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.org import AiInteraction


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
    """Call the hosted SyncUp agent via the Responses API. `input` is a str or a list
    of {role, content} messages; pass text=... for a JSON-schema response format. Sync
    client — call from async code via starlette.concurrency.run_in_threadpool.
    ponytail: sync + threadpool is fine; switch to azure.ai.projects.aio if the hop
    ever shows up in latency.
    """
    return get_client().responses.create(
        input=input,
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
