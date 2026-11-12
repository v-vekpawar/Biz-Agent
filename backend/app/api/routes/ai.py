"""AI provider configuration status (never returns secrets)."""

from fastapi import APIRouter, Depends

from ..deps import get_current_user
from ...integrations.llm.provider import provider_status

router = APIRouter(tags=["ai"])


@router.get("/ai/providers")
def ai_providers(_user=Depends(get_current_user)):
    """Show which free-tier providers are configured and their fallback order."""
    return provider_status()
