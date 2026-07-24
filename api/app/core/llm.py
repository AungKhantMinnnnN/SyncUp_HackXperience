"""Foundry client (OpenAI SDK) + JSON-schema call helper + ai_interactions logging.

Rules (see CLAUDE.md): request JSON against a Pydantic schema, temperature 0.1-0.3,
validate + retry 2x, log every call. The model parses and explains; it never computes.
"""

from openai import AsyncOpenAI

from app.config import settings

client = AsyncOpenAI(
    base_url=settings.foundry_base_url or None,
    api_key=settings.foundry_api_key or "unset",
)

# ponytail: schema-validated call helper + ai_interactions insert land here when the
# first agent.py needs them. Kept to the client until there's a real caller to shape it.
