import { ListChecks, RefreshCw, SlidersHorizontal } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import {
  Button,
  EmptyState,
  PageHeader,
  PageLayout,
  PriorityBadge,
  Select,
  Skeleton,
  StatusBadge,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@eventflow/ui";
import { QueryErrorState } from "../components/query-state";
import {
  CATEGORIES,
  PRIORITIES,
  WORK_ITEM_STATUSES,
  enumParam,
  withParam,
  withoutParams,
} from "../lib/filters";
import { formatRelativeTime, humanize, pluralize } from "../lib/format";
import { useWorkItems } from "../lib/queries";
import { useDocumentTitle } from "../lib/use-document-title";
import { useWorkspace } from "../lib/workspace";

export function WorkItemsPage() {
  const { workspace, workspaceId, projects, project } = useWorkspace();
  const [searchParams, setSearchParams] = useSearchParams();
  useDocumentTitle("Work items");

  const status = enumParam(searchParams, "status", WORK_ITEM_STATUSES);
  const category = enumParam(searchParams, "category", CATEGORIES);
  const priority = enumParam(searchParams, "priority", PRIORITIES);
  const workItems = useWorkItems(workspaceId ?? undefined, {
    status,
    category,
    priority,
    sort: "-updated_at",
  });
  const items = workItems.data?.pages.flatMap((page) => page.items) ?? [];
  const hasFilters = Boolean(status || category || priority);
  const projectsById = new Map(
    projects.map((item) => [item.project_id, item]),
  );

  function setFilter(key: string, value: string) {
    setSearchParams(withParam(searchParams, key, value), { replace: true });
  }

  function clearFilters() {
    setSearchParams(
      withoutParams(searchParams, ["status", "category", "priority"]),
      { replace: true },
    );
  }

  if (!workspace) return null;

  return (
    <PageLayout className="space-y-5">
      <PageHeader
        title="Work items"
        description="Delivery work across the workspace. The current API does not expose a project filter for work items, so this list always spans the workspace."
        actions={
          <Button variant="outline" onClick={() => void workItems.refetch()}>
            <RefreshCw className="size-4" aria-hidden="true" />
            Refresh
          </Button>
        }
      />

      {project ? (
        <p className="rounded-md border border-border bg-surface-muted px-3 py-2 text-xs text-muted-foreground">
          Active project: <strong>{project.name}</strong>. Project context applies
          to boards and project settings; work items remain workspace-wide.
        </p>
      ) : null}

      <div className="flex flex-col gap-3 rounded-lg border border-border bg-surface p-4 shadow-sm lg:flex-row lg:items-end">
        <div className="flex flex-1 flex-wrap gap-3">
          <div className="min-w-40 flex-1">
            <label
              htmlFor="work-item-status"
              className="mb-1.5 block text-xs font-medium text-foreground"
            >
              Status
            </label>
            <Select
              id="work-item-status"
              value={status ?? ""}
              onChange={(event) => setFilter("status", event.target.value)}
            >
              <option value="">All statuses</option>
              {WORK_ITEM_STATUSES.map((value) => (
                <option key={value} value={value}>
                  {humanize(value)}
                </option>
              ))}
            </Select>
          </div>
          <div className="min-w-40 flex-1">
            <label
              htmlFor="work-item-category"
              className="mb-1.5 block text-xs font-medium text-foreground"
            >
              Category
            </label>
            <Select
              id="work-item-category"
              value={category ?? ""}
              onChange={(event) => setFilter("category", event.target.value)}
            >
              <option value="">All categories</option>
              {CATEGORIES.map((value) => (
                <option key={value} value={value}>
                  {humanize(value)}
                </option>
              ))}
            </Select>
          </div>
          <div className="min-w-40 flex-1">
            <label
              htmlFor="work-item-priority"
              className="mb-1.5 block text-xs font-medium text-foreground"
            >
              Priority
            </label>
            <Select
              id="work-item-priority"
              value={priority ?? ""}
              onChange={(event) => setFilter("priority", event.target.value)}
            >
              <option value="">All priorities</option>
              {PRIORITIES.map((value) => (
                <option key={value} value={value}>
                  {humanize(value)}
                </option>
              ))}
            </Select>
          </div>
        </div>
        {hasFilters ? (
          <Button variant="ghost" onClick={clearFilters}>
            <SlidersHorizontal className="size-4" aria-hidden="true" />
            Clear filters
          </Button>
        ) : null}
      </div>

      <p className="text-sm text-muted-foreground" aria-live="polite">
        {workItems.isPending
          ? "Loading work items..."
          : `${pluralize(items.length, "work item")} loaded${workItems.hasNextPage ? " so far" : ""}.`}
      </p>

      {workItems.isError ? (
        <QueryErrorState
          error={workItems.error}
          onRetry={() => void workItems.refetch()}
        />
      ) : workItems.isPending ? (
        <div className="space-y-3">
          <Skeleton className="h-14" />
          <Skeleton className="h-14" />
          <Skeleton className="h-14" />
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          icon={ListChecks}
          title={hasFilters ? "No matching work items" : "No work items yet"}
          description={
            hasFilters
              ? "Try removing one or more filters to broaden the results."
              : "Approved proposals become work items and will appear here."
          }
          action={
            hasFilters ? (
              <Button variant="outline" onClick={clearFilters}>
                Clear filters
              </Button>
            ) : null
          }
        />
      ) : (
        <>
          <div className="hidden md:block">
            <TableContainer>
              <Table>
                <caption className="sr-only">
                  Work items in {workspace.name}
                </caption>
                <TableHead>
                  <TableRow>
                    <TableHeaderCell>Work item</TableHeaderCell>
                    <TableHeaderCell>Project</TableHeaderCell>
                    <TableHeaderCell>Status</TableHeaderCell>
                    <TableHeaderCell>Priority</TableHeaderCell>
                    <TableHeaderCell>Category</TableHeaderCell>
                    <TableHeaderCell>Updated</TableHeaderCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {items.map((workItem) => (
                    <TableRow key={workItem.work_item_id}>
                      <TableCell className="max-w-md">
                        <Link
                          to={`/work-items/${workItem.work_item_id}`}
                          className="line-clamp-1 font-medium text-foreground underline-offset-4 hover:text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        >
                          {workItem.title}
                        </Link>
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {projectsById.get(workItem.project_id)?.name ??
                          "Unknown project"}
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={workItem.status} />
                      </TableCell>
                      <TableCell>
                        <PriorityBadge priority={workItem.priority} />
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {humanize(workItem.category)}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                        {formatRelativeTime(workItem.updated_at)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </div>

          <ul className="space-y-3 md:hidden">
            {items.map((workItem) => (
              <li key={workItem.work_item_id}>
                <Link
                  to={`/work-items/${workItem.work_item_id}`}
                  className="block rounded-lg border border-border bg-surface p-4 shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <div className="flex items-start justify-between gap-3">
                    <p className="text-sm font-medium text-foreground">
                      {workItem.title}
                    </p>
                    <StatusBadge status={workItem.status} />
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span>
                      {projectsById.get(workItem.project_id)?.name ??
                        "Unknown project"}
                    </span>
                    <PriorityBadge priority={workItem.priority} />
                    <span>{formatRelativeTime(workItem.updated_at)}</span>
                  </div>
                </Link>
              </li>
            ))}
          </ul>

          {workItems.hasNextPage ? (
            <div className="flex justify-center">
              <Button
                variant="outline"
                loading={workItems.isFetchingNextPage}
                onClick={() => void workItems.fetchNextPage()}
              >
                Load more work items
              </Button>
            </div>
          ) : null}
        </>
      )}
    </PageLayout>
  );
}
