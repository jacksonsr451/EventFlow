"""PostgreSQL integration tests for workspace administration and RBAC (Issue #9).

These cover the security-critical properties: tenant isolation and IDOR/BOLA
denial, owner invariants under concurrency, identity-bound invitation acceptance,
and role-assignment limits. They skip themselves when no test database is
configured.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import re

from eventflow_work_management.authorization.policy import Action
from eventflow_work_management.authorization.service import AuthorizationService
from eventflow_work_management.models.membership import (
    WorkspaceInvitation,
    WorkspaceMembership,
)
from eventflow_work_management.security.crypto import digest_token
from eventflow_work_management.security.errors import ProblemError
from eventflow_work_management.security.principal import AuthenticatedPrincipal
from eventflow_work_management.security.repository import IdentityRepository
from eventflow_work_management.services.workspace_management import (
    InvitationService,
    MembershipService,
    ProjectService,
    WorkspaceService,
)
from sqlalchemy import select
from support import require_database_url, session_scope, temporary_database

ISSUER = "https://id.example.test/realms/eventflow"


def _identity(session, subject: str):
    identity, _ = IdentityRepository(session).resolve_or_create(
        issuer=ISSUER, subject=subject
    )
    session.commit()
    return identity


def _principal(identity) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=identity.id, issuer=identity.issuer, subject=identity.subject
    )


def _expect_status(status: int, call) -> ProblemError:
    try:
        call()
    except ProblemError as exc:
        assert exc.status_code == status, f"expected {status}, got {exc.status_code}"
        return exc
    raise AssertionError(f"expected ProblemError {status}")


def _seed_workspace(session, owner_subject: str = "owner-1"):
    owner = _identity(session, owner_subject)
    workspace = WorkspaceService(session).create(
        _principal(owner), name="Acme Inc", slug=f"acme-{owner.id.hex[:8]}"
    )
    return owner, workspace


def test_creator_becomes_owner_and_non_member_sees_404():
    with temporary_database(require_database_url()) as (_, engine):
        with session_scope(engine) as session:
            owner, workspace = _seed_workspace(session)
            outsider = _identity(session, "outsider-1")
            owners = session.execute(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == workspace.id
                )
            ).scalars().all()
            assert len(owners) == 1
            assert owners[0].role == "owner"
            assert owners[0].user_id == owner.id

        with session_scope(engine) as session:
            _expect_status(
                404,
                lambda: AuthorizationService(session).authorize(
                    _principal(outsider), workspace.id, Action.WORKSPACE_READ
                ),
            )


def test_foreign_membership_id_is_not_found_across_workspaces():
    with temporary_database(require_database_url()) as (_, engine):
        with session_scope(engine) as session:
            owner, workspace_a = _seed_workspace(session, "owner-a")
            _, workspace_b = _seed_workspace(session, "owner-b")
            target = session.execute(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == workspace_b.id
                )
            ).scalar_one()
            target_id = target.id

        with session_scope(engine) as session:
            context = AuthorizationService(session).authorize(
                _principal(owner), workspace_a.id, Action.MEMBERSHIP_UPDATE_ROLE
            )
            # The same membership id under workspace A's path must not be visible.
            _expect_status(
                404,
                lambda: MembershipService(session).change_role(
                    context, target_id, role="viewer"
                ),
            )


def test_invitation_acceptance_is_identity_bound_and_token_digested():
    with temporary_database(require_database_url()) as (_, engine):
        with session_scope(engine) as session:
            owner, workspace = _seed_workspace(session)
            invitee = _identity(session, "invitee-1")
            wrong = _identity(session, "wrong-user")
            owner_ctx = AuthorizationService(session).authorize(
                _principal(owner), workspace.id, Action.MEMBERSHIP_INVITE
            )
            created = InvitationService(session).create(
                owner_ctx, invited_user_id=invitee.id, role="contributor"
            )
            token = created.token
            invitation_id = created.invitation.id
            stored = session.get(WorkspaceInvitation, invitation_id)
            assert stored.token_digest == digest_token(token)
            assert token not in stored.token_digest

        with session_scope(engine) as session:
            # Wrong identity cannot accept even with the correct token.
            _expect_status(
                404,
                lambda: InvitationService(session).accept(
                    _principal(wrong),
                    workspace_id=workspace.id,
                    invitation_id=invitation_id,
                    token=token,
                ),
            )

        with session_scope(engine) as session:
            membership = InvitationService(session).accept(
                _principal(invitee),
                workspace_id=workspace.id,
                invitation_id=invitation_id,
                token=token,
            )
            assert membership.role == "contributor"
            assert membership.state == "active"
            assert session.get(WorkspaceInvitation, invitation_id).state == "accepted"

        with session_scope(engine) as session:
            # The token cannot be replayed.
            _expect_status(
                404,
                lambda: InvitationService(session).accept(
                    _principal(invitee),
                    workspace_id=workspace.id,
                    invitation_id=invitation_id,
                    token=token,
                ),
            )


def test_expired_invitation_is_rejected():
    with temporary_database(require_database_url()) as (_, engine):
        with session_scope(engine) as session:
            owner, workspace = _seed_workspace(session)
            invitee = _identity(session, "expiring-invitee")
            owner_ctx = AuthorizationService(session).authorize(
                _principal(owner), workspace.id, Action.MEMBERSHIP_INVITE
            )
            created = InvitationService(session).create(
                owner_ctx, invited_user_id=invitee.id, role="viewer"
            )
            stored = session.get(WorkspaceInvitation, created.invitation.id)
            stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            session.commit()
            invitation_id = stored.id
            token = created.token

        with session_scope(engine) as session:
            _expect_status(
                409,
                lambda: InvitationService(session).accept(
                    _principal(invitee),
                    workspace_id=workspace.id,
                    invitation_id=invitation_id,
                    token=token,
                ),
            )


def test_admin_cannot_touch_the_owner_seat_but_owner_can():
    with temporary_database(require_database_url()) as (_, engine):
        with session_scope(engine) as session:
            owner, workspace = _seed_workspace(session)
            admin = _identity(session, "admin-1")
            owner_ctx = AuthorizationService(session).authorize(
                _principal(owner), workspace.id, Action.MEMBERSHIP_INVITE
            )
            created = InvitationService(session).create(
                owner_ctx, invited_user_id=admin.id, role="admin"
            )
            InvitationService(session).accept(
                _principal(admin),
                workspace_id=workspace.id,
                invitation_id=created.invitation.id,
                token=created.token,
            )
            owner_membership_id = session.execute(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == workspace.id,
                    WorkspaceMembership.user_id == owner.id,
                )
            ).scalar_one().id

        with session_scope(engine) as session:
            admin_ctx = AuthorizationService(session).authorize(
                _principal(admin), workspace.id, Action.MEMBERSHIP_UPDATE_ROLE
            )
            _expect_status(
                403,
                lambda: MembershipService(session).change_role(
                    admin_ctx, owner_membership_id, role="viewer"
                ),
            )
            _expect_status(
                403,
                lambda: MembershipService(session).change_role(
                    admin_ctx, owner_membership_id, role="owner"
                ),
            )


def test_last_owner_cannot_be_demoted_or_revoked():
    with temporary_database(require_database_url()) as (_, engine):
        with session_scope(engine) as session:
            owner, workspace = _seed_workspace(session)
            owner_ctx = AuthorizationService(session).authorize(
                _principal(owner), workspace.id, Action.MEMBERSHIP_UPDATE_ROLE
            )
            owner_membership_id = owner_ctx.membership.id

        with session_scope(engine) as session:
            ctx = AuthorizationService(session).authorize(
                _principal(owner), workspace.id, Action.MEMBERSHIP_UPDATE_ROLE
            )
            _expect_status(
                409,
                lambda: MembershipService(session).change_role(
                    ctx, owner_membership_id, role="admin"
                ),
            )
        with session_scope(engine) as session:
            ctx = AuthorizationService(session).authorize(
                _principal(owner), workspace.id, Action.MEMBERSHIP_REVOKE
            )
            _expect_status(
                409,
                lambda: MembershipService(session).revoke(
                    ctx, owner_membership_id, reason="attempt"
                ),
            )


def test_transfer_ownership_preserves_an_owner():
    with temporary_database(require_database_url()) as (_, engine):
        with session_scope(engine) as session:
            owner, workspace = _seed_workspace(session)
            successor = _identity(session, "successor-1")
            owner_ctx = AuthorizationService(session).authorize(
                _principal(owner), workspace.id, Action.MEMBERSHIP_INVITE
            )
            created = InvitationService(session).create(
                owner_ctx, invited_user_id=successor.id, role="contributor"
            )
            InvitationService(session).accept(
                _principal(successor),
                workspace_id=workspace.id,
                invitation_id=created.invitation.id,
                token=created.token,
            )
            successor_membership_id = session.execute(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == workspace.id,
                    WorkspaceMembership.user_id == successor.id,
                )
            ).scalar_one().id
            owner_membership_id = owner_ctx.membership.id

        with session_scope(engine) as session:
            ctx = AuthorizationService(session).authorize(
                _principal(owner), workspace.id, Action.MEMBERSHIP_TRANSFER_OWNERSHIP
            )
            target, actor = MembershipService(session).transfer_ownership(
                ctx, successor_membership_id
            )
            assert target.role == "owner"
            assert actor.role == "admin"

        with session_scope(engine) as session:
            owners = session.execute(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.workspace_id == workspace.id,
                    WorkspaceMembership.role == "owner",
                    WorkspaceMembership.state == "active",
                )
            ).scalars().all()
            assert len(owners) == 1
            assert owners[0].id == successor_membership_id
            assert session.get(WorkspaceMembership, owner_membership_id).role == "admin"


def test_viewer_cannot_create_projects_but_can_read():
    with temporary_database(require_database_url()) as (_, engine):
        with session_scope(engine) as session:
            owner, workspace = _seed_workspace(session)
            viewer = _identity(session, "viewer-1")
            owner_ctx = AuthorizationService(session).authorize(
                _principal(owner), workspace.id, Action.MEMBERSHIP_INVITE
            )
            created = InvitationService(session).create(
                owner_ctx, invited_user_id=viewer.id, role="viewer"
            )
            InvitationService(session).accept(
                _principal(viewer),
                workspace_id=workspace.id,
                invitation_id=created.invitation.id,
                token=created.token,
            )

        with session_scope(engine) as session:
            _expect_status(
                403,
                lambda: AuthorizationService(session).authorize(
                    _principal(viewer), workspace.id, Action.PROJECT_CREATE
                ),
            )
            context = AuthorizationService(session).authorize(
                _principal(viewer), workspace.id, Action.PROJECT_READ
            )
            assert ProjectService(session).list(context) == []


def test_concurrent_workspace_creation_with_same_slug_creates_one():
    admin_url = require_database_url()
    with temporary_database(admin_url) as (_, engine):
        with session_scope(engine) as session:
            identity = _identity(session, "concurrent-creator")
        barrier = Barrier(2)

        def create():
            with session_scope(engine) as session:
                barrier.wait(timeout=10)
                try:
                    return WorkspaceService(session).create(
                        _principal(identity), name="Race Co", slug="race-co"
                    ).id
                except ProblemError as exc:
                    return exc.status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: create(), range(2)))
        successes = [result for result in results if not isinstance(result, int)]
        conflicts = [result for result in results if result == 409]
        assert len(successes) == 1
        assert len(conflicts) == 1


def test_invitation_token_is_not_disclosed_after_creation():
    with temporary_database(require_database_url()) as (_, engine):
        with session_scope(engine) as session:
            owner, workspace = _seed_workspace(session)
            invitee = _identity(session, "list-invitee")
            owner_ctx = AuthorizationService(session).authorize(
                _principal(owner), workspace.id, Action.MEMBERSHIP_INVITE
            )
            InvitationService(session).create(
                owner_ctx, invited_user_id=invitee.id, role="viewer"
            )

        with session_scope(engine) as session:
            invitation = session.execute(
                select(WorkspaceInvitation).where(
                    WorkspaceInvitation.workspace_id == workspace.id
                )
            ).scalar_one()
            # The ORM model has no plaintext-token attribute at all.
            assert not hasattr(invitation, "token")
            assert re.fullmatch(r"[0-9a-f]{64}", invitation.token_digest)
