import { ArrowLeft, KanbanSquare, RefreshCw } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import {
  Badge,
  Breadcrumb,
  Button,
  EmptyState,
  PageHeader,
  PageLayout,
  PriorityBadge,
  Skeleton,
  StatusBadge,
} from "@eventflow/ui";
import { QueryErrorState } from "../components/query-state";
import { formatDateTime, formatRelativeTime, humanize } from "../lib/format";
import {
  useBoard,
  useBoardCards,
  useBoardColumns,
} from "../lib/queries";
import { useDocumentTitle } from "../lib/use-document-title";
import { useWorkspace } from "../lib/workspace";

export function BoardDetailPage() {
  const { boardId } = useParams();
  const { workspace, workspaceId, projects } = useWorkspace();
  const boardQuery = useBoard(workspaceId ?? undefined, boardId);
  const columnsQuery = useBoardColumns(workspaceId ?? undefined, boardId);
  const cardsQuery = useBoardCards(workspaceId ?? undefined, boardId);
  useDocumentTitle(boardQuery.data?.name ?? "Board");

  if (!workspace) return null;

  if (boardQuery.isPending) {
    return (
      <PageLayout className="space-y-4">
        <Skeleton className="h-4 w-72" />
        <Skeleton className="h-9 w-1/3" />
        <div className="flex gap-4">
          <Skeleton className="h-96 w-72" />
          <Skeleton className="h-96 w-72" />
          <Skeleton className="h-96 w-72" />
        </div>
      </PageLayout>
    );
  }

  if (boardQuery.isError) {
    return (
      <PageLayout>
        <QueryErrorState
          error={boardQuery.error}
          onRetry={() => void boardQuery.refetch()}
        />
        <div className="mt-4 text-center">
          <Link
            to="/boards"
            className="text-sm font-medium text-primary underline-offset-4 hover:underline"
          >
            Back to boards
          </Link>
        </div>
      </PageLayout>
    );
  }

  const board = boardQuery.data;
  const project = projects.find(
    (candidate) => candidate.project_id === board.project_id,
  );
  const columns = columnsQuery.data ?? [];
  const cards = cardsQuery.data?.pages.flatMap((page) => page.items) ?? [];
  const cardsByColumn = new Map<string, typeof cards>();
  for (const card of cards) {
    const existing = cardsByColumn.get(card.column_id) ?? [];
    existing.push(card);
    cardsByColumn.set(card.column_id, existing);
  }
  const cardsAreComplete = !cardsQuery.hasNextPage;

  return (
    <PageLayout className="space-y-5">
      <Breadcrumb
        items={[
          { label: workspace.name, href: "/" },
          { label: "Boards", href: "/boards" },
          { label: board.name },
        ]}
      />
      <PageHeader
        eyebrow={project ? `${project.key} · ${project.name}` : "Delivery board"}
        title={board.name}
        description={`Version ${board.version} · Updated ${formatDateTime(board.updated_at)}.`}
        actions={
          <>
            <Button
              variant="outline"
              onClick={() => {
                void boardQuery.refetch();
                void columnsQuery.refetch();
                void cardsQuery.refetch();
              }}
            >
              <RefreshCw className="size-4" aria-hidden="true" />
              Refresh
            </Button>
            <Link
              to="/boards"
              className="inline-flex h-10 items-center gap-2 rounded-md px-3 text-sm font-medium text-muted-foreground transition-colors hover:bg-surface-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <ArrowLeft className="size-4" aria-hidden="true" />
              Back
            </Link>
          </>
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="info">{columns.length} columns</Badge>
        {board.archived_at ? <Badge tone="neutral">Archived</Badge> : null}
        <span className="text-xs text-muted-foreground">
          Delivery board is read-only in this release.
        </span>
      </div>

      {columnsQuery.isError ? (
        <QueryErrorState
          error={columnsQuery.error}
          onRetry={() => void columnsQuery.refetch()}
        />
      ) : cardsQuery.isError ? (
        <QueryErrorState
          error={cardsQuery.error}
          onRetry={() => void cardsQuery.refetch()}
        />
      ) : columnsQuery.isPending ? (
        <div className="flex gap-4 overflow-x-auto pb-4">
          <Skeleton className="h-96 w-72 shrink-0" />
          <Skeleton className="h-96 w-72 shrink-0" />
          <Skeleton className="h-96 w-72 shrink-0" />
        </div>
      ) : columns.length === 0 ? (
        <EmptyState
          icon={KanbanSquare}
          title="This board has no columns"
          description="Columns define the delivery flow. Configure them in the board administration workflow."
        />
      ) : (
        <>
          <div
            className="flex gap-4 overflow-x-auto pb-4"
            role="region"
            aria-label={`${board.name} columns`}
            tabIndex={0}
          >
            {columns.map((column) => {
              const columnCards = cardsByColumn.get(column.column_id) ?? [];
                const overWipLimit =
                cardsAreComplete &&
                column.wip_limit !== null &&
                column.wip_limit !== undefined &&
                columnCards.length > column.wip_limit;
              return (
                <section
                  key={column.column_id}
                  aria-labelledby={`column-${column.column_id}`}
                  className="flex w-72 shrink-0 flex-col rounded-lg border border-border bg-surface-muted/60"
                >
                  <header className="border-b border-border p-3">
                    <div className="flex items-center justify-between gap-2">
                      <h2
                        id={`column-${column.column_id}`}
                        className="text-sm font-semibold text-foreground"
                      >
                        {column.name}
                      </h2>
                      <Badge tone={overWipLimit ? "destructive" : "neutral"}>
                        {cardsAreComplete
                          ? `${columnCards.length}${column.wip_limit ? ` / ${column.wip_limit}` : ""}`
                          : `${columnCards.length}+`}
                      </Badge>
                    </div>
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <StatusBadge status={column.mapped_status} />
                      <span className="text-xs text-muted-foreground">
                        Position {column.position}
                      </span>
                    </div>
                    {overWipLimit ? (
                      <p className="mt-2 text-xs font-medium text-destructive">
                        Work-in-progress limit exceeded.
                      </p>
                    ) : null}
                  </header>
                  <div className="flex min-h-32 flex-1 flex-col gap-2 p-2">
                    {cardsQuery.isPending ? (
                      <>
                        <Skeleton className="h-24" />
                        <Skeleton className="h-24" />
                      </>
                    ) : columnCards.length === 0 ? (
                      <p className="px-2 py-6 text-center text-xs text-muted-foreground">
                        No cards in this column.
                      </p>
                    ) : (
                      columnCards.map((card) => (
                        <Link
                          key={card.card_id}
                          to={`/work-items/${card.work_item_id}`}
                          className="block rounded-md border border-border bg-surface p-3 shadow-sm transition-colors hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        >
                          <p className="text-sm font-medium text-foreground">
                            {card.title}
                          </p>
                          <div className="mt-2 flex flex-wrap items-center gap-1.5">
                            <PriorityBadge priority={card.priority} />
                            <Badge tone="neutral">
                              {humanize(card.category)}
                            </Badge>
                          </div>
                          <p className="mt-2 text-[0.68rem] text-muted-foreground">
                            Updated {formatRelativeTime(card.updated_at)}
                          </p>
                        </Link>
                      ))
                    )}
                  </div>
                </section>
              );
            })}
          </div>

          {cardsQuery.hasNextPage ? (
            <div className="flex flex-col items-center gap-2">
              <p className="text-xs text-muted-foreground">
                Some columns may contain more cards than shown.
              </p>
              <Button
                variant="outline"
                loading={cardsQuery.isFetchingNextPage}
                onClick={() => void cardsQuery.fetchNextPage()}
              >
                Load more cards
              </Button>
            </div>
          ) : null}
        </>
      )}
    </PageLayout>
  );
}
