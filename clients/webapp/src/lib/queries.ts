import {
  queryKeys,
  type BoardCardFilters,
  type ConsultationFilters,
  type NotificationFilters,
  type ProposalFilters,
  type WorkItemFilters,
} from "@eventflow/api-client";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { api } from "./api";

export const PAGE_SIZE = 25;

export function useWorkspaceList() {
  return useQuery({
    queryKey: queryKeys.workspaces.list(),
    queryFn: () => api.listWorkspaces(),
    staleTime: 30_000,
  });
}

export function useProjectList(workspaceId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.workspaces.projects(workspaceId ?? "none"),
    queryFn: () => api.listProjects(workspaceId!),
    enabled: Boolean(workspaceId),
    staleTime: 30_000,
  });
}

export function useProject(
  workspaceId: string | undefined,
  projectId: string | undefined,
) {
  return useQuery({
    queryKey: queryKeys.workspaces.project(
      workspaceId ?? "none",
      projectId ?? "none",
    ),
    queryFn: () => api.getProject(workspaceId!, projectId!),
    enabled: Boolean(workspaceId && projectId),
  });
}

export function useWorkspaceMembers(workspaceId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.workspaces.members(workspaceId ?? "none"),
    queryFn: () => api.listWorkspaceMembers(workspaceId!),
    enabled: Boolean(workspaceId),
    staleTime: 60_000,
  });
}

export function useConsultations(
  workspaceId: string | undefined,
  filters: ConsultationFilters,
  limit = PAGE_SIZE,
) {
  return useInfiniteQuery({
    queryKey: queryKeys.consultations.list(workspaceId ?? "none", {
      ...filters,
      limit,
    }),
    queryFn: ({ pageParam }) =>
      api.listConsultations(workspaceId!, {
        ...filters,
        limit,
        cursor: pageParam,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) =>
      lastPage.page_info.has_more
        ? (lastPage.page_info.next_cursor ?? undefined)
        : undefined,
    enabled: Boolean(workspaceId),
  });
}

export function useConsultation(
  workspaceId: string | undefined,
  consultationId: string | undefined,
) {
  return useQuery({
    queryKey: queryKeys.consultations.detail(
      workspaceId ?? "none",
      consultationId ?? "none",
    ),
    queryFn: () => api.getConsultation(workspaceId!, consultationId!),
    enabled: Boolean(workspaceId && consultationId),
  });
}

export function useConsultationProposals(
  workspaceId: string | undefined,
  consultationId: string | undefined,
  filters: ProposalFilters,
  limit = PAGE_SIZE,
) {
  return useInfiniteQuery({
    queryKey: queryKeys.proposals.list(
      workspaceId ?? "none",
      consultationId ?? "none",
      { ...filters, limit },
    ),
    queryFn: ({ pageParam }) =>
      api.listConsultationProposals(workspaceId!, consultationId!, {
        ...filters,
        limit,
        cursor: pageParam,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) =>
      lastPage.page_info.has_more
        ? (lastPage.page_info.next_cursor ?? undefined)
        : undefined,
    enabled: Boolean(workspaceId && consultationId),
  });
}

export function useProposal(
  workspaceId: string | undefined,
  proposalId: string | undefined,
) {
  return useQuery({
    queryKey: queryKeys.proposals.detail(
      workspaceId ?? "none",
      proposalId ?? "none",
    ),
    queryFn: () => api.getProposal(workspaceId!, proposalId!),
    enabled: Boolean(workspaceId && proposalId),
  });
}

export function useWorkItems(
  workspaceId: string | undefined,
  filters: WorkItemFilters,
  limit = PAGE_SIZE,
) {
  return useInfiniteQuery({
    queryKey: queryKeys.workItems.list(workspaceId ?? "none", {
      ...filters,
      limit,
    }),
    queryFn: ({ pageParam }) =>
      api.listWorkItems(workspaceId!, {
        ...filters,
        limit,
        cursor: pageParam,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) =>
      lastPage.page_info.has_more
        ? (lastPage.page_info.next_cursor ?? undefined)
        : undefined,
    enabled: Boolean(workspaceId),
  });
}

export function useWorkItem(
  workspaceId: string | undefined,
  workItemId: string | undefined,
) {
  return useQuery({
    queryKey: queryKeys.workItems.detail(
      workspaceId ?? "none",
      workItemId ?? "none",
    ),
    queryFn: () => api.getWorkItem(workspaceId!, workItemId!),
    enabled: Boolean(workspaceId && workItemId),
  });
}

export function useBoards(
  workspaceId: string | undefined,
  projectId: string | null,
  includeArchived = false,
) {
  return useQuery({
    queryKey: [
      ...queryKeys.boards.list(workspaceId ?? "none", projectId),
      includeArchived,
    ],
    queryFn: () => api.listBoards(workspaceId!, projectId, includeArchived),
    enabled: Boolean(workspaceId),
  });
}

export function useBoard(
  workspaceId: string | undefined,
  boardId: string | undefined,
) {
  return useQuery({
    queryKey: queryKeys.boards.detail(workspaceId ?? "none", boardId ?? "none"),
    queryFn: () => api.getBoard(workspaceId!, boardId!),
    enabled: Boolean(workspaceId && boardId),
  });
}

export function useBoardColumns(
  workspaceId: string | undefined,
  boardId: string | undefined,
) {
  return useQuery({
    queryKey: queryKeys.boards.columns(
      workspaceId ?? "none",
      boardId ?? "none",
    ),
    queryFn: () => api.listBoardColumns(workspaceId!, boardId!),
    enabled: Boolean(workspaceId && boardId),
  });
}

export function useBoardCards(
  workspaceId: string | undefined,
  boardId: string | undefined,
  filters: BoardCardFilters = {},
  limit = 100,
) {
  return useInfiniteQuery({
    queryKey: queryKeys.boards.cards(
      workspaceId ?? "none",
      boardId ?? "none",
      { ...filters, limit },
    ),
    queryFn: ({ pageParam }) =>
      api.listBoardCards(workspaceId!, boardId!, {
        ...filters,
        limit,
        cursor: pageParam,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) =>
      lastPage.page_info.has_more
        ? (lastPage.page_info.next_cursor ?? undefined)
        : undefined,
    enabled: Boolean(workspaceId && boardId),
  });
}

export function useNotifications(
  workspaceId: string | undefined,
  filters: NotificationFilters,
  limit = 20,
) {
  return useInfiniteQuery({
    queryKey: queryKeys.workspaces.notifications(workspaceId ?? "none", {
      ...filters,
      limit,
    }),
    queryFn: ({ pageParam }) =>
      api.listNotifications(workspaceId!, {
        ...filters,
        limit,
        cursor: pageParam,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) =>
      lastPage.page_info.has_more
        ? (lastPage.page_info.next_cursor ?? undefined)
        : undefined,
    enabled: Boolean(workspaceId),
  });
}

export function useUnreadNotificationCount(workspaceId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.workspaces.notifications(workspaceId ?? "none", {
      unread_only: true,
      limit: 1,
    }),
    queryFn: () =>
      api.listNotifications(workspaceId!, { unread_only: true, limit: 1 }),
    enabled: Boolean(workspaceId),
    staleTime: 30_000,
  });
}

export function useMarkNotification(workspaceId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      notificationId,
      read,
    }: {
      notificationId: string;
      read: boolean;
    }) => api.markNotification(workspaceId, notificationId, read),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: [...queryKeys.workspaces.detail(workspaceId), "notifications"],
      });
    },
  });
}

