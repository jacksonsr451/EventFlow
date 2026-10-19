"""Unit tests for repository URL normalization (Issue #44)."""

from __future__ import annotations

import testrunner

from eventflow_work_management.security.errors import ProblemError
from eventflow_work_management.services.project_repository_management import (
    normalize_repository_url,
)


def _rejects(url: str, **kwargs) -> None:
    try:
        normalize_repository_url(url, **kwargs)
    except ProblemError as error:
        assert error.status_code == 400
        return
    raise AssertionError(f"expected rejection for {url!r}")


def test_equivalent_https_and_ssh_forms_normalize_to_one_url():
    https = normalize_repository_url(
        "HTTPS://GitHub.COM/Acme/Payments.git/", provider_instance_id="github.com"
    )
    ssh = normalize_repository_url("ssh://git@github.com/Acme/Payments.git")
    scp = normalize_repository_url("git@github.com:Acme/Payments")
    expected = "https://github.com/Acme/Payments"
    assert https.canonical_repository_url == expected
    assert ssh.canonical_repository_url == expected
    assert scp.canonical_repository_url == expected
    assert https.repository_full_path == "Acme/Payments"
    assert https.provider_instance_id == "github.com"


def test_full_path_must_match_the_url_and_instance_must_match_the_host():
    normalized = normalize_repository_url(
        "https://gitlab.example.com/group/sub/repo.git",
        repository_full_path="group/sub/repo",
        provider_instance_id="gitlab.example.com",
    )
    assert normalized.repository_full_path == "group/sub/repo"
    _rejects(
        "https://gitlab.example.com/group/sub/repo.git",
        repository_full_path="group/other",
    )
    _rejects(
        "https://gitlab.example.com/group/repo.git",
        provider_instance_id="gitlab.other.example",
    )


def test_credentials_ports_queries_and_insecure_schemes_are_rejected():
    _rejects("http://github.com/acme/payments")
    _rejects("https://user:secret@github.com/acme/payments")
    _rejects("https://token@github.com/acme/payments")
    _rejects("https://github.com:8443/acme/payments")
    _rejects("https://github.com/acme/payments?ref=main")
    _rejects("https://github.com/acme/payments#readme")
    _rejects("git@github.com:acme")
    _rejects("git@github.com:acme/payments with space")


def test_problem_error_shape_is_public_and_does_not_echo_the_url():
    _rejects("https://user:secret@github.com/acme/payments")
    try:
        normalize_repository_url("https://user:secret@github.com/acme/payments")
    except ProblemError as error:
        assert "secret" not in error.detail
        assert error.code == "VALIDATION_ERROR"
    else:  # pragma: no cover - defensive
        testrunner.fail("expected a validation error")
