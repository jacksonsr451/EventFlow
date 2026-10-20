import { ArrowLeft, ExternalLink, FileText, RefreshCw } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import {
  Badge,
  Breadcrumb,
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
import { DetailField, DetailSection, Prose } from "../components/detail";
import { QueryErrorState } from "../components/query-state";
import { formatDateTime, formatRelativeTime, humanize, pluralize } from "../lib/format";
import {
  useConsultation,
  useConsultationProposals,
} from "../lib/queries";
import { useDocumentTitle } from "../lib/use-document-title";
import { isSafeHttpUrl } from "../lib/url";
import { useWorkspace } from "../lib/workspace";

function formatCustomFieldValue(value: unknown): string {
  if (value === null || value === undefined) return "Not set";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

export function ConsultationDetailPage() {
  const { consultationId } = useParams();
  const { workspace, workspaceId, projects } = useWorkspace();
  const consultationQuery = useConsultation(
    workspaceId ?? undefined,
    consultationId,
  );
  const proposals = useConsultationProposals(
    workspaceId ?? undefined,
    consultationId,
    { sort: "-created_at" },
  );
  useDocumentTitle(consultationQuery.data?.title ?? "Consultation");

  if (!workspace) return null;

  if (consultationQuery.isPending) {
    return (
      <PageLayout className="space-y-4">
        <Skeleton className="h-4 w-72" />
        <Skeleton className="h-9 w-2/3" />
        <div className="grid gap-4 lg:grid-cols-3">
          <Skeleton className="h-96 lg:col-span-2" />
          <Skeleton className="h-96" />
        </div>
      </PageLayout>
    );
  }

  if (consultationQuery.isError) {
    return (
      <PageLayout>
        <QueryErrorState
          error={consultationQuery.error}
          onRetry={() => void consultationQuery.refetch()}
        />
        <div className="mt-4 text-center">
          <Link
            to="/consultations"
            className="text-sm font-medium text-primary underline-offset-4 hover:underline"
          >
            Back to consultations
          </Link>
        </div>
      </PageLayout>
    );
  }

  const consultation = consultationQuery.data;
  const project = projects.find(
    (candidate) => candidate.project_id === consultation.project_id,
  );
  const proposalItems =
    proposals.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <PageLayout className="space-y-5">
      <Breadcrumb
        items={[
          { label: workspace.name, href: "/" },
          { label: "Consultations", href: "/consultations" },
          { label: consultation.title },
        ]}
      />
      <PageHeader
        eyebrow={project ? `${project.key} · ${project.name}` : "Workspace request"}
        title={consultation.title}
        description={`Created ${formatRelativeTime(consultation.created_at)} by ${consultation.author_id}.`}
        actions={
          <>
            <Button variant="outline" onClick={() => void consultationQuery.refetch()}>
              <RefreshCw className="size-4" aria-hidden="true" />
              Refresh
            </Button>
            <Link
              to="/consultations"
              className="inline-flex h-10 items-center gap-2 rounded-md px-3 text-sm font-medium text-muted-foreground transition-colors hover:bg-surface-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <ArrowLeft className="size-4" aria-hidden="true" />
              Back
            </Link>
          </>
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={consultation.status} />
        <PriorityBadge priority={consultation.priority} />
        <Badge tone="neutral">{humanize(consultation.category)}</Badge>
        <Badge tone="neutral">{humanize(consultation.origin)} origin</Badge>
        {consultation.active_proposal_id ? (
          <Badge tone="accent">Active proposal selected</Badge>
        ) : null}
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <DetailSection title="Request description">
            <Prose>{consultation.description}</Prose>
          </DetailSection>

          {(consultation.external_references ?? []).length > 0 ? (
            <DetailSection title="External references">
              <ul className="space-y-2">
                {(consultation.external_references ?? []).map((reference, index) => (
                  <li key={`${reference}-${index}`} className="flex items-start gap-2">
                    <ExternalLink
                      className="mt-0.5 size-3.5 shrink-0 text-muted-foreground"
                      aria-hidden="true"
                    />
                    {isSafeHttpUrl(reference) ? (
                      <a
                        href={reference}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="break-all text-primary underline-offset-4 hover:underline"
                      >
                        {reference}
                      </a>
                    ) : (
                      <span className="break-all">{reference}</span>
                    )}
                  </li>
                ))}
              </ul>
            </DetailSection>
          ) : null}

          {consultation.editor_context ? (
            <DetailSection title="Editor context">
              <dl className="grid gap-4 sm:grid-cols-2">
                <DetailField label="Repository">
                  {consultation.editor_context.repository}
                </DetailField>
                <DetailField label="Branch">
                  {consultation.editor_context.branch}
                </DetailField>
                <DetailField label="File">
                  {consultation.editor_context.file_path}
                </DetailField>
                <DetailField label="Lines">
                  {consultation.editor_context.line_start}–
                  {consultation.editor_context.line_end}
                </DetailField>
                <DetailField label="Commit">
                  <span className="font-mono text-xs">
                    {consultation.editor_context.commit_sha}
                  </span>
                </DetailField>
              </dl>
              {consultation.editor_context.selected_code_snippet ? (
                <pre className="mt-4 overflow-x-auto rounded-md bg-surface-muted p-3 text-xs">
                  <code>
                    {consultation.editor_context.selected_code_snippet}
                  </code>
                </pre>
              ) : null}
            </DetailSection>
          ) : null}

          {consultation.triage_custom_fields &&
          Object.keys(consultation.triage_custom_fields).length > 0 ? (
            <DetailSection title="Triage fields">
              <dl className="grid gap-4 sm:grid-cols-2">
                {Object.entries(consultation.triage_custom_fields).map(
                  ([key, value]) => (
                    <DetailField key={key} label={humanize(key)}>
                      {formatCustomFieldValue(value)}
                    </DetailField>
                  ),
                )}
              </dl>
            </DetailSection>
          ) : null}
        </div>

        <Card className="h-fit">
          <CardHeader>
            <CardTitle>Details</CardTitle>
            <CardDescription>Request metadata and triage signals.</CardDescription>
          </CardHeader>
          <CardContent>
            <dl className="grid gap-4">
              <DetailField label="Project">
                {project?.name ?? "Unknown project"}
              </DetailField>
              <DetailField label="Author">
                <span className="font-mono text-xs">{consultation.author_id}</span>
              </DetailField>
              <DetailField label="Assignee">
                {consultation.assignee_id ? (
                  <span className="font-mono text-xs">
                    {consultation.assignee_id}
                  </span>
                ) : (
                  "Unassigned"
                )}
              </DetailField>
              <DetailField label="Business impact">
                {humanize(consultation.business_impact)}
              </DetailField>
              <DetailField label="Business urgency">
                {humanize(consultation.business_urgency)}
              </DetailField>
              <DetailField label="Created">
                {formatDateTime(consultation.created_at)}
              </DetailField>
              <DetailField label="Updated">
                {formatDateTime(consultation.updated_at)}
              </DetailField>
              {consultation.active_proposal_id ? (
                <DetailField label="Active proposal">
                  <Link
                    to={`/proposals/${consultation.active_proposal_id}`}
                    className="text-primary underline-offset-4 hover:underline"
                  >
                    Open active proposal
                  </Link>
                </DetailField>
              ) : null}
            </dl>
          </CardContent>
        </Card>
      </div>

      <section aria-labelledby="consultation-proposals-heading" className="space-y-3">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <h2
              id="consultation-proposals-heading"
              className="text-base font-semibold text-foreground"
            >
              Proposals
            </h2>
            <p className="text-sm text-muted-foreground">
              {proposals.isPending
                ? "Loading proposals..."
                : `${pluralize(proposalItems.length, "proposal")} loaded.`}
            </p>
          </div>
        </div>

        {proposals.isError ? (
          <QueryErrorState
            error={proposals.error}
            onRetry={() => void proposals.refetch()}
          />
        ) : proposals.isPending ? (
          <div className="space-y-3">
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
          </div>
        ) : proposalItems.length === 0 ? (
          <EmptyState
            icon={FileText}
            title="No proposals yet"
            description="Proposals appear after this consultation is triaged and a proposal is drafted."
          />
        ) : (
          <ul className="space-y-3">
            {proposalItems.map((proposal) => (
              <li key={proposal.proposal_id}>
                <Link
                  to={`/proposals/${proposal.proposal_id}`}
                  className="block rounded-lg border border-border bg-surface p-4 shadow-sm transition-colors hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-foreground">
                        {proposal.title}
                      </p>
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        Version {proposal.version} ·{" "}
                        {formatRelativeTime(proposal.updated_at)}
                      </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      {proposal.proposal_id === consultation.active_proposal_id ? (
                        <Badge tone="accent">Active</Badge>
                      ) : null}
                      <StatusBadge status={proposal.status} />
                      <PriorityBadge priority={proposal.priority} />
                    </div>
                  </div>
                  <p className="mt-3 line-clamp-2 text-sm text-muted-foreground">
                    {proposal.technical_description}
                  </p>
                </Link>
              </li>
            ))}
          </ul>
        )}

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
      </section>
    </PageLayout>
  );
}
