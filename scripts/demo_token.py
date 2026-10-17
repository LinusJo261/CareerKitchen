"""Print a short-lived development-only token for a named fictional fixture account."""

import argparse

from app.core.auth import mint_dev_token

from scripts.seed_demo import identity

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "account",
        choices=["employer", "verifier", "operations"] + [f"candidate-{i:02}" for i in range(1, 31)],
    )
    account = parser.parse_args().account
    print(mint_dev_token(identity(account), email=f"{account}@fictional.example.invalid"))
