import { FolderKanban, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";
import {
  Badge,
  Button,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  EmptyState,
  PageHeader,
  PageLayout,
  Skeleton,
} from "@eventflow/ui";
import { QueryErrorState } from "../components/query-state";
import { formatRelativeTime, pluralize } from "../lib/format";
import { useDocumentTitle } from "../lib/use-document-title";
import { useWorkspace } from "../lib/workspace";

export function ProjectsPage() {
  const {
    workspace,
    projects,
    projectId,
    selectProject,
    isProjectsLoading,
    projectsError,
    refreshWorkspaces,
  } = useWorkspace();
  useDocumentTitle("Projects");

  if (!workspace) return null;

  return (
    <PageLayout className="space-y-5">
      <PageHeader
        title="Projects"
        description="Projects organise consultations, proposals, boards, repositories, and triage configuration within the workspace."
        actions={
          <Button variant="outline" onClick={refreshWorkspaces}>
            <RefreshCw className="size-4" aria-hidden="true" />
            Refresh
          </Button>
        }
      />

      <p className="text-sm text-muted-foreground" aria-live="polite">
        {isProjectsLoading
          ? "Loading projects..."
          : `${pluralize(projects.length, "project")} in ${workspace.name}.`}
      </p>

      {projectsError ? (
        <QueryErrorState
          error={projectsError}
          onRetry={refreshWorkspaces}
        />
      ) : isProjectsLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <Skeleton className="h-44" />
          <Skeleton className="h-44" />
          <Skeleton className="h-44" />
        </div>
      ) : projects.length === 0 ? (
        <EmptyState
          icon={FolderKanban}
          title="No projects yet"
          description="Create a project in the work management API to organise boards, repositories, and triage configuration."
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {projects.map((project) => {
            const isSelected = project.project_id === projectId;
            return (
              <Link
                key={project.project_id}
                to={`/projects/${project.project_id}`}
                onClick={() => selectProject(project.project_id)}
                className="group block rounded-lg border border-border bg-surface shadow-sm transition-colors hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <CardHeader className="flex-row items-start justify-between space-y-0">
                  <div className="min-w-0">
                    <p className="font-mono text-xs font-semibold uppercase tracking-wide text-primary">
                      {project.key}
                    </p>
                    <CardTitle className="mt-1 truncate group-hover:text-primary">
                      {project.name}
                    </CardTitle>
                  </div>
                  {isSelected ? <Badge tone="accent">Active</Badge> : null}
                </CardHeader>
                <CardContent>
                  <CardDescription className="line-clamp-2">
                    {project.description?.trim() || "No description provided."}
                  </CardDescription>
                  <p className="mt-3 text-xs text-muted-foreground">
                    Updated {formatRelativeTime(project.updated_at)}
                  </p>
                </CardContent>
              </Link>
            );
          })}
        </div>
      )}
    </PageLayout>
  );
}
