"""Exercise a fresh loopback fictional fixture through HTTP; never print tokens.

Run once after guarded demo reset, with the API running and the worker stopped.
The smoke performs two human decisions and a message, so its fixture is consumed.
"""

import json
from uuid import uuid4

import httpx
from app.core.auth import mint_dev_token
from app.core.settings import get_settings

from scripts.seed_demo import identity


class SmokePreconditionError(RuntimeError):
    """Used fixture or concurrent activity prevents a deterministic smoke."""


def headers(account: str) -> dict[str, str]:
    return {
        "Authorization": "Bearer "
        + mint_dev_token(identity(account), email=f"{account}@fictional.example.invalid"),
        "Idempotency-Key": str(uuid4()),
    }


def run() -> None:
    settings = get_settings()
    if settings.environment != "development" or settings.auth_mode != "local":
        raise RuntimeError("HTTP smoke is restricted to fictional loopback development")
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=60, follow_redirects=False) as client:
        assert client.get("/v1/health").status_code == 200
        assert client.get("/v1/ready").status_code == 200
        profile = client.get("/v1/candidates/me", headers=headers("candidate-01"))
        profile.raise_for_status()
        assert profile.json()["data"]["headline"].startswith("Fictional")
        # Fail before reconcile or any human action when this candidate's fixture
        # already contains decisions. Waiting is valid behavior, not a lost card.
        waiting = client.get("/v1/candidates/me/waiting", headers=headers("candidate-01"))
        matches = client.get("/v1/candidates/me/matches", headers=headers("candidate-01"))
        history = client.get("/v1/candidates/me/history?limit=100", headers=headers("candidate-01"))
        for response in (waiting, matches, history):
            response.raise_for_status()
        pristine_states = {"ELIGIBLE", "CANDIDATE_DECISION_REQUIRED", "EMPLOYER_DECISION_REQUIRED"}
        used_states = sorted(
            {item["state"] for item in history.json()["data"] if item["state"] not in pristine_states}
        )
        if waiting.json()["data"] or matches.json()["data"] or used_states:
            states = ", ".join(used_states) or "previous interest or mutual match"
            raise SmokePreconditionError(
                f"candidate-01 already has {states}. A full employer inbox correctly keeps first interest "
                "in WAITING_EMPLOYER_SLOT. Stop the demo API/worker, reset only the guarded fictional "
                "fixture with `python -m scripts.seed_demo --reset`, start the API without the worker, "
                "and run this smoke once. See docs/demo.md. No smoke mutations were performed."
            )
        result = client.post("/v1/internal/reconcile", headers=headers("operations"))
        result.raise_for_status()
        inbox = client.get("/v1/candidates/me/decisions", headers=headers("candidate-01"))
        inbox.raise_for_status()
        cards = inbox.json()["data"]
        if not 0 < len(cards) <= profile.json()["data"]["cap"] <= 10:
            raise SmokePreconditionError(
                "Expected fresh candidate decision cards within the selected cap; see docs/demo.md"
            )
        card = None
        for candidate_card in cards:
            if candidate_card["other_side_interested"]:
                continue
            employer_inbox = client.get(
                f"/v1/vacancies/{candidate_card['vacancy']['id']}/decisions", headers=headers("employer")
            )
            employer_inbox.raise_for_status()
            if len(employer_inbox.json()["data"]) < candidate_card["vacancy"]["cap"]:
                card = candidate_card
                break
        if card is None:
            raise SmokePreconditionError(
                "No candidate-first card has a free employer decision slot. This is valid attention-cap "
                "behavior in a used market. No Interested decision was sent. Reset the fictional fixture "
                "and run once with only the API running; see docs/demo.md."
            )
        first = client.post(
            f"/v1/decisions/{card['id']}/interested",
            json={"expected_cycle_version": card["cycle_version"], "decision_token": card["decision_token"]},
            headers=headers("candidate-01"),
        )
        first.raise_for_status()
        first_state = first.json()["data"]["pair_state"]
        if first_state == "WAITING_EMPLOYER_SLOT":
            raise SmokePreconditionError(
                "Employer capacity filled during the smoke. The candidate interest is correctly waiting; "
                "no second-side card is due yet. Reset and run without concurrent activity; see docs/demo.md."
            )
        if first_state != "EMPLOYER_DECISION_REQUIRED":
            raise RuntimeError(
                f"Expected a fresh employer decision after first interest, received {first_state}"
            )
        employer_cards = client.get(
            f"/v1/vacancies/{card['vacancy']['id']}/decisions", headers=headers("employer")
        )
        employer_cards.raise_for_status()
        second_card = next(
            (
                item
                for item in employer_cards.json()["data"]
                if item["pair_cycle_id"] == card["pair_cycle_id"]
            ),
            None,
        )
        if second_card is None:
            raise RuntimeError(
                "The API returned EMPLOYER_DECISION_REQUIRED but its active card is missing from the "
                "authorized employer inbox; inspect concurrent activity and decision events."
            )
        second = client.post(
            f"/v1/decisions/{second_card['id']}/interested",
            json={
                "expected_cycle_version": second_card["cycle_version"],
                "decision_token": second_card["decision_token"],
            },
            headers=headers("employer"),
        )
        second.raise_for_status()
        assert second.json()["data"]["pair_state"] == "MUTUAL_MATCH"
        match_id = second.json()["data"]["match_id"]
        message = client.post(
            f"/v1/matches/{match_id}/messages",
            json={
                "expected_version": 1,
                "body": "Fictional demonstration: two independent interests enabled this conversation.",
            },
            headers=headers("candidate-01"),
        )
        message.raise_for_status()
        forbidden = client.get(f"/v1/matches/{match_id}", headers=headers("candidate-30"))
        assert forbidden.status_code == 403
        print(
            json.dumps(
                {
                    "fictional": True,
                    "health": 200,
                    "ready": 200,
                    "issued_cards": len(result.json()["data"]["issued"]),
                    "candidate_active_cards_at_review": len(cards),
                    "double_opt_in": "MUTUAL_MATCH",
                    "message": 200,
                    "unrelated_actor": 403,
                    "match_id": match_id,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    try:
        run()
    except SmokePreconditionError as exc:
        raise SystemExit(f"Smoke precondition failed: {exc}") from None
