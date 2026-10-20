import type { Project, Workspace } from "@eventflow/domain";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useProjectList, useWorkspaceList } from "./queries";

const WORKSPACE_STORAGE_KEY = "eventflow.workspace";
const PROJECT_STORAGE_PREFIX = "eventflow.project.";

function projectStorageKey(workspaceId: string): string {
  return `${PROJECT_STORAGE_PREFIX}${workspaceId}`;
}

function readStorage(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: string | null): void {
  try {
    if (value) {
      localStorage.setItem(key, value);
    } else {
      localStorage.removeItem(key);
    }
  } catch {
    // Context still works for the current session.
  }
}

interface WorkspaceContextValue {
  workspaces: Workspace[];
  workspace: Workspace | null;
  workspaceId: string | null;
  projects: Project[];
  project: Project | null;
  projectId: string | null;
  isWorkspacesLoading: boolean;
  isProjectsLoading: boolean;
  workspacesError: Error | null;
  projectsError: Error | null;
  selectWorkspace: (workspaceId: string) => void;
  selectProject: (projectId: string | null) => void;
  refreshWorkspaces: () => void;
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const workspaceQuery = useWorkspaceList();
  const workspaces = useMemo(
    () => workspaceQuery.data ?? [],
    [workspaceQuery.data],
  );
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string | null>(
    () => readStorage(WORKSPACE_STORAGE_KEY),
  );
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(
    null,
  );

  useEffect(() => {
    if (workspaceQuery.isPending) return;
    if (workspaces.length === 0) {
      if (selectedWorkspaceId !== null) setSelectedWorkspaceId(null);
      return;
    }
    const isValid = workspaces.some(
      (workspace) => workspace.workspace_id === selectedWorkspaceId,
    );
    if (!isValid) {
      setSelectedWorkspaceId(workspaces[0]?.workspace_id ?? null);
    }
  }, [workspaceQuery.isPending, workspaces, selectedWorkspaceId]);

  const workspace =
    workspaces.find(
      (candidate) => candidate.workspace_id === selectedWorkspaceId,
    ) ?? null;
  const workspaceId = workspace?.workspace_id ?? null;

  useEffect(() => {
    if (!workspaceId) {
      setSelectedProjectId(null);
      return;
    }
    setSelectedProjectId(readStorage(projectStorageKey(workspaceId)));
  }, [workspaceId]);

  const projectsQuery = useProjectList(workspaceId ?? undefined);
  const projects = useMemo(
    () => projectsQuery.data ?? [],
    [projectsQuery.data],
  );

  useEffect(() => {
    if (!workspaceId || projectsQuery.isPending) return;
    if (selectedProjectId === null) return;
    const isValid = projects.some(
      (candidate) => candidate.project_id === selectedProjectId,
    );
    if (!isValid) {
      setSelectedProjectId(null);
      writeStorage(projectStorageKey(workspaceId), null);
    }
  }, [projects, projectsQuery.isPending, selectedProjectId, workspaceId]);

  const project =
    projects.find(
      (candidate) => candidate.project_id === selectedProjectId,
    ) ?? null;

  const selectWorkspace = useCallback(
    (nextWorkspaceId: string) => {
      const next = workspaces.find(
        (candidate) => candidate.workspace_id === nextWorkspaceId,
      );
      if (!next) return;
      setSelectedWorkspaceId(next.workspace_id);
      writeStorage(WORKSPACE_STORAGE_KEY, next.workspace_id);
    },
    [workspaces],
  );

  const selectProject = useCallback(
    (nextProjectId: string | null) => {
      if (!workspaceId) return;
      if (nextProjectId !== null) {
        const next = projects.find(
          (candidate) => candidate.project_id === nextProjectId,
        );
        if (!next) return;
      }
      setSelectedProjectId(nextProjectId);
      writeStorage(projectStorageKey(workspaceId), nextProjectId);
    },
    [projects, workspaceId],
  );

  const refreshWorkspaces = useCallback(() => {
    void workspaceQuery.refetch();
    if (workspaceId) void projectsQuery.refetch();
  }, [projectsQuery, workspaceId, workspaceQuery]);

  const value = useMemo<WorkspaceContextValue>(
    () => ({
      workspaces,
      workspace,
      workspaceId,
      projects,
      project,
      projectId: project?.project_id ?? null,
      isWorkspacesLoading: workspaceQuery.isPending,
      isProjectsLoading: projectsQuery.isPending,
      workspacesError: workspaceQuery.error,
      projectsError: projectsQuery.error,
      selectWorkspace,
      selectProject,
      refreshWorkspaces,
    }),
    [
      workspaces,
      workspace,
      workspaceId,
      projects,
      project,
      workspaceQuery.isPending,
      workspaceQuery.error,
      projectsQuery.isPending,
      projectsQuery.error,
      selectWorkspace,
      selectProject,
      refreshWorkspaces,
    ],
  );

  return (
    <WorkspaceContext.Provider value={value}>
      {children}
    </WorkspaceContext.Provider>
  );
}

export function useWorkspace(): WorkspaceContextValue {
  const context = useContext(WorkspaceContext);
  if (!context) {
    throw new Error("useWorkspace must be used within a WorkspaceProvider");
  }
  return context;
}
