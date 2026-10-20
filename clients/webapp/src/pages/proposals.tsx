import { FileText, RefreshCw } from "lucide-react";
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
  PROPOSAL_STATUSES,
  enumParam,
  withParam,
} from "../lib/filters";
import {
  formatRelativeTime,
  humanize,
  pluralize,
} from "../lib/format";
import {
  useConsultation,
  useConsultationProposals,
  useConsultations,
} from "../lib/queries";
import { useDocumentTitle } from "../lib/use-document-title";
import { useWorkspace } from "../lib/workspace";

export function ProposalsPage() {
  const { workspace, workspaceId, projects, project } = useWorkspace();
  const [searchParams, setSearchParams] = useSearchParams();
  useDocumentTitle("Proposals");

  const selectedConsultationId = searchParams.get("consultation") ?? undefined;
  const status = enumParam(searchParams, "status", PROPOSAL_STATUSES);
  const consultations = useConsultations(
    workspaceId ?? undefined,
    { sort: "-created_at" },
    100,
  );
  const consultation = useConsultation(
    workspaceId ?? undefined,
    selectedConsultationId,
  );
  const proposals = useConsultationProposals(
    workspaceId ?? undefined,
    selectedConsultationId,
    { status, sort: "-updated_at" },
  );

  const consultationItems =
    consultations.data?.pages.flatMap((page) => page.items) ?? [];
  const proposalItems =
    proposals.data?.pages.flatMap((page) => page.items) ?? [];
  const projectsById = new Map(
    projects.map((item) => [item.project_id, item]),
  );

  function selectConsultation(value: string) {
    const next = withParam(searchParams, "consultation", value || null);
    setSearchParams(next, { replace: true });
  }

  function selectStatus(value: string) {
    setSearchParams(withParam(searchParams, "status", value), {
      replace: true,
    });
  }

  if (!workspace) return null;

  return (
    <PageLayout className="space-y-5">
      <PageHeader
        title="Proposals"
        description="Proposals are scoped to a consultation in the current API. Choose a consultation to review its proposals."
        actions={
          <Button
            variant="outline"
            onClick={() => {
              void consultations.refetch();
              if (selectedConsultationId) void proposals.refetch();
            }}
          >
            <RefreshCw className="size-4" aria-hidden="true" />
            Refresh
          </Button>
        }
      />

      {project ? (
        <p className="rounded-md border border-border bg-surface-muted px-3 py-2 text-xs text-muted-foreground">
          Active project: <strong>{project.name}</strong>. Proposal results are
          determined by the selected consultation; the project context does not
          filter consultations in this API.
        </p>
      ) : null}

      <div className="grid gap-3 rounded-lg border border-border bg-surface p-4 shadow-sm sm:grid-cols-2">
        <div>
          <label
            htmlFor="proposal-consultation"
            className="mb-1.5 block text-xs font-medium text-foreground"
          >
            Consultation
          </label>
          <Select
            id="proposal-consultation"
            value={selectedConsultationId ?? ""}
            disabled={consultations.isPending}
            onChange={(event) => selectConsultation(event.target.value)}
          >
            <option value="">Choose a consultation</option>
            {consultationItems.map((item) => (
              <option key={item.consultation_id} value={item.consultation_id}>
                {item.title} ·{" "}
                {projectsById.get(item.project_id)?.name ?? "Unknown project"}
              </option>
            ))}
          </Select>
          {consultations.hasNextPage ? (
            <p className="mt-1.5 text-xs text-muted-foreground">
              Showing the first 100 consultations. Open a consultation directly
              to view proposals beyond that limit.
            </p>
          ) : null}
        </div>
        <div>
          <label
            htmlFor="proposal-status"
            className="mb-1.5 block text-xs font-medium text-foreground"
          >
            Proposal status
          </label>
          <Select
            id="proposal-status"
            value={status ?? ""}
            disabled={!selectedConsultationId}
            onChange={(event) => selectStatus(event.target.value)}
          >
            <option value="">All statuses</option>
            {PROPOSAL_STATUSES.map((value) => (
              <option key={value} value={value}>
                {humanize(value)}
              </option>
            ))}
          </Select>
        </div>
      </div>

      {consultations.isError ? (
        <QueryErrorState
          error={consultations.error}
          onRetry={() => void consultations.refetch()}
        />
      ) : !selectedConsultationId ? (
        <EmptyState
          icon={FileText}
          title="Choose a consultation"
          description="Select a consultation above to load the proposals attached to it. Workspace-wide proposal lists are not exposed by the current API."
          action={
            <Link
              to="/consultations"
              className="inline-flex h-10 items-center rounded-md border border-border-strong bg-surface px-4 text-sm font-medium text-foreground transition-colors hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              Browse consultations
            </Link>
          }
        />
      ) : consultation.isPending ? (
        <Skeleton className="h-32" />
      ) : consultation.isError ? (
        <QueryErrorState
          error={consultation.error}
          onRetry={() => void consultation.refetch()}
        />
      ) : (
        <section aria-labelledby="proposal-results-heading" className="space-y-3">
          <div>
            <h2
              id="proposal-results-heading"
              className="text-base font-semibold text-foreground"
            >
              {consultation.data.title}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {consultation.data.project_id
                ? `${projectsById.get(consultation.data.project_id)?.name ?? "Unknown project"} · `
                : ""}
              {proposals.isPending
                ? "Loading proposals..."
                : `${pluralize(proposalItems.length, "proposal")} loaded${proposals.hasNextPage ? " so far" : ""}.`}
            </p>
          </div>

          {proposals.isError ? (
            <QueryErrorState
              error={proposals.error}
              onRetry={() => void proposals.refetch()}
            />
          ) : proposals.isPending ? (
            <div className="space-y-3">
              <Skeleton className="h-20" />
              <Skeleton className="h-20" />
            </div>
          ) : proposalItems.length === 0 ? (
            <EmptyState
              icon={FileText}
              title="No proposals for this consultation"
              description={
                status
                  ? "No proposals match the selected status. Try clearing the status filter."
                  : "Proposals will appear after the consultation is triaged and a proposal is drafted."
              }
              action={
                status ? (
                  <Button
                    variant="outline"
                    onClick={() => selectStatus("")}
                  >
                    Clear status filter
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
                      Proposals for {consultation.data.title}
                    </caption>
                    <TableHead>
                      <TableRow>
                        <TableHeaderCell>Proposal</TableHeaderCell>
                        <TableHeaderCell>Version</TableHeaderCell>
                        <TableHeaderCell>Status</TableHeaderCell>
                        <TableHeaderCell>Priority</TableHeaderCell>
                        <TableHeaderCell>Category</TableHeaderCell>
                        <TableHeaderCell>Updated</TableHeaderCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {proposalItems.map((proposal) => (
                        <TableRow key={proposal.proposal_id}>
                          <TableCell className="max-w-md">
                            <Link
                              to={`/proposals/${proposal.proposal_id}`}
                              className="line-clamp-1 font-medium text-foreground underline-offset-4 hover:text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            >
                              {proposal.title}
                            </Link>
                          </TableCell>
                          <TableCell className="text-sm text-muted-foreground">
                            v{proposal.version}
                          </TableCell>
                          <TableCell>
                            <StatusBadge status={proposal.status} />
                          </TableCell>
                          <TableCell>
                            <PriorityBadge priority={proposal.priority} />
                          </TableCell>
                          <TableCell className="text-sm text-muted-foreground">
                            {humanize(proposal.category)}
                          </TableCell>
                          <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                            {formatRelativeTime(proposal.updated_at)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              </div>

              <ul className="space-y-3 md:hidden">
                {proposalItems.map((proposal) => (
                  <li key={proposal.proposal_id}>
                    <Link
                      to={`/proposals/${proposal.proposal_id}`}
                      className="block rounded-lg border border-border bg-surface p-4 shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <p className="text-sm font-medium text-foreground">
                          {proposal.title}
                        </p>
                        <StatusBadge status={proposal.status} />
                      </div>
                      <p className="mt-2 text-xs text-muted-foreground">
                        v{proposal.version} · {humanize(proposal.category)} ·{" "}
                        {formatRelativeTime(proposal.updated_at)}
                      </p>
                    </Link>
                  </li>
                ))}
              </ul>

              {proposals.hasNextPage ? (
                <div className="flex justify-center">
                  <Button
                    variant="outline"
                    loading={proposals.isFetchingNextPage}
                    onClick={() => void proposals.fetchNextPage()}
                  >
                    Load more proposals
                  </Button>
                </div>
              ) : null}
            </>
          )}
        </section>
      )}
    </PageLayout>
  );
}
