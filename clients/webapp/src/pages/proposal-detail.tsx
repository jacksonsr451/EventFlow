import { ArrowLeft, CheckCircle2, Circle, RefreshCw } from "lucide-react";
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
  PageHeader,
  PageLayout,
  PriorityBadge,
  Skeleton,
  StatusBadge,
} from "@eventflow/ui";
import { DetailField, DetailSection, Prose } from "../components/detail";
import { QueryErrorState } from "../components/query-state";
import { formatDateTime, humanize } from "../lib/format";
import { useProposal } from "../lib/queries";
import { useDocumentTitle } from "../lib/use-document-title";
import { useWorkspace } from "../lib/workspace";

function TextList({
  items,
  emptyText,
}: {
  items: string[];
  emptyText: string;
}) {
  if (items.length === 0) {
    return <p className="text-muted-foreground">{emptyText}</p>;
  }
  return (
    <ul className="list-disc space-y-1.5 pl-5">
      {items.map((item, index) => (
        <li key={`${item}-${index}`}>{item}</li>
      ))}
    </ul>
  );
}

export function ProposalDetailPage() {
  const { proposalId } = useParams();
  const { workspace, workspaceId, projects } = useWorkspace();
  const proposalQuery = useProposal(workspaceId ?? undefined, proposalId);
  useDocumentTitle(proposalQuery.data?.title ?? "Proposal");

  if (!workspace) return null;

  if (proposalQuery.isPending) {
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

  if (proposalQuery.isError) {
    return (
      <PageLayout>
        <QueryErrorState
          error={proposalQuery.error}
          onRetry={() => void proposalQuery.refetch()}
        />
        <div className="mt-4 text-center">
          <Link
            to="/proposals"
            className="text-sm font-medium text-primary underline-offset-4 hover:underline"
          >
            Back to proposals
          </Link>
        </div>
      </PageLayout>
    );
  }

  const proposal = proposalQuery.data;
  const project = projects.find(
    (candidate) => candidate.project_id === proposal.project_id,
  );

  return (
    <PageLayout className="space-y-5">
      <Breadcrumb
        items={[
          { label: workspace.name, href: "/" },
          { label: "Consultations", href: "/consultations" },
          {
            label: "Consultation",
            href: `/consultations/${proposal.consultation_id}`,
          },
          { label: proposal.title },
        ]}
      />
      <PageHeader
        eyebrow={`Proposal v${proposal.version} · ${project?.name ?? "Workspace"}`}
        title={proposal.title}
        description={`Proposed by ${proposal.proposer_id}.`}
        actions={
          <>
            <Button
              variant="outline"
              onClick={() => void proposalQuery.refetch()}
            >
              <RefreshCw className="size-4" aria-hidden="true" />
              Refresh
            </Button>
            <Link
              to={`/consultations/${proposal.consultation_id}`}
              className="inline-flex h-10 items-center gap-2 rounded-md px-3 text-sm font-medium text-muted-foreground transition-colors hover:bg-surface-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <ArrowLeft className="size-4" aria-hidden="true" />
              Consultation
            </Link>
          </>
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={proposal.status} />
        <PriorityBadge priority={proposal.priority} />
        <Badge tone="neutral">{humanize(proposal.category)}</Badge>
        {proposal.estimated_hours !== null ? (
          <Badge tone="info">
            {proposal.estimated_hours}{" "}
            {proposal.estimated_hours === 1 ? "hour" : "hours"} estimated
          </Badge>
        ) : null}
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <DetailSection title="Technical description">
            <Prose>{proposal.technical_description}</Prose>
          </DetailSection>
          <DetailSection title="Scope">
            <Prose>{proposal.scope}</Prose>
          </DetailSection>
          <DetailSection title="Justification">
            <Prose>{proposal.justification}</Prose>
          </DetailSection>
          <DetailSection title="Acceptance criteria">
            <TextList
              items={proposal.acceptance_criteria}
              emptyText="No acceptance criteria were provided."
            />
          </DetailSection>
          <DetailSection title="Checklist">
            {proposal.checklist.length === 0 ? (
              <p className="text-muted-foreground">No checklist items.</p>
            ) : (
              <ul className="space-y-2">
                {proposal.checklist.map((item) => (
                  <li key={item.item_id} className="flex items-start gap-2">
                    {item.done ? (
                      <CheckCircle2
                        className="mt-0.5 size-4 shrink-0 text-success"
                        aria-hidden="true"
                      />
                    ) : (
                      <Circle
                        className="mt-0.5 size-4 shrink-0 text-muted-foreground"
                        aria-hidden="true"
                      />
                    )}
                    <span
                      className={
                        item.done ? "text-muted-foreground line-through" : ""
                      }
                    >
                      {item.text}
                    </span>
                    <span className="sr-only">
                      {item.done ? "Completed" : "Not completed"}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </DetailSection>
          <div className="grid gap-4 sm:grid-cols-2">
            <DetailSection title="Risks">
            <TextList
              items={proposal.risks ?? []}
                emptyText="No risks recorded."
              />
            </DetailSection>
            <DetailSection title="Dependencies">
            <TextList
              items={proposal.dependencies ?? []}
                emptyText="No dependencies recorded."
              />
            </DetailSection>
          </div>
        </div>

        <Card className="h-fit">
          <CardHeader>
            <CardTitle>Proposal details</CardTitle>
            <CardDescription>Ownership, timing, and evidence.</CardDescription>
          </CardHeader>
          <CardContent>
            <dl className="grid gap-4">
              <DetailField label="Project">
                {project?.name ?? "Unknown project"}
              </DetailField>
              <DetailField label="Version">v{proposal.version}</DetailField>
              <DetailField label="Proposer">
                <span className="font-mono text-xs">{proposal.proposer_id}</span>
              </DetailField>
              <DetailField label="Reviewer">
                {proposal.reviewer_id ? (
                  <span className="font-mono text-xs">
                    {proposal.reviewer_id}
                  </span>
                ) : (
                  "Not assigned"
                )}
              </DetailField>
              <DetailField label="Created">
                {formatDateTime(proposal.created_at)}
              </DetailField>
              <DetailField label="Updated">
                {formatDateTime(proposal.updated_at)}
              </DetailField>
              <DetailField label="Evidence">
                {(proposal.evidence ?? []).length === 0 ? (
                  "None cited"
                ) : (
                  <ul className="space-y-1 font-mono text-xs">
                    {(proposal.evidence ?? []).map((evidenceId) => (
                      <li key={evidenceId}>{evidenceId}</li>
                    ))}
                  </ul>
                )}
              </DetailField>
              {proposal.duplicated_from_proposal_id ? (
                <DetailField label="Duplicated from">
                  <Link
                    to={`/proposals/${proposal.duplicated_from_proposal_id}`}
                    className="break-all text-primary underline-offset-4 hover:underline"
                  >
                    {proposal.duplicated_from_proposal_id}
                  </Link>
                </DetailField>
              ) : null}
              {proposal.superseded_by_proposal_id ? (
                <DetailField label="Superseded by">
                  <Link
                    to={`/proposals/${proposal.superseded_by_proposal_id}`}
                    className="break-all text-primary underline-offset-4 hover:underline"
                  >
                    {proposal.superseded_by_proposal_id}
                  </Link>
                </DetailField>
              ) : null}
            </dl>
          </CardContent>
        </Card>
      </div>
    </PageLayout>
  );
}
