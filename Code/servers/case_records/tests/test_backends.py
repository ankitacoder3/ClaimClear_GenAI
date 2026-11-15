"""The case store on its production backends: PostgreSQL index and MinIO (S3) files.

Run against the services in deploy/storage.compose.yml:

    CLAIMCLEAR_TEST_POSTGRES=postgresql://claimclear:claimclear@127.0.0.1:5432/claimclear
    CLAIMCLEAR_TEST_S3=s3://claimclear-test?endpoint=127.0.0.1:9000&secure=0
    CLAIMCLEAR_S3_ACCESS_KEY=claimclear  CLAIMCLEAR_S3_SECRET_KEY=claimclear-secret

Skipped when those are not set. Each run uses its own table prefix and key prefix.
"""

import asyncio
import os
import uuid

import pytest

from case_records.backends import (JsonIndex, LocalBlobs, PostgresIndex, S3Blobs, blobs_for, connect_postgres,
                                   index_for)
from case_records.store import CaseStore, StoreError

PG = os.environ.get("CLAIMCLEAR_TEST_POSTGRES")
S3 = os.environ.get("CLAIMCLEAR_TEST_S3")
needs_services = pytest.mark.skipif(not (PG and S3), reason="set CLAIMCLEAR_TEST_POSTGRES and CLAIMCLEAR_TEST_S3")


@pytest.fixture
def remote():
    """Index and blob URLs private to this test, dropped afterwards."""
    run_id = "t" + uuid.uuid4().hex[:10]
    sep = "&" if "?" in PG else "?"
    yield f"{PG}{sep}table_prefix={run_id}_", f"{S3}&prefix={run_id}/"
    con = connect_postgres(PG)
    cur = con.cursor()
    cur.execute(f"DROP TABLE IF EXISTS {run_id}_documents")
    cur.execute(f"DROP TABLE IF EXISTS {run_id}_cases")
    con.commit()
    con.close()


def test_defaults_are_the_local_files(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAIMCLEAR_CASE_INDEX", raising=False)
    monkeypatch.delenv("CLAIMCLEAR_BLOB_STORE", raising=False)
    assert isinstance(index_for(tmp_path), JsonIndex) and isinstance(blobs_for(tmp_path), LocalBlobs)


def test_bad_urls_are_refused():
    with pytest.raises(ValueError):
        S3Blobs("http://bucket")
    with pytest.raises(ValueError):
        PostgresIndex("postgresql://u:p@127.0.0.1:1/db?table_prefix=Bad;DROP")


@needs_services
def test_store_round_trip_on_postgres_and_minio(remote, tmp_path, doc):
    index_url, blob_url = remote
    store = CaseStore(tmp_path / "unused", index=PostgresIndex(index_url), blobs=S3Blobs(blob_url))
    case = store.create_case("AS-2025-100478", salt="backend")
    rec = store.add_document(case.case_id, doc("GEN-02"), role="bill")
    assert not (tmp_path / "unused").exists()                   # nothing written locally

    again = CaseStore(tmp_path / "unused", index=PostgresIndex(index_url), blobs=S3Blobs(blob_url))
    record, data = again.read(case.case_id, rec.document_id)
    assert record == rec and data == doc("GEN-02").read_bytes()
    assert again.role(case.case_id, rec.document_id) == "bill"
    with pytest.raises(StoreError) as e:
        again.document(case.case_id, rec.document_id)          # no local paths on S3
    assert e.value.code == "DOCUMENT_INTEGRITY"


@needs_services
def test_a_changed_object_is_caught(remote, tmp_path, doc):
    index_url, blob_url = remote
    blobs = S3Blobs(blob_url)
    store = CaseStore(tmp_path, index=PostgresIndex(index_url), blobs=blobs)
    case = store.create_case("AS-2025-100478", salt="tamper")
    rec = store.add_document(case.case_id, doc("GEN-02"), role="bill")
    blobs.put(rec.stored_name, b"%PDF-1.7 replaced", rec.media_type)
    with pytest.raises(StoreError) as e:
        store.read(case.case_id, rec.document_id)
    assert e.value.code == "DOCUMENT_INTEGRITY"


@needs_services
def test_the_mcp_server_reads_from_the_production_backends(remote, tmp_path, doc, dataset_dir, monkeypatch):
    from mcp import Client
    from case_records.app import create_server
    index_url, blob_url = remote
    monkeypatch.setenv("CLAIMCLEAR_CASE_INDEX", index_url)
    monkeypatch.setenv("CLAIMCLEAR_BLOB_STORE", blob_url)
    store = CaseStore(tmp_path)
    case = store.create_case("AS-2025-100478", salt="mcp")
    rec = store.add_document(case.case_id, doc("ADV-02"), role="bill")
    server = create_server(tmp_path, dataset_dir / "dev" / "reference", use_ocr=False)

    async def go():
        async with Client(server) as client:
            return await client.call_tool("get_document_text", {"case_id": case.case_id, "document_id": rec.document_id})
    page = asyncio.run(go()).structured_content["pages"][0]
    assert "SYSTEM OVERRIDE" in page["hidden_text"] and "SYSTEM OVERRIDE" not in page["text"]
