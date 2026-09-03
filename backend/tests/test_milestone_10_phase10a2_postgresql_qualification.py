"""Guarded, real-PostgreSQL qualification for the additive M10A2 foundation."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import os
from threading import Event
import time
from uuid import uuid4

import pytest
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateTable

from app.attribution.contracts import AttributionContractError, AttributionIdempotencyConflict
from app.models.affiliate_content_asset import AffiliateContentAsset
from app.models.affiliate_conversion import AffiliateConversion
from app.models.affiliate_link import AffiliateLink
from app.models.affiliate_program import AffiliateProgram
from app.models.attribution import AttributionClick, AttributionContext, AttributionFact, AttributionPublication
from app.models.content_brief import ContentBrief
from app.models.content_evaluation import ContentEvaluation
from app.models.content_generation_run import ContentGenerationRun
from app.models.discovery import DiscoveryCandidate, DiscoveryRun
from app.models.distribution_run import DistributionRun
from app.models.generated_content_artifact import GeneratedContentArtifact
from app.models.product import Product
from app.models.publishing_queue import PublishingQueue
from app.services.attribution_click_service import AttributionClickService
from app.services.attribution_context_service import AttributionContextService
from app.services.attribution_fact_service import AttributionFactService
from app.services.attribution_publication_service import AttributionPublicationService
from app.services.affiliate_click_service import AffiliateClickService
from app.services.affiliate_conversion_service import AffiliateConversionService
from app.services.affiliate_link_service import AffiliateLinkService


REVISION = "c3d4e5f6a7b8"
DATABASE = "etm_g5_m10a2_qualification"
raw_url = os.getenv("ETM_G5_DATABASE_URL")
if not raw_url:
    pytest.skip("Requires guarded ETM_G5_DATABASE_URL.", allow_module_level=True)
url = make_url(raw_url)
if not (
    url.drivername.startswith("postgresql") and url.host == "127.0.0.1"
    and url.port == 5432 and url.database == DATABASE
):
    raise RuntimeError("M10A2 qualification requires the dedicated local PostgreSQL database")

engine = create_engine(url.render_as_string(hide_password=False), pool_pre_ping=True)
Session = sessionmaker(bind=engine, expire_on_commit=False)
NOW = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


@pytest.fixture(scope="module", autouse=True)
def guarded_schema():
    with engine.connect() as connection:
        assert connection.execute(text("SELECT current_database()" )).scalar_one() == DATABASE
        assert MigrationContext.configure(connection).get_current_revision() == REVISION
    yield
    engine.dispose()


def _legacy(db, *, product_name="M10A2 Product"):
    token = uuid4().hex
    product = Product(
        name=product_name, website=f"https://{token}.invalid", category="test", affiliate_program="yes",
        commission_type="flat", commission_value="10", affiliate_score=1, grade="A", confidence=100,
        summary="", recommendation="", status="active",
    )
    db.add(product); db.flush()
    program = AffiliateProgram(product_id=product.id, program_name=f"program-{token}")
    db.add(program); db.flush()
    asset = AffiliateContentAsset(product_id=product.id, asset_type="article", title="M10A2")
    db.add(asset); db.flush()
    queue = PublishingQueue(content_asset_id=asset.id, channel=f"m10a2-{token}")
    db.add(queue); db.flush()
    link = AffiliateLink(
        affiliate_program_id=program.id, content_asset_id=asset.id, name="M10A2",
        destination_url="https://destination.invalid", tracking_code=f"m10a2-{token}", is_active=True,
    )
    db.add(link); db.flush()
    conversion = AffiliateConversion(
        affiliate_link_id=link.id, affiliate_program_id=program.id,
        external_conversion_id=f"conversion-{token}", sale_amount=0, commission_amount=0,
        currency="USD", conversion_status="pending", source="qualification",
        customer_reference="m10a2@example.test",
        metadata_json=(
            '{"ipv4":"203.0.113.77","ipv6":"2001:db8::77",'
            '"phone":"+2348012345678","ua":"Safari/605.1.15",'
            '"customer":"customer-784392","secret":"sk_live_51ABCDEF"}'
        ),
    )
    db.add(conversion); db.flush()
    return product, program, asset, queue, link, conversion


def _modern_run(db):
    ids = {name: str(uuid4()) for name in ("discovery", "candidate", "brief", "generation", "artifact", "evaluation", "run")}
    rows = [
        DiscoveryRun(id=ids["discovery"], input_type="URL", input_value="https://modern.invalid", status="COMPLETED", idempotency_key=ids["discovery"], candidate_count=1, verified_count=1, selected_count=1, created_at=NOW, updated_at=NOW),
        DiscoveryCandidate(id=ids["candidate"], run_id=ids["discovery"], source_adapter="test", source_type="test", canonical_domain="modern.invalid", program_identity_key=ids["candidate"], dedupe_key=ids["candidate"], commission_model="UNKNOWN", verification_status="VERIFIED", disposition="SELECTED", created_at=NOW, updated_at=NOW),
        ContentBrief(id=ids["brief"], discovery_run_id=ids["discovery"], discovery_candidate_id=ids["candidate"], content_type="ARTICLE", channel_intent="SEO", objective="proof", call_to_action="CHECK_DETAILS", required_disclosure="AFFILIATE_DISCLOSURE_REQUIRED", key_benefits=[], proof_points=[], target_keywords=[], constraints=[], idempotency_key=ids["brief"], status="READY", created_at=NOW, updated_at=NOW),
        ContentGenerationRun(id=ids["generation"], content_brief_id=ids["brief"], idempotency_key=ids["generation"], provider="test", model="test", prompt_version="v1", generation_parameters={}, status="COMPLETED", attempt_count=1, created_at=NOW, updated_at=NOW),
        GeneratedContentArtifact(id=ids["artifact"], generation_run_id=ids["generation"], content_brief_id=ids["brief"], content_type="ARTICLE", title="proof", hook="proof", body="proof", call_to_action="CHECK_DETAILS", affiliate_disclosure="disclosure", claims=[], status="GENERATED", created_at=NOW, updated_at=NOW),
        ContentEvaluation(id=ids["evaluation"], artifact_id=ids["artifact"], content_brief_id=ids["brief"], generation_run_id=ids["generation"], factual_grounding_score=100, offer_alignment_score=100, intent_alignment_score=100, clarity_score=100, cta_score=100, compliance_score=100, overall_score=100, decision="APPROVED", approved=True, evaluator_version="v1", policy_version="v1", claim_results=[], compliance_flags=[], unsupported_claims=[], missing_evidence_ids=[], revision_reasons=[], rejection_reasons=[], created_at=NOW, updated_at=NOW),
        DistributionRun(id=ids["run"], generated_content_artifact_id=ids["artifact"], content_evaluation_id=ids["evaluation"], platform="test", account_reference="account", destination="destination", status="CREATED", idempotency_key=ids["run"], payload_fingerprint="a" * 64, prepared_content_body="proof", created_at=NOW, updated_at=NOW),
    ]
    for row in rows:
        db.add(row); db.flush()
    return ids["run"]


def _foundation(db):
    _, program, _, queue, link, conversion = _legacy(db)
    publication = AttributionPublicationService(db).bind_legacy(queue.id)
    context = AttributionContextService(db).create(
        affiliate_program_id=program.id, attribution_publication_id=publication.id,
    )
    return program, queue, link, conversion, publication, context


def _constraint_names(items):
    return {item["name"] for item in items}


def test_model_and_postgresql_schema_parity_is_mechanical_and_semantic():
    inspector = inspect(engine)
    model_tables = {
        table.name: table for table in (
            AttributionPublication.__table__, AttributionContext.__table__,
            AttributionClick.__table__, AttributionFact.__table__,
        )
    }
    for table_name, model in model_tables.items():
        live_columns = {item["name"]: item for item in inspector.get_columns(table_name)}
        assert set(live_columns) == {column.name for column in model.columns}
        for column in model.columns:
            live = live_columns[column.name]
            assert live["nullable"] == column.nullable
            assert (live.get("default") is None) == (column.server_default is None)
            model_type = column.type.compile(dialect=postgresql.dialect())
            live_type = live["type"].compile(dialect=postgresql.dialect())
            assert live_type == model_type

        model_fks = {
            (next(iter(fk.columns)).name, next(iter(fk.elements)).target_fullname)
            for fk in model.foreign_key_constraints
        }
        live_fks = {
            (item["constrained_columns"][0], f"{item['referred_table']}.{item['referred_columns'][0]}")
            for item in inspector.get_foreign_keys(table_name)
        }
        assert live_fks == model_fks

        model_uniques = {
            constraint.name for constraint in model.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        }
        assert _constraint_names(inspector.get_unique_constraints(table_name)) == model_uniques
        assert {item["name"] for item in inspector.get_indexes(table_name) if not item.get("duplicates_constraint")} == {
            index.name for index in model.indexes
        }
        model_checks = {
            constraint.name for constraint in model.constraints
            if constraint.__class__.__name__ == "CheckConstraint"
        }
        assert _constraint_names(inspector.get_check_constraints(table_name)) == model_checks

        ddl = str(CreateTable(model).compile(dialect=postgresql.dialect()))
        live_checks = "\n".join(item["sqltext"] for item in inspector.get_check_constraints(table_name))
        for field in (
            "context_fingerprint", "source_fingerprint", "source_event_key_digest",
        ):
            if field in live_columns:
                assert f"{field} ~ '^[0-9a-f]{{64}}$'" in ddl
                assert "^[0-9a-f]{64}$" in live_checks
        for column in model.columns:
            if column.name in {"created_at", "occurred_at", "recorded_at"}:
                assert live_columns[column.name]["type"].timezone is True


def test_postgresql_rejects_every_malformed_fingerprint_and_digest_class():
    db = Session()
    try:
        program, _, link, _, publication, context = _foundation(db)
        db.commit()
        ids = program.id, link.id, publication.id, context.id
    finally:
        db.close()
    program_id, link_id, publication_id, context_id = ids
    malformed = ("a" * 63, "a" * 65, "A" * 64, "g" * 64, "a" * 63 + " ")

    statements = (
        """INSERT INTO attribution_contexts(
               id,affiliate_program_id,attribution_publication_id,context_fingerprint,created_at
           ) VALUES (:id,:program,:publication,:bad,now())""",
        """INSERT INTO attribution_clicks(
               id,click_key,attribution_context_id,affiliate_link_id,source_namespace,
               source_event_key_digest,source_fingerprint,occurred_at,recorded_at
           ) VALUES (:id,:click_key,:context,:link,'malformed',:good,:bad,now(),now())""",
        """INSERT INTO attribution_clicks(
               id,click_key,attribution_context_id,affiliate_link_id,source_namespace,
               source_event_key_digest,source_fingerprint,occurred_at,recorded_at
           ) VALUES (:id,:click_key,:context,:link,'malformed',:bad,:good,now(),now())""",
        """INSERT INTO attribution_facts(
               id,fact_kind,source_namespace,source_event_key_digest,source_fingerprint,
               attribution_publication_id,occurred_at,recorded_at
           ) VALUES (:id,'PUBLICATION_BOUND','malformed',:good,:bad,:publication,now(),now())""",
        """INSERT INTO attribution_facts(
               id,fact_kind,source_namespace,source_event_key_digest,source_fingerprint,
               attribution_publication_id,occurred_at,recorded_at
           ) VALUES (:id,'PUBLICATION_BOUND','malformed',:bad,:good,:publication,now(),now())""",
    )
    for sql in statements:
        for bad in malformed:
            with engine.connect() as connection:
                transaction = connection.begin()
                with pytest.raises(DBAPIError):
                    connection.execute(text(sql), {
                        "id": str(uuid4()), "click_key": str(uuid4()),
                        "program": program_id, "publication": publication_id,
                        "context": context_id, "link": link_id,
                        "good": _digest(f"good-{uuid4().hex}"), "bad": bad,
                    })
                transaction.rollback()


def test_publication_context_contracts_and_database_constraints():
    db = Session()
    try:
        product, program, _, queue, _, _ = _legacy(db)
        publication_service = AttributionPublicationService(db)
        publication = publication_service.bind_legacy(queue.id)
        assert publication_service.bind_legacy(queue.id).id == publication.id
        context_service = AttributionContextService(db)
        context = context_service.create(affiliate_program_id=program.id, attribution_publication_id=publication.id)
        assert context_service.create(affiliate_program_id=program.id, attribution_publication_id=publication.id).id == context.id
        other = Product(name="other", website=f"https://{uuid4().hex}.invalid", category="test", affiliate_program="yes", commission_type="flat", commission_value="1")
        db.add(other); db.flush()
        other_program = AffiliateProgram(product_id=other.id, program_name="other")
        db.add(other_program); db.flush()
        with pytest.raises(ValueError, match="does not match"):
            context_service.create(affiliate_program_id=other_program.id, attribution_publication_id=publication.id)
        run_id = _modern_run(db)
        modern = publication_service.bind_distribution(run_id)
        assert publication_service.bind_distribution(run_id).id == modern.id
        assert context_service.create(affiliate_program_id=program.id, attribution_publication_id=modern.id)
        db.commit()
    finally:
        db.close()
    invalid_statements = [
        ("INSERT INTO attribution_publications(id,created_at) VALUES (:id,now())", {}),
        ("INSERT INTO attribution_publications(id,legacy_publishing_queue_id,distribution_run_id,created_at) VALUES (:id,:queue,:run,now())", {"queue": queue.id, "run": run_id}),
        ("INSERT INTO attribution_publications(id,legacy_publishing_queue_id,created_at) VALUES (:id,2147483647,now())", {}),
        ("INSERT INTO attribution_contexts(id,affiliate_program_id,attribution_publication_id,context_fingerprint,created_at) VALUES (:id,2147483647,:publication,repeat('b',64),now())", {"publication": publication.id}),
    ]
    for sql, params in invalid_statements:
        with engine.connect() as connection:
            transaction = connection.begin()
            with pytest.raises(IntegrityError):
                connection.execute(text(sql), {"id": str(uuid4()), **params})
            transaction.rollback()
    duplicate_authorities = (
        (
            {"legacy_publishing_queue_id": queue.id, "distribution_run_id": None},
            "uq_attribution_publications_legacy_queue",
        ),
        (
            {"legacy_publishing_queue_id": None, "distribution_run_id": run_id},
            "uq_attribution_publications_distribution_run",
        ),
    )
    for authority, constraint_name in duplicate_authorities:
        with engine.connect() as connection:
            transaction = connection.begin()
            with pytest.raises(IntegrityError) as error:
                connection.execute(AttributionPublication.__table__.insert().values(
                    id=str(uuid4()), created_at=NOW, **authority,
                ))
            assert error.value.orig.diag.constraint_name == constraint_name
            transaction.rollback()
    verifier = Session()
    try:
        assert verifier.query(AttributionPublication).filter_by(
            legacy_publishing_queue_id=queue.id,
        ).count() == 1
        assert verifier.query(AttributionPublication).filter_by(
            distribution_run_id=run_id,
        ).count() == 1
    finally:
        verifier.close()
    columns = {column["name"]: column for column in inspect(engine).get_columns("attribution_contexts")}
    assert columns["created_at"]["type"].timezone is True


def test_click_fact_ledger_privacy_append_only_and_atomicity():
    db = Session()
    try:
        program, _, link, conversion, publication, context = _foundation(db)
        click_service = AttributionClickService(db)
        for raw_identity in (
            "203.0.113.77", "2001:db8::77", "m10a2@example.test",
            "+2348012345678", "Safari/605.1.15", "customer-784392",
            "sk_live_51ABCDEF",
        ):
            with pytest.raises(AttributionContractError, match="source_event_key_digest"):
                click_service.record(
                    attribution_context_id=context.id, affiliate_link_id=link.id,
                    source_namespace="qualification", source_event_key_digest=raw_identity,
                    occurred_at=NOW,
                )
        click = click_service.record(
            attribution_context_id=context.id, affiliate_link_id=link.id,
            source_namespace="  Qualification ", source_event_key_digest=_digest(f"click-{uuid4().hex}"), occurred_at=NOW,
        )
        replay = click_service.record(
            attribution_context_id=context.id, affiliate_link_id=link.id,
            source_namespace="qualification", source_event_key_digest=click.source_event_key_digest, occurred_at=NOW,
        )
        assert replay.id == click.id
        with pytest.raises(AttributionIdempotencyConflict):
            click_service.record(
                attribution_context_id=context.id, affiliate_link_id=link.id,
                source_namespace="qualification", source_event_key_digest=click.source_event_key_digest,
                occurred_at=NOW + timedelta(seconds=1),
            )
        with pytest.raises(AttributionContractError, match="timezone-aware"):
            click_service.record(
                attribution_context_id=context.id, affiliate_link_id=link.id,
                source_namespace="qualification", source_event_key_digest=_digest("naive"), occurred_at=datetime(2026, 1, 1),
            )
        _, wrong_program, _, _, wrong_link, _ = _legacy(db, product_name="wrong")
        assert wrong_program.id != program.id
        with pytest.raises(ValueError, match="does not match"):
            click_service.record(
                attribution_context_id=context.id, affiliate_link_id=wrong_link.id,
                source_namespace="qualification", source_event_key_digest=_digest("wrong-link"), occurred_at=NOW,
            )
        facts = AttributionFactService(db)
        publication_fact = facts.append(fact_kind="PUBLICATION_BOUND", source_namespace="qualification", source_event_key_digest=_digest(f"publication-{uuid4().hex}"), occurred_at=NOW, attribution_publication_id=publication.id)
        link_fact = facts.append(fact_kind="LINK_BOUND", source_namespace="qualification", source_event_key_digest=_digest(f"link-{uuid4().hex}"), occurred_at=NOW, attribution_context_id=context.id, affiliate_link_id=link.id)
        click_fact = facts.append(fact_kind="CLICK_RECORDED", source_namespace="qualification", source_event_key_digest=_digest(f"click-fact-{uuid4().hex}"), occurred_at=NOW, attribution_context_id=context.id, attribution_click_id=click.id, affiliate_link_id=link.id)
        conversion_fact = facts.append(fact_kind="CONVERSION_REPORTED", source_namespace="qualification", source_event_key_digest=_digest(f"conversion-{uuid4().hex}"), occurred_at=NOW, attribution_context_id=context.id, affiliate_conversion_id=conversion.id)
        correction = facts.append(fact_kind="ATTRIBUTION_CORRECTED", source_namespace="qualification", source_event_key_digest=_digest(f"correction-{uuid4().hex}"), occurred_at=NOW, supersedes_fact_id=link_fact.id)
        assert correction.id != link_fact.id
        assert facts.append(fact_kind="PUBLICATION_BOUND", source_namespace="qualification", source_event_key_digest=publication_fact.source_event_key_digest, occurred_at=NOW, attribution_publication_id=publication.id).id == publication_fact.id
        with pytest.raises(AttributionIdempotencyConflict):
            facts.append(fact_kind="PUBLICATION_BOUND", source_namespace="qualification", source_event_key_digest=publication_fact.source_event_key_digest, occurred_at=NOW + timedelta(seconds=1), attribution_publication_id=publication.id)
        with pytest.raises(AttributionContractError):
            facts.append(fact_kind="COMMISSION_EARNED", source_namespace="qualification", source_event_key_digest=_digest("financial"), occurred_at=NOW)
        assert {row.fact_kind for row in (publication_fact, link_fact, click_fact, conversion_fact, correction)} == {
            "PUBLICATION_BOUND", "LINK_BOUND", "CLICK_RECORDED", "CONVERSION_REPORTED", "ATTRIBUTION_CORRECTED",
        }
        ids = (
            publication.id, context.id, click.id, publication_fact.id,
            click.occurred_at, click.recorded_at,
        )
        db.commit()
    finally:
        db.close()

    with engine.connect() as connection:
        transaction = connection.begin()
        with pytest.raises(IntegrityError):
            connection.execute(text("""
                INSERT INTO attribution_facts(
                    id,fact_kind,source_namespace,source_event_key_digest,source_fingerprint,occurred_at,recorded_at
                ) VALUES (:id,'PUBLICATION_BOUND','qualification',:key,repeat('a',64),now(),now())
            """), {"id": str(uuid4()), "key": _digest(f"invalid-refs-{uuid4().hex}")})
        transaction.rollback()

    with engine.connect() as connection:
        values = []
        for table in ("attribution_publications", "attribution_contexts", "attribution_clicks", "attribution_facts"):
            for row in connection.execute(text(f"SELECT * FROM {table}")).mappings():
                values.extend(str(value).lower() for value in row.values() if value is not None)
        durable = "\n".join(values)
        for marker in (
            "203.0.113.77", "2001:db8::77", "m10a2@example.test",
            "+2348012345678", "safari/605.1.15", "customer-784392",
            "sk_live_51abcdef",
        ):
            assert marker not in durable
        fact_id = ids[3]

    timestamp_verifier = Session()
    try:
        reloaded_click = timestamp_verifier.get(AttributionClick, ids[2])
        assert reloaded_click.occurred_at.tzinfo is not None
        assert reloaded_click.occurred_at.utcoffset() is not None
        assert reloaded_click.recorded_at.tzinfo is not None
        assert reloaded_click.recorded_at.utcoffset() is not None
        assert reloaded_click.occurred_at.astimezone(timezone.utc) == ids[4].astimezone(timezone.utc) == NOW
        assert reloaded_click.recorded_at.astimezone(timezone.utc) == ids[5].astimezone(timezone.utc)
    finally:
        timestamp_verifier.close()

    fact_fields = (
        "id", "fact_kind", "source_namespace", "source_event_key_digest",
        "source_fingerprint", "attribution_publication_id",
        "attribution_context_id", "attribution_click_id", "affiliate_link_id",
        "affiliate_conversion_id", "supersedes_fact_id", "occurred_at", "recorded_at",
    )

    def persisted_fact_snapshot():
        fresh = Session()
        try:
            row = fresh.get(AttributionFact, fact_id)
            assert row is not None
            return tuple(getattr(row, field) for field in fact_fields)
        finally:
            fresh.close()

    original_fact = persisted_fact_snapshot()
    with engine.connect() as connection:
        transaction = connection.begin()
        with pytest.raises(DBAPIError, match="append-only"):
            connection.execute(text(
                "UPDATE attribution_facts SET occurred_at=now() WHERE id=:id"
            ), {"id": fact_id})
        transaction.rollback()
    assert persisted_fact_snapshot() == original_fact

    with engine.connect() as connection:
        transaction = connection.begin()
        with pytest.raises(DBAPIError, match="append-only"):
            connection.execute(text("DELETE FROM attribution_facts WHERE id=:id"), {"id": fact_id})
        transaction.rollback()
    assert persisted_fact_snapshot() == original_fact
    survival_verifier = Session()
    try:
        assert survival_verifier.query(AttributionFact).filter_by(id=fact_id).count() == 1
    finally:
        survival_verifier.close()
    inspector = inspect(engine)
    assert inspector.get_columns("attribution_clicks")[-1]["type"].timezone is True
    assert inspector.get_columns("attribution_facts")[-1]["type"].timezone is True

    rollback_db = Session()
    try:
        _, _, _, queue, _, _ = _legacy(rollback_db)
        rolled_publication = AttributionPublicationService(rollback_db).bind_legacy(queue.id)
        rolled_fact = AttributionFactService(rollback_db).append(
            fact_kind="PUBLICATION_BOUND", source_namespace="qualification", source_event_key_digest=_digest(f"rollback-{uuid4().hex}"),
            occurred_at=NOW, attribution_publication_id=rolled_publication.id,
        )
        rolled_ids = rolled_publication.id, rolled_fact.id
        rollback_db.rollback()
    finally:
        rollback_db.close()
    verify = Session()
    try:
        assert verify.get(AttributionPublication, rolled_ids[0]) is None
        assert verify.get(AttributionFact, rolled_ids[1]) is None
    finally:
        verify.close()


def _hold_uncommitted_click(context_id, link_id, namespace, key, occurred,
                            inserted, release, backend):
    db = Session()
    try:
        backend["pid"] = db.execute(text("SELECT pg_backend_pid()" )).scalar_one()
        row = AttributionClickService(db).record(
            attribution_context_id=context_id, affiliate_link_id=link_id,
            source_namespace=namespace, source_event_key_digest=key, occurred_at=occurred,
        )
        row_id = row.id
        inserted.set()
        if not release.wait(10):
            raise AssertionError("timed out waiting to release held click transaction")
        db.commit()
        return "ok", row_id
    except Exception:
        db.rollback()
        inserted.set()
        raise
    finally:
        db.close()


def _contending_click(context_id, link_id, namespace, key, occurred,
                      started, completed, backend):
    db = Session()
    try:
        backend["pid"] = db.execute(text("SELECT pg_backend_pid()" )).scalar_one()
        started.set()
        row = AttributionClickService(db).record(
            attribution_context_id=context_id, affiliate_link_id=link_id,
            source_namespace=namespace, source_event_key_digest=key, occurred_at=occurred,
        )
        row_id = row.id
        db.commit()
        return "ok", row_id
    except AttributionIdempotencyConflict:
        db.rollback()
        return "conflict", None
    finally:
        completed.set()
        db.close()


def _hold_uncommitted_fact(publication_id, namespace, key, occurred,
                           inserted, release, backend):
    db = Session()
    try:
        backend["pid"] = db.execute(text("SELECT pg_backend_pid()" )).scalar_one()
        row = AttributionFactService(db).append(
            fact_kind="PUBLICATION_BOUND", source_namespace=namespace,
            source_event_key_digest=key, occurred_at=occurred,
            attribution_publication_id=publication_id,
        )
        row_id = row.id
        inserted.set()
        if not release.wait(10):
            raise AssertionError("timed out waiting to release held fact transaction")
        db.commit()
        return "ok", row_id
    except Exception:
        db.rollback()
        inserted.set()
        raise
    finally:
        db.close()


def _contending_fact(publication_id, namespace, key, occurred,
                     started, completed, backend):
    db = Session()
    try:
        backend["pid"] = db.execute(text("SELECT pg_backend_pid()" )).scalar_one()
        started.set()
        row = AttributionFactService(db).append(
            fact_kind="PUBLICATION_BOUND", source_namespace=namespace,
            source_event_key_digest=key, occurred_at=occurred,
            attribution_publication_id=publication_id,
        )
        row_id = row.id
        db.commit()
        return "ok", row_id
    except AttributionIdempotencyConflict:
        db.rollback()
        return "conflict", None
    finally:
        completed.set()
        db.close()


def _assert_real_postgresql_contention(contender_pid, holder_pid, completed):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with engine.connect() as connection:
            state = connection.execute(text("""
                SELECT wait_event_type, wait_event, pg_blocking_pids(pid) AS blockers
                FROM pg_stat_activity WHERE pid=:pid
            """), {"pid": contender_pid}).mappings().one_or_none()
        if state is not None and state["wait_event_type"] == "Lock" and holder_pid in state["blockers"]:
            assert not completed.is_set()
            return state["wait_event"]
        if completed.wait(0.025):
            pytest.fail("contender completed before PostgreSQL lock contention was observed")
    pytest.fail("PostgreSQL lock contention was not observed")


def _forced_click_race(context_id, link_id, key, contender_occurred_at):
    inserted, started, completed, release = Event(), Event(), Event(), Event()
    holder_backend, contender_backend = {}, {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        holder = pool.submit(
            _hold_uncommitted_click, context_id, link_id, "concurrency", key,
            NOW, inserted, release, holder_backend,
        )
        assert inserted.wait(5)
        if holder.done():
            holder.result()
        contender = pool.submit(
            _contending_click, context_id, link_id, "concurrency", key,
            contender_occurred_at, started, completed, contender_backend,
        )
        assert started.wait(5)
        try:
            wait_event = _assert_real_postgresql_contention(
                contender_backend["pid"], holder_backend["pid"], completed,
            )
        finally:
            release.set()
        return holder.result(timeout=10), contender.result(timeout=10), wait_event


def _forced_fact_race(publication_id, key, contender_occurred_at):
    inserted, started, completed, release = Event(), Event(), Event(), Event()
    holder_backend, contender_backend = {}, {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        holder = pool.submit(
            _hold_uncommitted_fact, publication_id, "concurrency", key,
            NOW, inserted, release, holder_backend,
        )
        assert inserted.wait(5)
        if holder.done():
            holder.result()
        contender = pool.submit(
            _contending_fact, publication_id, "concurrency", key,
            contender_occurred_at, started, completed, contender_backend,
        )
        assert started.wait(5)
        try:
            wait_event = _assert_real_postgresql_contention(
                contender_backend["pid"], holder_backend["pid"], completed,
            )
        finally:
            release.set()
        return holder.result(timeout=10), contender.result(timeout=10), wait_event


def test_real_postgresql_click_and_fact_concurrency():
    db = Session()
    try:
        _, _, link, _, publication, context = _foundation(db)
        db.commit()
        context_id, link_id, publication_id = context.id, link.id, publication.id
    finally:
        db.close()

    click_key = _digest(f"concurrent-click-{uuid4().hex}")
    click_winner, click_replay, click_wait = _forced_click_race(
        context_id, link_id, click_key, NOW,
    )
    assert click_wait
    assert click_winner[0] == click_replay[0] == "ok"
    assert click_winner[1] == click_replay[1]

    conflict_key = _digest(f"conflicting-click-{uuid4().hex}")
    click_winner, click_conflict, conflict_wait = _forced_click_race(
        context_id, link_id, conflict_key, NOW + timedelta(seconds=1),
    )
    assert conflict_wait
    assert click_winner[0] == "ok" and click_conflict[0] == "conflict"

    fact_key = _digest(f"concurrent-fact-{uuid4().hex}")
    fact_winner, fact_replay, fact_wait = _forced_fact_race(publication_id, fact_key, NOW)
    assert fact_wait
    assert fact_winner[0] == fact_replay[0] == "ok"
    assert fact_winner[1] == fact_replay[1]

    conflicting_fact_key = _digest(f"conflicting-fact-{uuid4().hex}")
    fact_winner, fact_conflict, fact_conflict_wait = _forced_fact_race(
        publication_id, conflicting_fact_key, NOW + timedelta(seconds=1),
    )
    assert fact_conflict_wait
    assert fact_winner[0] == "ok" and fact_conflict[0] == "conflict"

    verifier = Session()
    try:
        assert verifier.query(AttributionClick).filter_by(source_namespace="concurrency", source_event_key_digest=click_key).count() == 1
        assert verifier.query(AttributionClick).filter_by(source_namespace="concurrency", source_event_key_digest=conflict_key).count() == 1
        assert verifier.query(AttributionFact).filter_by(source_namespace="concurrency", source_event_key_digest=fact_key).count() == 1
        assert verifier.query(AttributionFact).filter_by(source_namespace="concurrency", source_event_key_digest=conflicting_fact_key).count() == 1
    finally:
        verifier.close()


def test_legacy_link_click_conversion_remain_compatible_and_unbridged():
    db = Session()
    try:
        _, program, asset, _, _, _ = _legacy(db)
        db.commit()
        before_clicks = db.query(AttributionClick).count()
        before_facts = db.query(AttributionFact).count()
        link = AffiliateLinkService(db).create_link(
            affiliate_program_id=program.id, content_asset_id=asset.id,
            name="legacy compatibility", destination_url="https://legacy.invalid",
        )
        legacy_click = AffiliateClickService(db).record_click(
            link.tracking_code, ip_address="198.51.100.5", user_agent="legacy-agent",
        )
        legacy_conversion = AffiliateConversionService(db).create_conversion(
            affiliate_program_id=program.id, affiliate_link_id=link.id,
            sale_amount=Decimal("10.00"), external_conversion_id=f"legacy-{uuid4().hex}",
        )
        assert legacy_click.affiliate_link_id == link.id
        assert legacy_conversion.affiliate_link_id == link.id
        assert db.query(AttributionClick).count() == before_clicks
        assert db.query(AttributionFact).count() == before_facts
    finally:
        db.close()
