"""Persistence for versioned SLA policies, instances, pauses and events."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from eventflow_work_management.models import (
    SlaEvent,
    SlaInstance,
    SlaPauseInterval,
    SlaPolicy,
)
from eventflow_work_management.repositories.base import Repository


class SlaPolicyRepository(Repository):
    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def add(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID | None,
        name: str,
        version: int,
        response_minutes: int | None,
        resolution_minutes: int | None,
        timezone: str,
        business_hours: dict,
        holidays: list,
        pause_statuses: list,
        warning_threshold_percent: int,
        created_by: UUID,
        supersedes_id: UUID | None,
    ) -> SlaPolicy:
        policy = SlaPolicy(
            id=uuid4(),
            workspace_id=workspace_id,
            project_id=project_id,
            name=name,
            version=version,
            status="draft",
            response_minutes=response_minutes,
            resolution_minutes=resolution_minutes,
            timezone=timezone,
            business_hours=business_hours,
            holidays=holidays,
            pause_statuses=pause_statuses,
            warning_threshold_percent=warning_threshold_percent,
            created_by=created_by,
            supersedes_id=supersedes_id,
        )
        self._session.add(policy)
        self._session.flush()
        return policy

    def get(self, *, workspace_id: UUID, policy_id: UUID) -> SlaPolicy | None:
        statement = select(SlaPolicy).where(
            SlaPolicy.workspace_id == workspace_id, SlaPolicy.id == policy_id
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get_for_update(self, *, workspace_id: UUID, policy_id: UUID) -> SlaPolicy | None:
        statement = (
            select(SlaPolicy)
            .where(SlaPolicy.workspace_id == workspace_id, SlaPolicy.id == policy_id)
            .with_for_update()
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_page(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID | None,
        include_workspace_default: bool,
        status: str | None,
        limit: int,
        after: tuple[datetime, UUID] | None = None,
    ) -> list[SlaPolicy]:
        statement = select(SlaPolicy).where(SlaPolicy.workspace_id == workspace_id)
        if include_workspace_default:
            if project_id is not None:
                statement = statement.where(
                    (SlaPolicy.project_id == project_id)
                    | (SlaPolicy.project_id.is_(None))
                )
            # project_id None means "workspace defaults only"
            elif project_id is None:
                statement = statement.where(SlaPolicy.project_id.is_(None))
        elif project_id is None:
            statement = statement.where(SlaPolicy.project_id.is_(None))
        else:
            statement = statement.where(SlaPolicy.project_id == project_id)
        if status is not None:
            statement = statement.where(SlaPolicy.status == status)
        statement = statement.order_by(SlaPolicy.created_at, SlaPolicy.id)
        if after is not None:
            statement = statement.where(
                tuple_(SlaPolicy.created_at, SlaPolicy.id) > after
            )
        statement = statement.limit(limit)
        return list(self._session.execute(statement).scalars())

    def latest_version(
        self, *, workspace_id: UUID, project_id: UUID | None, name: str
    ) -> SlaPolicy | None:
        statement = (
            select(SlaPolicy)
            .where(
                SlaPolicy.workspace_id == workspace_id,
                SlaPolicy.name == name,
            )
            .order_by(SlaPolicy.version.desc())
            .limit(1)
        )
        if project_id is None:
            statement = statement.where(SlaPolicy.project_id.is_(None))
        else:
            statement = statement.where(SlaPolicy.project_id == project_id)
        return self._session.execute(statement).scalar_one_or_none()

    def active_for_project(
        self, *, workspace_id: UUID, project_id: UUID
    ) -> SlaPolicy | None:
        """Resolve the active policy with deterministic project > workspace."""
        project_statement = (
            select(SlaPolicy)
            .where(
                SlaPolicy.workspace_id == workspace_id,
                SlaPolicy.project_id == project_id,
                SlaPolicy.status == "active",
            )
            .order_by(SlaPolicy.version.desc())
            .limit(1)
        )
        project_policy = self._session.execute(project_statement).scalar_one_or_none()
        if project_policy is not None:
            return project_policy
        workspace_statement = (
            select(SlaPolicy)
            .where(
                SlaPolicy.workspace_id == workspace_id,
                SlaPolicy.project_id.is_(None),
                SlaPolicy.status == "active",
            )
            .order_by(SlaPolicy.version.desc())
            .limit(1)
        )
        return self._session.execute(workspace_statement).scalar_one_or_none()

    def active_by_name(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID | None,
        name: str,
        exclude_id: UUID | None = None,
    ) -> SlaPolicy | None:
        statement = select(SlaPolicy).where(
            SlaPolicy.workspace_id == workspace_id,
            SlaPolicy.name == name,
            SlaPolicy.status == "active",
        )
        statement = (
            statement.where(SlaPolicy.project_id.is_(None))
            if project_id is None
            else statement.where(SlaPolicy.project_id == project_id)
        )
        if exclude_id is not None:
            statement = statement.where(SlaPolicy.id != exclude_id)
        return self._session.execute(statement).scalar_one_or_none()


class SlaInstanceRepository(Repository):
    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def add(self, **values) -> SlaInstance:
        instance = SlaInstance(**values)
        self._session.add(instance)
        self._session.flush()
        return instance

    def get_for_work_item(
        self, *, workspace_id: UUID, work_item_id: UUID
    ) -> SlaInstance | None:
        statement = select(SlaInstance).where(
            SlaInstance.workspace_id == workspace_id,
            SlaInstance.work_item_id == work_item_id,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def get_for_update(self, *, workspace_id: UUID, instance_id: UUID) -> SlaInstance | None:
        statement = (
            select(SlaInstance)
            .where(
                SlaInstance.workspace_id == workspace_id,
                SlaInstance.id == instance_id,
            )
            .with_for_update()
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_due(self, *, now: datetime, limit: int) -> list[SlaInstance]:
        statement = (
            select(SlaInstance)
            .where(
                SlaInstance.status.in_(("pending", "running", "paused")),
                SlaInstance.next_evaluation_at.is_not(None),
                SlaInstance.next_evaluation_at <= now,
            )
            .order_by(SlaInstance.next_evaluation_at, SlaInstance.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(self._session.execute(statement).scalars())

    def list_for_workspace(
        self, *, workspace_id: UUID, project_id: UUID | None = None
    ) -> list[SlaInstance]:
        statement = select(SlaInstance).where(
            SlaInstance.workspace_id == workspace_id
        )
        if project_id is not None:
            statement = statement.where(SlaInstance.project_id == project_id)
        return list(self._session.execute(statement).scalars())


class SlaPauseIntervalRepository(Repository):
    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def open_interval(
        self, *, workspace_id: UUID, instance_id: UUID, reason: str, started_at: datetime
    ) -> SlaPauseInterval:
        interval = SlaPauseInterval(
            id=uuid4(),
            workspace_id=workspace_id,
            instance_id=instance_id,
            reason=reason,
            started_at=started_at,
        )
        self._session.add(interval)
        self._session.flush()
        return interval

    def open_for_instance(
        self, *, workspace_id: UUID, instance_id: UUID
    ) -> SlaPauseInterval | None:
        statement = (
            select(SlaPauseInterval)
            .where(
                SlaPauseInterval.workspace_id == workspace_id,
                SlaPauseInterval.instance_id == instance_id,
                SlaPauseInterval.ended_at.is_(None),
            )
            .order_by(SlaPauseInterval.started_at.desc())
            .limit(1)
        )
        return self._session.execute(statement).scalar_one_or_none()

    def close_interval(
        self, interval: SlaPauseInterval, *, ended_at: datetime, seconds: int
    ) -> None:
        interval.ended_at = ended_at
        interval.seconds = seconds
        self._session.flush()

    def list_for_instance(
        self, *, workspace_id: UUID, instance_id: UUID
    ) -> list[SlaPauseInterval]:
        statement = (
            select(SlaPauseInterval)
            .where(
                SlaPauseInterval.workspace_id == workspace_id,
                SlaPauseInterval.instance_id == instance_id,
            )
            .order_by(SlaPauseInterval.started_at, SlaPauseInterval.id)
        )
        return list(self._session.execute(statement).scalars())


class SlaEventRepository(Repository):
    def __init__(self, session: Session) -> None:
        super().__init__(session)

    def append(
        self,
        *,
        workspace_id: UUID,
        instance_id: UUID,
        event_type: str,
        due_at: datetime,
        occurred_at: datetime,
        payload: dict | None = None,
    ) -> SlaEvent:
        event = SlaEvent(
            id=uuid4(),
            workspace_id=workspace_id,
            instance_id=instance_id,
            event_type=event_type,
            due_at=due_at,
            occurred_at=occurred_at,
            payload=payload or {},
        )
        self._session.add(event)
        self._session.flush()
        return event

    def get(
        self, *, instance_id: UUID, event_type: str, due_at: datetime
    ) -> SlaEvent | None:
        statement = select(SlaEvent).where(
            SlaEvent.instance_id == instance_id,
            SlaEvent.event_type == event_type,
            SlaEvent.due_at == due_at,
        )
        return self._session.execute(statement).scalar_one_or_none()

    def list_for_instance(
        self, *, workspace_id: UUID, instance_id: UUID
    ) -> list[SlaEvent]:
        statement = (
            select(SlaEvent)
            .where(
                SlaEvent.workspace_id == workspace_id,
                SlaEvent.instance_id == instance_id,
            )
            .order_by(SlaEvent.occurred_at, SlaEvent.id)
        )
        return list(self._session.execute(statement).scalars())
