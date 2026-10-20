import { ArrowLeft, ExternalLink, RefreshCw } from "lucide-react";
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
import { useWorkItem } from "../lib/queries";
import { useDocumentTitle } from "../lib/use-document-title";
import { isSafeHttpUrl } from "../lib/url";
import { useWorkspace } from "../lib/workspace";

export function WorkItemDetailPage() {
  const { workItemId } = useParams();
  const { workspace, workspaceId, projects } = useWorkspace();
  const workItemQuery = useWorkItem(workspaceId ?? undefined, workItemId);
  useDocumentTitle(workItemQuery.data?.title ?? "Work item");

  if (!workspace) return null;

  if (workItemQuery.isPending) {
    return (
      <PageLayout className="space-y-4">
        <Skeleton className="h-4 w-72" />
        <Skeleton className="h-9 w-2/3" />
        <div className="grid gap-4 lg:grid-cols-3">
          <Skeleton className="h-80 lg:col-span-2" />
          <Skeleton className="h-80" />
        </div>
      </PageLayout>
    );
  }

  if (workItemQuery.isError) {
    return (
      <PageLayout>
        <QueryErrorState
          error={workItemQuery.error}
          onRetry={() => void workItemQuery.refetch()}
        />
        <div className="mt-4 text-center">
          <Link
            to="/work-items"
            className="text-sm font-medium text-primary underline-offset-4 hover:underline"
          >
            Back to work items
          </Link>
        </div>
      </PageLayout>
    );
  }

  const workItem = workItemQuery.data;
  const project = projects.find(
    (candidate) => candidate.project_id === workItem.project_id,
  );

  return (
    <PageLayout className="space-y-5">
      <Breadcrumb
        items={[
          { label: workspace.name, href: "/" },
          { label: "Work items", href: "/work-items" },
          { label: workItem.title },
        ]}
      />
      <PageHeader
        eyebrow={project ? `${project.key} · ${project.name}` : "Delivery work"}
        title={workItem.title}
        description={`Updated ${formatDateTime(workItem.updated_at)}.`}
        actions={
          <>
            <Button
              variant="outline"
              onClick={() => void workItemQuery.refetch()}
            >
              <RefreshCw className="size-4" aria-hidden="true" />
              Refresh
            </Button>
            <Link
              to="/work-items"
              className="inline-flex h-10 items-center gap-2 rounded-md px-3 text-sm font-medium text-muted-foreground transition-colors hover:bg-surface-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <ArrowLeft className="size-4" aria-hidden="true" />
              Back
            </Link>
          </>
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={workItem.status} />
        <PriorityBadge priority={workItem.priority} />
        <Badge tone="neutral">{humanize(workItem.category)}</Badge>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <DetailSection title="Description">
            <Prose>{workItem.description}</Prose>
          </DetailSection>
          <DetailSection title="Acceptance criteria">
            {workItem.acceptance_criteria.length === 0 ? (
              <p className="text-muted-foreground">
                No acceptance criteria were provided.
              </p>
            ) : (
              <ul className="list-disc space-y-1.5 pl-5">
                {workItem.acceptance_criteria.map((criterion, index) => (
                  <li key={`${criterion}-${index}`}>{criterion}</li>
                ))}
              </ul>
            )}
          </DetailSection>
          {(workItem.external_issue_links ?? []).length > 0 ? (
            <DetailSection title="External issue links">
              <ul className="space-y-2">
                {(workItem.external_issue_links ?? []).map((link, index) => (
                  <li
                    key={`${link}-${index}`}
                    className="flex items-start gap-2"
                  >
                    <ExternalLink
                      className="mt-0.5 size-3.5 shrink-0 text-muted-foreground"
                      aria-hidden="true"
                    />
                    {isSafeHttpUrl(link) ? (
                      <a
                        href={link}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="break-all text-primary underline-offset-4 hover:underline"
                      >
                        {link}
                      </a>
                    ) : (
                      <span className="break-all">{link}</span>
                    )}
                  </li>
                ))}
              </ul>
            </DetailSection>
          ) : null}
        </div>

        <Card className="h-fit">
          <CardHeader>
            <CardTitle>Work item details</CardTitle>
            <CardDescription>Ownership and delivery metadata.</CardDescription>
          </CardHeader>
          <CardContent>
            <dl className="grid gap-4">
              <DetailField label="Project">
                {project?.name ?? "Unknown project"}
              </DetailField>
              <DetailField label="Assignee">
                {workItem.assignee_id ? (
                  <span className="font-mono text-xs">
                    {workItem.assignee_id}
                  </span>
                ) : (
                  "Unassigned"
                )}
              </DetailField>
              <DetailField label="Origin proposal">
                <Link
                  to={`/proposals/${workItem.origin_proposal_id}`}
                  className="text-primary underline-offset-4 hover:underline"
                >
                  Proposal v{workItem.origin_proposal_version}
                </Link>
              </DetailField>
              <DetailField label="Approval">
                <span className="break-all font-mono text-xs">
                  {workItem.origin_approval_id}
                </span>
              </DetailField>
              <DetailField label="Created">
                {formatDateTime(workItem.created_at)}
              </DetailField>
              <DetailField label="Updated">
                {formatDateTime(workItem.updated_at)}
              </DetailField>
            </dl>
          </CardContent>
        </Card>
      </div>
    </PageLayout>
  );
}
