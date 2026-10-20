import { KanbanSquare, RefreshCw } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import {
  Badge,
  Button,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  PageHeader,
  PageLayout,
  Skeleton,
  Switch,
} from "@eventflow/ui";
import { QueryErrorState } from "../components/query-state";
import { formatRelativeTime, pluralize } from "../lib/format";
import { useBoards } from "../lib/queries";
import { useDocumentTitle } from "../lib/use-document-title";
import { useWorkspace } from "../lib/workspace";

export function BoardsPage() {
  const { workspace, workspaceId, project, projectId, projects } = useWorkspace();
  const [includeArchived, setIncludeArchived] = useState(false);
  const boards = useBoards(
    workspaceId ?? undefined,
    projectId,
    includeArchived,
  );
  useDocumentTitle("Boards");

  const projectsById = new Map(
    projects.map((item) => [item.project_id, item]),
  );

  if (!workspace) return null;

  return (
    <PageLayout className="space-y-5">
      <PageHeader
        title="Boards"
        description={
          project
            ? `Boards for ${project.name}. Change the project context in the sidebar to view another project.`
            : "Boards across every project in this workspace."
        }
        actions={
          <Button variant="outline" onClick={() => void boards.refetch()}>
            <RefreshCw className="size-4" aria-hidden="true" />
            Refresh
          </Button>
        }
      />

      <div className="flex items-center gap-3 rounded-lg border border-border bg-surface px-4 py-3 shadow-sm">
        <Switch
          id="include-archived-boards"
          checked={includeArchived}
          onCheckedChange={setIncludeArchived}
          label="Include archived boards"
          description="Include archived boards in this project context."
        />
      </div>

      {boards.isError ? (
        <QueryErrorState
          error={boards.error}
          onRetry={() => void boards.refetch()}
        />
      ) : boards.isPending ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <Skeleton className="h-40" />
          <Skeleton className="h-40" />
          <Skeleton className="h-40" />
        </div>
      ) : (boards.data ?? []).length === 0 ? (
        <EmptyState
          icon={KanbanSquare}
          title="No boards in this context"
          description={
            includeArchived
              ? "No active or archived boards match the current project context."
              : "No active boards match the current project context. Try including archived boards or switching projects."
          }
          action={
            !includeArchived ? (
              <Button
                variant="outline"
                onClick={() => setIncludeArchived(true)}
              >
                Include archived boards
              </Button>
            ) : null
          }
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {(boards.data ?? []).map((board) => (
            <Link
              key={board.board_id}
              to={`/boards/${board.board_id}`}
              className="group block rounded-lg border border-border bg-surface shadow-sm transition-colors hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <CardHeader className="flex-row items-start justify-between space-y-0">
                <div>
                  <CardTitle className="group-hover:text-primary">
                    {board.name}
                  </CardTitle>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {projectsById.get(board.project_id)?.name ??
                      "Unknown project"}
                  </p>
                </div>
                {board.archived_at ? <Badge tone="neutral">Archived</Badge> : null}
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-1.5">
                  <span className="rounded-full bg-surface-muted px-2 py-0.5 text-xs text-muted-foreground">
                    {pluralize(board.columns.length, "column")}
                  </span>
                </div>
                <p className="mt-3 text-xs text-muted-foreground">
                  {pluralize(board.columns.length, "column")} · Updated{" "}
                  {formatRelativeTime(board.updated_at)}
                </p>
              </CardContent>
            </Link>
          ))}
        </div>
      )}
    </PageLayout>
  );
}
