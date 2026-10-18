"""Draft-only adaptive onboarding; confirmation is a separate explicit mutation."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import TransactionalRoute, actor_dep, db_dep
from app.core.errors import AppError
from app.core.settings import get_settings
from app.db.models import User
from app.integrations.gemini_onboarding import onboard
from app.schemas.onboarding import OnboardingChatIn, OnboardingChatOut
from app.schemas.responses import Envelope
from app.services.common import Actor, emit, load

router = APIRouter(route_class=TransactionalRoute, tags=["navigation"])


@router.post("/navigation/onboarding", response_model=Envelope[OnboardingChatOut])
async def onboarding_chat(
    body: OnboardingChatIn,
    request: Request,
    actor: Actor = Depends(actor_dep),
    db: Session = Depends(db_dep),
):
    persistence = get_settings()
    if (
        not persistence.encryption_key.get_secret_value()
        or len(persistence.audit_hmac_key.get_secret_value()) < 32
    ):
        raise AppError(
            503, "CHAT_UNAVAILABLE", "Career Chef requires server encryption and audit configuration"
        )
    result = await onboard(body, request.app.state.settings)
    emit(
        db,
        actor,
        "ONBOARDING_ASSISTED",
        load(db, User, actor.user_id),
        payload={"contract_version": 1, "consent_to_gemini": True},
    )
    return {"data": result}