export function useRepositories(
  workspaceId: string | undefined,
  projectId: string | undefined,
) {
  return useQuery({
    queryKey: queryKeys.repositories.list(
      workspaceId ?? "none",
      projectId ?? "none",
    ),
    queryFn: () => api.listProjectRepositories(workspaceId!, projectId!),
    enabled: Boolean(workspaceId && projectId),
  });
}

export function useTriageConfiguration(
  workspaceId: string | undefined,
  projectId: string | undefined,
) {
  return useQuery({
    queryKey: queryKeys.triage.configuration(
      workspaceId ?? "none",
      projectId ?? "none",
    ),
    queryFn: () => api.getTriageConfiguration(workspaceId!, projectId!),
    enabled: Boolean(workspaceId && projectId),
  });
}

export function useTriageTemplates(
  workspaceId: string | undefined,
  projectId: string | undefined,
) {
  return useQuery({
    queryKey: queryKeys.triage.templates(
      workspaceId ?? "none",
      projectId ?? "none",
      { limit: 100 },
    ),
    queryFn: () =>
      api.listTriageTemplates(workspaceId!, projectId!, { limit: 100 }),
    enabled: Boolean(workspaceId && projectId),
  });
}

export function useAuthSessions() {
  return useQuery({
    queryKey: queryKeys.authSessions,
    queryFn: () => api.listAuthSessions(),
  });
}

export function useRevokeAuthSession() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (sessionId: string) => api.revokeAuthSession(sessionId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.authSessions });
    },
  });
}
