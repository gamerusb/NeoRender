from __future__ import annotations

from core import tenancy


def test_normalize_tenant_id_accepts_valid_lowercase() -> None:
    assert tenancy.normalize_tenant_id("acme-tenant_1") == "acme-tenant_1"


def test_normalize_tenant_id_normalizes_case_and_spaces() -> None:
    assert tenancy.normalize_tenant_id("  AcMe  ") == "acme"


def test_normalize_tenant_id_rejects_invalid_values() -> None:
    assert tenancy.normalize_tenant_id("") == tenancy.DEFAULT_TENANT_ID
    assert tenancy.normalize_tenant_id("bad/path") == tenancy.DEFAULT_TENANT_ID
    assert tenancy.normalize_tenant_id("кириллица") == tenancy.DEFAULT_TENANT_ID


def test_tenant_id_from_environ(monkeypatch) -> None:
    monkeypatch.setenv("NEORENDER_TENANT_ID", " Team_A ")
    assert tenancy.tenant_id_from_environ() == "team_a"
