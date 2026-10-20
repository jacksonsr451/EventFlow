import { Inbox, RefreshCw, SlidersHorizontal } from "lucide-react";
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
  CONSULTATION_STATUSES,
  PRIORITIES,
  enumParam,
  withParam,
  withoutParams,
} from "../lib/filters";
import { formatRelativeTime, humanize, pluralize } from "../lib/format";
import { useConsultations } from "../lib/queries";
import { useDocumentTitle } from "../lib/use-document-title";
import { useWorkspace } from "../lib/workspace";

export function ConsultationsPage() {
  const { workspace, workspaceId, projects } = useWorkspace();
  const [searchParams, setSearchParams] = useSearchParams();
  useDocumentTitle("Consultations");

  const status = enumParam(searchParams, "status", CONSULTATION_STATUSES);
  const category = enumParam(searchParams, "category", CATEGORIES);
  const priority = enumParam(searchParams, "priority", PRIORITIES);
  const filters = {
    status,
    category,
    priority,
    sort: "-created_at",
  };
  const consultations = useConsultations(workspaceId ?? undefined, filters);
  const items = consultations.data?.pages.flatMap((page) => page.items) ?? [];
  const hasFilters = Boolean(status || category || priority);
  const projectsById = new Map(
    projects.map((project) => [project.project_id, project]),
  );

  function setFilter(key: string, value: string) {
    setSearchParams(withParam(searchParams, key, value), { replace: true });
  }

  if (!workspace) return null;

  return (
    <PageLayout className="space-y-5">
      <PageHeader
        title="Consultations"
        description="Incoming requests across the workspace. The current API does not expose a project filter or free-text search for consultations."
        actions={
          <Button
            variant="outline"
            onClick={() => void consultations.refetch()}
          >
            <RefreshCw className="size-4" aria-hidden="true" />
            Refresh
          </Button>
        }
      />

      <div className="flex flex-col gap-3 rounded-lg border border-border bg-surface p-4 shadow-sm lg:flex-row lg:items-end">
        <div className="flex flex-1 flex-wrap gap-3">
          <div className="min-w-40 flex-1">
            <label
              htmlFor="consultation-status"
              className="mb-1.5 block text-xs font-medium text-foreground"
            >
              Status
            </label>
            <Select
              id="consultation-status"
              value={status ?? ""}
              onChange={(event) => setFilter("status", event.target.value)}
            >
              <option value="">All statuses</option>
              {CONSULTATION_STATUSES.map((value) => (
                <option key={value} value={value}>
                  {humanize(value)}
                </option>
              ))}
            </Select>
          </div>
          <div className="min-w-40 flex-1">
            <label
              htmlFor="consultation-category"
              className="mb-1.5 block text-xs font-medium text-foreground"
            >
              Category
            </label>
            <Select
              id="consultation-category"
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
              htmlFor="consultation-priority"
              className="mb-1.5 block text-xs font-medium text-foreground"
            >
              Priority
            </label>
            <Select
              id="consultation-priority"
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
          <Button
            variant="ghost"
            className="self-start lg:self-auto"
            onClick={() =>
              setSearchParams(
                withoutParams(searchParams, [
                  "status",
                  "category",
                  "priority",
                ]),
                { replace: true },
              )
            }
          >
            <SlidersHorizontal className="size-4" aria-hidden="true" />
            Clear filters
          </Button>
        ) : null}
      </div>

      <p className="text-sm text-muted-foreground" aria-live="polite">
        {consultations.isPending
          ? "Loading consultations..."
          : `${pluralize(items.length, "consultation")} loaded${consultations.hasNextPage ? " so far" : ""}.`}
      </p>

      {consultations.isError ? (
        <QueryErrorState
          error={consultations.error}
          onRetry={() => void consultations.refetch()}
        />
      ) : consultations.isPending ? (
        <div className="space-y-3">
          <Skeleton className="h-14" />
          <Skeleton className="h-14" />
          <Skeleton className="h-14" />
          <Skeleton className="h-14" />
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          icon={Inbox}
          title={hasFilters ? "No matching consultations" : "No consultations yet"}
          description={
            hasFilters
              ? "Try removing one or more filters to broaden the results."
              : "Incoming requests will appear here once they are created."
          }
          action={
            hasFilters ? (
              <Button
                variant="outline"
                onClick={() =>
                  setSearchParams(
                    withoutParams(searchParams, [
                      "status",
                      "category",
                      "priority",
                    ]),
                    { replace: true },
                  )
                }
              >
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
                  Consultations in {workspace.name}
                </caption>
                <TableHead>
                  <TableRow>
                    <TableHeaderCell>Consultation</TableHeaderCell>
                    <TableHeaderCell>Project</TableHeaderCell>
                    <TableHeaderCell>Status</TableHeaderCell>
                    <TableHeaderCell>Priority</TableHeaderCell>
                    <TableHeaderCell>Category</TableHeaderCell>
                    <TableHeaderCell>Updated</TableHeaderCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {items.map((consultation) => (
                    <TableRow key={consultation.consultation_id}>
                      <TableCell className="max-w-md">
                        <Link
                          to={`/consultations/${consultation.consultation_id}`}
                          className="line-clamp-1 font-medium text-foreground underline-offset-4 hover:text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        >
                          {consultation.title}
                        </Link>
                        <p className="mt-0.5 text-xs text-muted-foreground">
                          {pluralize(
                            (consultation.external_references ?? []).length,
                            "reference",
                          )}
                        </p>
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {projectsById.get(consultation.project_id)?.name ??
                          "Unknown project"}
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={consultation.status} />
                      </TableCell>
                      <TableCell>
                        <PriorityBadge priority={consultation.priority} />
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {humanize(consultation.category)}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                        {formatRelativeTime(consultation.updated_at)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </div>

          <ul className="space-y-3 md:hidden">
            {items.map((consultation) => (
              <li key={consultation.consultation_id}>
                <Link
                  to={`/consultations/${consultation.consultation_id}`}
                  className="block rounded-lg border border-border bg-surface p-4 shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <div className="flex items-start justify-between gap-3">
                    <p className="text-sm font-medium text-foreground">
                      {consultation.title}
                    </p>
                    <StatusBadge status={consultation.status} />
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span>
                      {projectsById.get(consultation.project_id)?.name ??
                        "Unknown project"}
                    </span>
                    <PriorityBadge priority={consultation.priority} />
                    <span>{humanize(consultation.category)}</span>
                    <span>{formatRelativeTime(consultation.updated_at)}</span>
                  </div>
                </Link>
              </li>
            ))}
          </ul>

          {consultations.hasNextPage ? (
            <div className="flex justify-center">
              <Button
                variant="outline"
                loading={consultations.isFetchingNextPage}
                onClick={() => void consultations.fetchNextPage()}
              >
                {consultations.isFetchingNextPage
                  ? "Loading more..."
                  : "Load more consultations"}
              </Button>
            </div>
          ) : null}
        </>
      )}
    </PageLayout>
  );
}
