import type {
  BoardCardFilters,
  ConsultationFilters,
  NotificationFilters,
  ProposalFilters,
  TriageTemplateFilters,
  WorkItemFilters,
} from "./types";

export const queryKeys = {
  session: ["session"] as const,
  authSessions: ["auth", "sessions"] as const,
  workspaces: {
    all: ["workspaces"] as const,
    list: () => [...queryKeys.workspaces.all, "list"] as const,
    detail: (workspaceId: string) =>
      [...queryKeys.workspaces.all, workspaceId] as const,
    projects: (workspaceId: string) =>
      [...queryKeys.workspaces.detail(workspaceId), "projects"] as const,
    project: (workspaceId: string, projectId: string) =>
      [...queryKeys.workspaces.projects(workspaceId), projectId] as const,
    members: (workspaceId: string) =>
      [...queryKeys.workspaces.detail(workspaceId), "members"] as const,
    notifications: (
      workspaceId: string,
      filters: NotificationFilters = {},
    ) =>
      [
        ...queryKeys.workspaces.detail(workspaceId),
        "notifications",
        filters,
      ] as const,
  },
  consultations: {
    all: (workspaceId: string) =>
      [...queryKeys.workspaces.detail(workspaceId), "consultations"] as const,
    list: (workspaceId: string, filters: ConsultationFilters = {}) =>
      [...queryKeys.consultations.all(workspaceId), "list", filters] as const,
    detail: (workspaceId: string, consultationId: string) =>
      [
        ...queryKeys.consultations.all(workspaceId),
        consultationId,
      ] as const,
  },
  proposals: {
    all: (workspaceId: string) =>
      [...queryKeys.workspaces.detail(workspaceId), "proposals"] as const,
    list: (
      workspaceId: string,
      consultationId: string,
      filters: ProposalFilters = {},
    ) =>
      [
        ...queryKeys.proposals.all(workspaceId),
        "consultation",
        consultationId,
        filters,
      ] as const,
    detail: (workspaceId: string, proposalId: string) =>
      [...queryKeys.proposals.all(workspaceId), proposalId] as const,
  },
  workItems: {
    all: (workspaceId: string) =>
      [...queryKeys.workspaces.detail(workspaceId), "work-items"] as const,
    list: (workspaceId: string, filters: WorkItemFilters = {}) =>
      [...queryKeys.workItems.all(workspaceId), "list", filters] as const,
    detail: (workspaceId: string, workItemId: string) =>
      [...queryKeys.workItems.all(workspaceId), workItemId] as const,
  },
  boards: {
    all: (workspaceId: string) =>
      [...queryKeys.workspaces.detail(workspaceId), "boards"] as const,
    list: (workspaceId: string, projectId: string | null) =>
      [...queryKeys.boards.all(workspaceId), "list", projectId] as const,
    detail: (workspaceId: string, boardId: string) =>
      [...queryKeys.boards.all(workspaceId), boardId] as const,
    columns: (workspaceId: string, boardId: string) =>
      [...queryKeys.boards.detail(workspaceId, boardId), "columns"] as const,
    cards: (
      workspaceId: string,
      boardId: string,
      filters: BoardCardFilters = {},
    ) =>
      [
        ...queryKeys.boards.detail(workspaceId, boardId),
        "cards",
        filters,
      ] as const,
  },
  triage: {
    all: (workspaceId: string, projectId: string) =>
      [
        ...queryKeys.workspaces.detail(workspaceId),
        "triage",
        projectId,
      ] as const,
    configuration: (workspaceId: string, projectId: string) =>
      [...queryKeys.triage.all(workspaceId, projectId), "configuration"] as const,
    templates: (
      workspaceId: string,
      projectId: string,
      filters: TriageTemplateFilters = {},
    ) =>
      [
        ...queryKeys.triage.all(workspaceId, projectId),
        "templates",
        filters,
      ] as const,
    template: (
      workspaceId: string,
      projectId: string,
      templateId: string,
    ) =>
      [
        ...queryKeys.triage.all(workspaceId, projectId),
        "templates",
        templateId,
      ] as const,
  },
  repositories: {
    all: (workspaceId: string, projectId: string) =>
      [
        ...queryKeys.workspaces.detail(workspaceId),
        "repositories",
        projectId,
      ] as const,
    list: (workspaceId: string, projectId: string) =>
      [...queryKeys.repositories.all(workspaceId, projectId), "list"] as const,
  },
} as const;

export type QueryKey = ReturnType<
  | typeof queryKeys.workspaces.list
  | typeof queryKeys.workspaces.projects
  | typeof queryKeys.consultations.list
  | typeof queryKeys.consultations.detail
  | typeof queryKeys.workItems.list
  | typeof queryKeys.boards.list
  | typeof queryKeys.boards.cards
  | typeof queryKeys.triage.configuration
>;
