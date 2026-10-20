import {
  ArrowRight,
  FolderKanban,
  Inbox,
  KanbanSquare,
  ListChecks,
  RefreshCw,
} from "lucide-react";
import { Link } from "react-router-dom";
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  EmptyState,
  PageHeader,
  PageLayout,
  PriorityBadge,
  Skeleton,
  StatusBadge,
} from "@eventflow/ui";
import { useDocumentTitle } from "../lib/use-document-title";
import { useConsultations, useBoards, useWorkItems } from "../lib/queries";
import { useWorkspace } from "../lib/workspace";
import { formatRelativeTime, pluralize } from "../lib/format";
import { QueryErrorState } from "../components/query-state";

function DashboardSkeleton() {
  return (
    <div className="space-y-6" aria-busy="true">
      <Skeleton className="h-10 w-72" />
      <div className="grid gap-4 sm:grid-cols-3">
        <Skeleton className="h-28" />
        <Skeleton className="h-28" />
        <Skeleton className="h-28" />
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Skeleton className="h-80" />
        <Skeleton className="h-80" />
      </div>
    </div>
  );
}

export function DashboardPage() {
  const { workspace, workspaceId, project, projects, projectId, refreshWorkspaces } =
    useWorkspace();
  useDocumentTitle("Dashboard");

  const consultations = useConsultations(
    workspaceId ?? undefined,
    { sort: "-created_at" },
    5,
  );
  const workItems = useWorkItems(
    workspaceId ?? undefined,
    { sort: "-updated_at" },
    5,
  );
  const boards = useBoards(workspaceId ?? undefined, projectId);

  const projectsById = new Map(
    projects.map((item) => [item.project_id, item]),
  );
  const recentConsultations =
    consultations.data?.pages.flatMap((page) => page.items) ?? [];
  const recentWorkItems =
    workItems.data?.pages.flatMap((page) => page.items) ?? [];
  const boardItems = boards.data ?? [];

  if (!workspace) return null;

  const isInitialLoading =
    consultations.isPending && workItems.isPending && boards.isPending;

  return (
    <PageLayout className="space-y-6">
      <PageHeader
        eyebrow={project ? `${project.key} · ${project.name}` : workspace.name}
        title={project ? `${project.name} overview` : "Workspace overview"}
        description={
          project
            ? "Delivery signals for the selected project context. Consultations and work items remain workspace-wide because the current API does not expose project filters for them."
            : "A focused view of incoming requests, active delivery work, and boards across this workspace."
        }
        actions={
          <Button
            variant="outline"
            onClick={() => {
              refreshWorkspaces();
              void consultations.refetch();
              void workItems.refetch();
              void boards.refetch();
            }}
          >
            <RefreshCw className="size-4" aria-hidden="true" />
            Refresh
          </Button>
        }
      />

      {isInitialLoading ? (
        <DashboardSkeleton />
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <Card>
              <CardContent className="flex items-start gap-3 p-5">
                <span className="flex size-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <FolderKanban className="size-5" aria-hidden="true" />
                </span>
                <div className="min-w-0">
                  <p className="text-2xl font-semibold text-foreground">
                    {projects.length}
                  </p>
                  <p className="text-sm font-medium text-foreground">Projects</p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    Available in this workspace
                  </p>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="flex items-start gap-3 p-5">
                <span className="flex size-10 items-center justify-center rounded-lg bg-info/10 text-info">
                  <KanbanSquare className="size-5" aria-hidden="true" />
                </span>
                <div className="min-w-0">
                  <p className="text-2xl font-semibold text-foreground">
                    {boards.isPending ? "–" : boardItems.length}
                  </p>
                  <p className="text-sm font-medium text-foreground">Boards</p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {project ? `In ${project.name}` : "Across all projects"}
                  </p>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="flex items-start gap-3 p-5">
                <span className="flex size-10 items-center justify-center rounded-lg bg-accent text-accent-foreground">
                  <Inbox className="size-5" aria-hidden="true" />
                </span>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-foreground">
                    Selected context
                  </p>
                  <p className="mt-1 truncate text-lg font-semibold text-foreground">
                    {project?.name ?? "All projects"}
                  </p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    Change it from the sidebar
                  </p>
                </div>
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-4 xl:grid-cols-2">
            <Card>
              <CardHeader className="flex-row items-start justify-between gap-4 space-y-0">
                <div>
                  <CardTitle>Recent consultations</CardTitle>
                  <CardDescription>
                    Latest incoming requests in the workspace.
                  </CardDescription>
                </div>
                <Link
                  to="/consultations"
                  className="inline-flex items-center gap-1 rounded-sm text-sm font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  View all
                  <ArrowRight className="size-3.5" aria-hidden="true" />
                </Link>
              </CardHeader>
              <CardContent>
                {consultations.isError ? (
                  <QueryErrorState
                    error={consultations.error}
                    onRetry={() => void consultations.refetch()}
                    className="min-h-48 border-0"
                  />
                ) : consultations.isPending ? (
                  <div className="space-y-3">
                    <Skeleton className="h-14" />
                    <Skeleton className="h-14" />
                    <Skeleton className="h-14" />
                  </div>
                ) : recentConsultations.length === 0 ? (
                  <EmptyState
                    icon={Inbox}
                    title="No consultations yet"
                    description="Incoming requests will appear here once they are created."
                    className="min-h-48 border-0"
                  />
                ) : (
                  <ul className="divide-y divide-border">
                    {recentConsultations.map((consultation) => {
                      const consultationProject = projectsById.get(
                        consultation.project_id,
                      );
                      return (
                        <li key={consultation.consultation_id}>
                          <Link
                            to={`/consultations/${consultation.consultation_id}`}
                            className="block rounded-md px-2 py-3 transition-colors hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                          >
                            <div className="flex items-start justify-between gap-3">
                              <p className="line-clamp-1 text-sm font-medium text-foreground">
                                {consultation.title}
                              </p>
                              <StatusBadge status={consultation.status} />
                            </div>
                            <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                              <span>
                                {consultationProject?.name ??
                                  "Unknown project"}
                              </span>
                              <span aria-hidden="true">·</span>
                              <PriorityBadge priority={consultation.priority} />
                              <span aria-hidden="true">·</span>
                              <span>
                                {formatRelativeTime(consultation.created_at)}
                              </span>
                            </div>
                          </Link>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex-row items-start justify-between gap-4 space-y-0">
                <div>
                  <CardTitle>Latest work items</CardTitle>
                  <CardDescription>
                    Recently updated delivery work across the workspace.
                  </CardDescription>
                </div>
                <Link
                  to="/work-items"
                  className="inline-flex items-center gap-1 rounded-sm text-sm font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  View all
                  <ArrowRight className="size-3.5" aria-hidden="true" />
                </Link>
              </CardHeader>
              <CardContent>
                {workItems.isError ? (
                  <QueryErrorState
                    error={workItems.error}
                    onRetry={() => void workItems.refetch()}
                    className="min-h-48 border-0"
                  />
                ) : workItems.isPending ? (
                  <div className="space-y-3">
                    <Skeleton className="h-14" />
                    <Skeleton className="h-14" />
                    <Skeleton className="h-14" />
                  </div>
                ) : recentWorkItems.length === 0 ? (
                  <EmptyState
                    icon={ListChecks}
                    title="No work items yet"
                    description="Approved proposals become work items, which will appear here."
                    className="min-h-48 border-0"
                  />
                ) : (
                  <ul className="divide-y divide-border">
                    {recentWorkItems.map((workItem) => {
                      const itemProject = projectsById.get(workItem.project_id);
                      return (
                        <li key={workItem.work_item_id}>
                          <Link
                            to={`/work-items/${workItem.work_item_id}`}
                            className="block rounded-md px-2 py-3 transition-colors hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                          >
                            <div className="flex items-start justify-between gap-3">
                              <p className="line-clamp-1 text-sm font-medium text-foreground">
                                {workItem.title}
                              </p>
                              <StatusBadge status={workItem.status} />
                            </div>
                            <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                              <span>{itemProject?.name ?? "Unknown project"}</span>
                              <span aria-hidden="true">·</span>
                              <PriorityBadge priority={workItem.priority} />
                              <span aria-hidden="true">·</span>
                              <span>
                                {formatRelativeTime(workItem.updated_at)}
                              </span>
                            </div>
                          </Link>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </CardContent>
            </Card>
          </div>

          <section aria-labelledby="boards-heading" className="space-y-3">
            <div className="flex flex-wrap items-end justify-between gap-2">
              <div>
                <h2
                  id="boards-heading"
                  className="text-base font-semibold text-foreground"
                >
                  Boards
                </h2>
                <p className="text-sm text-muted-foreground">
                  {project
                    ? `Boards for ${project.name}.`
                    : "Boards across all projects in this workspace."}
                </p>
              </div>
              <Link
                to="/boards"
                className="inline-flex items-center gap-1 rounded-sm text-sm font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                All boards
                <ArrowRight className="size-3.5" aria-hidden="true" />
              </Link>
            </div>
            {boards.isError ? (
              <QueryErrorState
                error={boards.error}
                onRetry={() => void boards.refetch()}
                className="min-h-40"
              />
            ) : boards.isPending ? (
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                <Skeleton className="h-28" />
                <Skeleton className="h-28" />
                <Skeleton className="h-28" />
              </div>
            ) : boardItems.length === 0 ? (
              <EmptyState
                icon={KanbanSquare}
                title="No boards in this context"
                description={
                  project
                    ? "This project has no active boards. Switch to another project or view all projects."
                    : "Create boards in a project to visualise delivery flow."
                }
                action={
                  project ? (
                    <Link
                      to="/boards"
                      className="inline-flex h-10 items-center justify-center rounded-md border border-border-strong bg-surface px-4 text-sm font-medium text-foreground transition-colors hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      Browse all boards
                    </Link>
                  ) : null
                }
              />
            ) : (
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                {boardItems.slice(0, 6).map((board) => {
                  const boardProject = projectsById.get(board.project_id);
                  return (
                    <Link
                      key={board.board_id}
                      to={`/boards/${board.board_id}`}
                      className="group rounded-lg border border-border bg-surface p-4 shadow-sm transition-colors hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <h3 className="text-sm font-semibold text-foreground group-hover:text-primary">
                          {board.name}
                        </h3>
                        <KanbanSquare
                          className="size-4 shrink-0 text-muted-foreground"
                          aria-hidden="true"
                        />
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {boardProject?.name ?? "Unknown project"}
                      </p>
                      <p className="mt-3 text-xs text-muted-foreground">
                        {pluralize(board.columns.length, "column")} · Updated{" "}
                        {formatRelativeTime(board.updated_at)}
                      </p>
                    </Link>
                  );
                })}
              </div>
            )}
          </section>
        </>
      )}
    </PageLayout>
  );
}
