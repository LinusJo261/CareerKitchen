from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import TransactionalRoute, actor_dep, db_dep
from app.db.models import User
from app.integrations.gemini_navigation import navigate
from app.schemas.navigation import NavigationChatIn, NavigationChatOut
from app.schemas.responses import Envelope
from app.services.common import Actor, emit, load

router = APIRouter(route_class=TransactionalRoute, tags=["navigation"])


@router.post("/navigation/chat", response_model=Envelope[NavigationChatOut])
async def navigation_chat(
    body: NavigationChatIn,
    request: Request,
    actor: Actor = Depends(actor_dep),
    db: Session = Depends(db_dep),
):
    result = await navigate(body.message, request.app.state.settings)
    # Store no prompt in audit/outbox; encrypted idempotency has the response only.
    emit(
        db,
        actor,
        "NAVIGATION_ASSISTED",
        load(db, User, actor.user_id),
        payload={"contract_version": 1, "consent_to_gemini": True},
    )
    return {"data": result}
