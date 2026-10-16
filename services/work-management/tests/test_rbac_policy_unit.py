"""Unit tests for the Work Management RBAC policy (no database required).

These tests pin the action matrix, the role-assignment rules, and the owner
protection, and cross-check the policy against the ``x-required-roles`` declared
in the public OpenAPI contract so the two cannot drift.
"""

from __future__ import annotations

import pathlib

import yaml
from eventflow_work_management.authorization.policy import (
    ALL_ROLES,
    Action,
    assignable_roles,
    can_administer,
    can_assign_role,
    can_modify_membership,
    is_known_role,
    role_has_permission,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
OPENAPI_PATH = REPO_ROOT / "contracts" / "openapi" / "work-management.yaml"


def _roles_for(action: Action) -> set[str]:
    return {role for role in ALL_ROLES if role_has_permission(role, action)}


def test_deny_by_default_for_unknown_role_and_action():
    assert is_known_role("owner") is True
    assert is_known_role("superuser") is False
    assert role_has_permission("superuser", Action.WORKSPACE_READ) is False
    assert role_has_permission("viewer", Action.WORKSPACE_DELETE) is False


def test_viewer_is_read_only():
    assert role_has_permission("viewer", Action.WORKSPACE_READ)
    assert role_has_permission("viewer", Action.PROJECT_READ)
    assert not role_has_permission("viewer", Action.PROJECT_CREATE)
    assert not role_has_permission("viewer", Action.MEMBERSHIP_INVITE)
    assert not role_has_permission("viewer", Action.CONSULTATION_CREATE)


def test_role_specific_mutations():
    assert role_has_permission("contributor", Action.CONSULTATION_CREATE)
    assert role_has_permission("contributor", Action.BOARD_MANAGE)
    assert not role_has_permission("contributor", Action.APPROVAL_DECIDE)
    assert not role_has_permission("contributor", Action.CONSULTATION_TRIAGE)

    assert role_has_permission("approver", Action.APPROVAL_DECIDE)
    assert not role_has_permission("approver", Action.CONSULTATION_TRIAGE)

    assert role_has_permission("triager", Action.CONSULTATION_TRIAGE)
    assert not role_has_permission("triager", Action.APPROVAL_DECIDE)


def test_owner_has_every_action():
    for action in Action:
        assert role_has_permission("owner", action), action


def test_admin_cannot_grant_or_modify_the_owner_seat():
    assert can_administer("admin") is True
    assert can_administer("triager") is False
    assert can_assign_role("admin", "owner") is False
    assert can_assign_role("admin", "contributor") is True
    assert can_assign_role("owner", "owner") is True
    assert can_assign_role("triager", "contributor") is False

    assert can_modify_membership("admin", "owner") is False
    assert can_modify_membership("admin", "admin") is True
    assert can_modify_membership("owner", "owner") is True
    assert can_modify_membership("contributor", "viewer") is False
    assert assignable_roles("admin") == ALL_ROLES - {"owner"}


def test_policy_matches_declared_openapi_roles():
    with OPENAPI_PATH.open(encoding="utf-8") as stream:
        openapi = yaml.safe_load(stream)

    expected = {
        "createWorkspace": None,  # authenticated-only, see x-authorization-scope
        "updateWorkspace": Action.WORKSPACE_UPDATE,
        "createProject": Action.PROJECT_CREATE,
        "updateProject": Action.PROJECT_UPDATE,
        "changeMemberRole": Action.MEMBERSHIP_UPDATE_ROLE,
        "revokeMember": Action.MEMBERSHIP_REVOKE,
        "transferOwnership": Action.MEMBERSHIP_TRANSFER_OWNERSHIP,
        "createInvitation": Action.MEMBERSHIP_INVITE,
        "createConsultation": Action.CONSULTATION_CREATE,
        "createConsultationDraft": Action.CONSULTATION_CREATE,
        "updateConsultationDraft": Action.CONSULTATION_UPDATE,
        "submitConsultationDraft": Action.CONSULTATION_SUBMIT,
        "triageConsultation": Action.CONSULTATION_TRIAGE,
        "decideProposal": Action.APPROVAL_DECIDE,
        "moveBoardCard": Action.BOARD_MANAGE,
    }
    operations = {}
    for item in openapi["paths"].values():
        for method, operation in item.items():
            if method in {"get", "post", "put", "patch", "delete"}:
                operations[operation["operationId"]] = operation

    for operation_id, action in expected.items():
        operation = operations[operation_id]
        declared = set(operation["x-required-roles"])
        if action is None:
            assert operation.get("x-authorization-scope") == "authenticated"
            continue
        assert declared == _roles_for(action), (
            f"{operation_id} declares {sorted(declared)} but policy grants "
            f"{sorted(_roles_for(action))}"
        )


def test_authenticated_only_operations_are_declared():
    with OPENAPI_PATH.open(encoding="utf-8") as stream:
        openapi = yaml.safe_load(stream)
    authenticated_only = {
        operation["operationId"]
        for item in openapi["paths"].values()
        for method, operation in item.items()
        if method in {"get", "post", "put", "patch", "delete"}
        and operation.get("x-authorization-scope") == "authenticated"
    }
    assert authenticated_only == {
        "createWorkspace",
        "listWorkspaces",
        "acceptInvitation",
    }
