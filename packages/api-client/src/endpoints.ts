import type {
  Board,
  BoardCardPage,
  BoardColumn,
  Consultation,
  ConsultationPage,
  Notification,
  NotificationPage,
  Project,
  ProjectRepository,
  ProjectTriageConfiguration,
  ProjectTriageTemplate,
  ProjectTriageTemplatePage,
  Proposal,
  ProposalPage,
  WorkItem,
  WorkItemPage,
  Workspace,
  WorkspaceMember,
} from "@eventflow/domain";
import type { ApiClient, QueryValue } from "./client";
import type {
  AuthSessionListItem,
  BoardCardFilters,
  ConsultationFilters,
  NotificationFilters,
  ProposalFilters,
  SessionResponse,
  TriageTemplateFilters,
  WorkItemFilters,
} from "./types";

function segment(value: string): string {
  return encodeURIComponent(value);
}

function compact(filters: object): Record<string, QueryValue> {
  return Object.fromEntries(
    Object.entries(filters).filter(([, value]) => value !== undefined),
  ) as Record<string, QueryValue>;
}

export function createWorkManagementApi(client: ApiClient) {
  return {
    async getSession(): Promise<SessionResponse> {
      return client.requestData<SessionResponse>("/v1/auth/session", {
        suppressUnauthorizedEvent: true,
      });
    },

    async refreshSession(): Promise<SessionResponse> {
      return client.requestData<SessionResponse>("/v1/auth/refresh", {
        method: "POST",
        suppressUnauthorizedEvent: true,
      });
    },

    async logout(): Promise<void> {
      await client.request<void>("/v1/auth/logout", { method: "POST" });
    },

    async listAuthSessions(): Promise<AuthSessionListItem[]> {
      return client.requestData<AuthSessionListItem[]>("/v1/auth/sessions");
    },

    async revokeAuthSession(sessionId: string): Promise<void> {
      await client.request<void>(
        `/v1/auth/sessions/${segment(sessionId)}`,
        { method: "DELETE" },
      );
    },

    async listWorkspaces(): Promise<Workspace[]> {
      return client.requestData<Workspace[]>("/v1/workspaces");
    },

    async getWorkspace(workspaceId: string): Promise<Workspace> {
      return client.requestData<Workspace>(
        `/v1/workspaces/${segment(workspaceId)}`,
      );
    },

    async listProjects(workspaceId: string): Promise<Project[]> {
      return client.requestData<Project[]>(
        `/v1/workspaces/${segment(workspaceId)}/projects`,
      );
    },

    async getProject(
      workspaceId: string,
      projectId: string,
    ): Promise<Project> {
      return client.requestData<Project>(
        `/v1/workspaces/${segment(workspaceId)}/projects/${segment(projectId)}`,
      );
    },

    async listWorkspaceMembers(
      workspaceId: string,
    ): Promise<WorkspaceMember[]> {
      return client.requestData<WorkspaceMember[]>(
        `/v1/workspaces/${segment(workspaceId)}/members`,
      );
    },

    async listConsultations(
      workspaceId: string,
      filters: ConsultationFilters = {},
    ): Promise<ConsultationPage> {
      return client.requestData<ConsultationPage>(
        `/v1/workspaces/${segment(workspaceId)}/consultations`,
        { query: compact(filters) },
      );
    },

    async getConsultation(
      workspaceId: string,
      consultationId: string,
    ): Promise<Consultation> {
      return client.requestData<Consultation>(
        `/v1/workspaces/${segment(workspaceId)}/consultations/${segment(consultationId)}`,
      );
    },

    async listConsultationProposals(
      workspaceId: string,
      consultationId: string,
      filters: ProposalFilters = {},
    ): Promise<ProposalPage> {
      return client.requestData<ProposalPage>(
        `/v1/workspaces/${segment(workspaceId)}/consultations/${segment(consultationId)}/proposals`,
        { query: compact(filters) },
      );
    },

    async getProposal(
      workspaceId: string,
      proposalId: string,
    ): Promise<Proposal> {
      return client.requestData<Proposal>(
        `/v1/workspaces/${segment(workspaceId)}/proposals/${segment(proposalId)}`,
      );
    },

    async listWorkItems(
      workspaceId: string,
      filters: WorkItemFilters = {},
    ): Promise<WorkItemPage> {
      return client.requestData<WorkItemPage>(
        `/v1/workspaces/${segment(workspaceId)}/work-items`,
        { query: compact(filters) },
      );
    },

    async getWorkItem(
      workspaceId: string,
      workItemId: string,
    ): Promise<WorkItem> {
      return client.requestData<WorkItem>(
        `/v1/workspaces/${segment(workspaceId)}/work-items/${segment(workItemId)}`,
      );
    },

    async listBoards(
      workspaceId: string,
      projectId?: string | null,
      includeArchived = false,
    ): Promise<Board[]> {
      return client.requestData<Board[]>(
        `/v1/workspaces/${segment(workspaceId)}/boards`,
        {
          query: compact({
            project_id: projectId ?? undefined,
            include_archived: includeArchived,
          }),
        },
      );
    },

    async getBoard(workspaceId: string, boardId: string): Promise<Board> {
      return client.requestData<Board>(
        `/v1/workspaces/${segment(workspaceId)}/boards/${segment(boardId)}`,
      );
    },

    async listBoardColumns(
      workspaceId: string,
      boardId: string,
    ): Promise<BoardColumn[]> {
      return client.requestData<BoardColumn[]>(
        `/v1/workspaces/${segment(workspaceId)}/boards/${segment(boardId)}/columns`,
      );
    },

    async listBoardCards(
      workspaceId: string,
      boardId: string,
      filters: BoardCardFilters = {},
    ): Promise<BoardCardPage> {
      return client.requestData<BoardCardPage>(
        `/v1/workspaces/${segment(workspaceId)}/boards/${segment(boardId)}/cards`,
        { query: compact(filters) },
      );
    },

    async listNotifications(
      workspaceId: string,
      filters: NotificationFilters = {},
    ): Promise<NotificationPage> {
      return client.requestData<NotificationPage>(
        `/v1/workspaces/${segment(workspaceId)}/notifications`,
        { query: compact(filters) },
      );
    },

    async markNotification(
      workspaceId: string,
      notificationId: string,
      read: boolean,
    ): Promise<Notification> {
      return client.requestData<Notification>(
        `/v1/workspaces/${segment(workspaceId)}/notifications/${segment(notificationId)}`,
        { method: "PATCH", body: { read } },
      );
    },

    async getTriageConfiguration(
      workspaceId: string,
      projectId: string,
    ): Promise<ProjectTriageConfiguration> {
      return client.requestData<ProjectTriageConfiguration>(
        `/v1/workspaces/${segment(workspaceId)}/projects/${segment(projectId)}/triage-configuration`,
      );
    },

    async listTriageTemplates(
      workspaceId: string,
      projectId: string,
      filters: TriageTemplateFilters = {},
    ): Promise<ProjectTriageTemplatePage> {
      return client.requestData<ProjectTriageTemplatePage>(
        `/v1/workspaces/${segment(workspaceId)}/projects/${segment(projectId)}/triage-templates`,
        { query: compact(filters) },
      );
    },

    async getTriageTemplate(
      workspaceId: string,
      projectId: string,
      templateId: string,
    ): Promise<ProjectTriageTemplate> {
      return client.requestData<ProjectTriageTemplate>(
        `/v1/workspaces/${segment(workspaceId)}/projects/${segment(projectId)}/triage-templates/${segment(templateId)}`,
      );
    },

    async listProjectRepositories(
      workspaceId: string,
      projectId: string,
    ): Promise<ProjectRepository[]> {
      return client.requestData<ProjectRepository[]>(
        `/v1/workspaces/${segment(workspaceId)}/projects/${segment(projectId)}/repositories`,
      );
    },
  };
}

export type WorkManagementApi = ReturnType<typeof createWorkManagementApi>;
