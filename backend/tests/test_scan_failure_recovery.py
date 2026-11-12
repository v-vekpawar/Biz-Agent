"""Regression tests for long evidence titles and scan failure persistence."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.domain.enums import RunStatus, ScanStatus
from app.repositories import EvidenceRepository, RunRepository, ScanRepository


def _poison_transaction(session):
    statement = text(
        "INSERT INTO users (email, password_hash, display_name) "
        "VALUES ('scan-recovery@example.com', 'hash', 'Test')"
    )
    session.execute(statement)
    with pytest.raises(IntegrityError):
        session.execute(statement)


def test_evidence_source_title_accepts_long_search_titles(factory, case_id):
    title = "Long source title " * 80
    with factory() as session:
        evidence = EvidenceRepository(session).create(case_id, title)
        assert evidence.source_title == title
        assert EvidenceRepository(session).require(evidence.id).source_title == title


def test_failure_transitions_recover_a_failed_database_transaction(factory, case_id):
    with factory() as session:
        runs = RunRepository(session)
        scans = ScanRepository(session)

        run = runs.create(case_id)
        runs.start(run.id)
        job = scans.create(case_id)
        scans.start(job)

        # Simulate a failed flush (unique constraint violation), which leaves
        # SQLAlchemy's Session requiring an explicit rollback.
        _poison_transaction(session)
        failed_run = runs.fail(run.id, "evidence write failed")
        assert failed_run.status == RunStatus.FAILED

        _poison_transaction(session)
        scans.fail(job, "The scan stopped unexpectedly (IntegrityError).")
        assert scans.get(job.id).status == ScanStatus.FAILED
