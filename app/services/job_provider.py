"""Mock Trello/Jira job feed — reads local JSON only."""

import json
import logging
from pathlib import Path

from pydantic import ValidationError

from app.schemas import JobSeed

logger = logging.getLogger(__name__)
MOCK_JOBS_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "mock_jobs.json"


def load_job_seeds() -> list[JobSeed]:
    if not MOCK_JOBS_PATH.exists():
        logger.warning("Mock jobs file missing: %s", MOCK_JOBS_PATH)
        return []
    raw = json.loads(MOCK_JOBS_PATH.read_text())
    seeds: list[JobSeed] = []
    for row in raw:
        try:
            seeds.append(JobSeed.model_validate(row))
        except ValidationError as exc:
            logger.warning("Skipping invalid mock job row: %s", exc)
    return seeds
