"""Run API or worker against the separately seeded local fictional database."""

import argparse
import os

from app.core.settings import get_settings
from sqlalchemy.engine import make_url

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    options = parser.parse_args()
    settings = get_settings()
    if settings.environment != "development" or settings.auth_mode != "local":
        raise RuntimeError("Demo requires explicit local development configuration")
    os.environ["DATABASE_URL"] = (
        make_url(settings.database_url)
        .set(database="career_kitchen_demo")
        .render_as_string(hide_password=False)
    )
    get_settings.cache_clear()
    if options.worker:
        import sys

        sys.argv = [sys.argv[0]]
        from app.workers.runner import main

        main()
    else:
        import uvicorn

        uvicorn.run("app.main:app", host="127.0.0.1", port=8000)
