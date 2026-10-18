"""Run the existing API against the separate synthetic sample database on loopback."""

from __future__ import annotations

import argparse
import os
import re
from urllib.parse import urlsplit

from app.core.auth import mint_dev_token
from app.core.settings import get_settings
from app.db.models import Candidate, IdempotencyRecord, User
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from scripts.seed_samples import CLIENT_KEY, MARKER, ROUTE, identity, require_local


def check_samples() -> None:
    """Require a completed, recognized sample import before serving or minting tokens."""
    engine = create_engine(require_local(get_settings()), connect_args={"connect_timeout": 5})
    try:
        with Session(engine) as db:
            markers = list(db.scalars(text("SELECT marker FROM ck_sample_marker")))
            receipt = db.get(IdempotencyRecord, (identity("importer"), ROUTE, CLIENT_KEY))
            if markers != [MARKER] or receipt is None:
                raise ValueError("Run scripts.seed_samples to complete the sample import first")
    finally:
        engine.dispose()


def account_token(account: str) -> str:
    """Explicitly print a token only for a persisted fixture account; no role claims."""
    if account != "employer" and re.fullmatch(r"candidate-[0-9]{6}", account) is None:
        raise ValueError("Choose employer or candidate-000001 through the imported candidate count")
    label = "employer" if account == "employer" else account.replace("candidate-", "candidate-user-", 1)
    engine = create_engine(require_local(get_settings()), connect_args={"connect_timeout": 5})
    try:
        with Session(engine) as db:
            user = db.get(User, identity(label))
            if user is None or user.status != "ACTIVE":
                raise ValueError("The selected sample account does not exist")
            if (
                account != "employer"
                and db.scalar(select(Candidate.id).where(Candidate.user_id == user.id)) is None
            ):
                raise ValueError("The selected sample profile does not exist")
            return mint_dev_token(user.id, email=user.verified_email)
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    address = urlsplit(get_settings().sample_api_url)
    if (
        address.hostname not in {"127.0.0.1", "localhost", "::1"}
        or address.scheme != "http"
        or address.username
        or address.password
        or address.query
        or address.fragment
        or address.path not in {"", "/"}
    ):
        raise ValueError("The sample API requires a separate loopback HTTP address")
    parser.add_argument("--port", type=int, default=address.port or 8001)
    parser.add_argument("--token", metavar="ACCOUNT", help="Print a short-lived local fixture token and exit")
    options = parser.parse_args()
    if not 1024 <= options.port <= 65535:
        parser.error("Choose a port in 1024..65535")
    check_samples()
    if options.token:
        print(account_token(options.token))
        return
    os.environ["DATABASE_URL"] = require_local(get_settings()).render_as_string(hide_password=False)
    os.environ["SAMPLE_DEMO_ENABLED"] = "true"
    get_settings.cache_clear()
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=options.port)


if __name__ == "__main__":
    main()
