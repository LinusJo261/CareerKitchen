from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import TransactionalRoute, actor_dep, db_dep
from app.core.errors import AppError
from app.core.settings import get_settings
from app.db.models import User
from app.integrations.gemini_navigation import navigate
from app.schemas.navigation import NavigationChatIn, NavigationChatOut
from app.schemas.responses import Envelope
from app.services.common import Actor, emit, load

router = APIRouter(route_class=TransactionalRoute, tags=["navigation"])


@router.post(
    "/navigation/chat",
    response_model=Envelope[NavigationChatOut],
    summary="Ask Career Chef for application guidance",
    description=(
        "Returns a Gemini-generated plain-text answer and approved navigation links. "
        "Use Authorize with a valid session, supply a unique Idempotency-Key, and explicitly "
        "consent to sending the message and optional history to Google Gemini. "
        "The answer is in data.reply. No application actions are performed."
    ),
)
async def navigation_chat(
    body: NavigationChatIn,
    request: Request,
    actor: Actor = Depends(actor_dep),
    db: Session = Depends(db_dep),
):
    # The existing encryption/audit helpers use process settings. Fail before a
    # paid provider call if durable transactional processing cannot be completed.
    persistence = get_settings()
    if (
        not persistence.encryption_key.get_secret_value()
        or len(persistence.audit_hmac_key.get_secret_value()) < 32
    ):
        raise AppError(
            503, "CHAT_UNAVAILABLE", "Career Chef requires server encryption and audit configuration"
        )
    result = await navigate(body.message, request.app.state.settings, history=body.history)
    # Store no prompt in audit/outbox; encrypted idempotency has the response only.
    emit(
        db,
        actor,
        "NAVIGATION_ASSISTED",
        load(db, User, actor.user_id),
        payload={"contract_version": 1, "consent_to_gemini": True},
    )
    return {"data": result}
