import { Building2, Check, RefreshCw, Users } from "lucide-react";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  EmptyState,
  PageHeader,
  PageLayout,
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
import { formatDateTime, humanize, pluralize, truncateId } from "../lib/format";
import { useWorkspaceMembers } from "../lib/queries";
import { useDocumentTitle } from "../lib/use-document-title";
import { useWorkspace } from "../lib/workspace";

export function WorkspacePage() {
  const {
    workspace,
    workspaceId,
    workspaces,
    selectWorkspace,
    refreshWorkspaces,
  } = useWorkspace();
  const members = useWorkspaceMembers(workspaceId ?? undefined);
  useDocumentTitle("Workspace");

  if (!workspace) return null;

  return (
    <PageLayout className="space-y-5">
      <PageHeader
        eyebrow={workspace.slug}
        title={workspace.name}
        description="Workspace context, membership, and access roles."
        actions={
          <Button
            variant="outline"
            onClick={() => {
              refreshWorkspaces();
              void members.refetch();
            }}
          >
            <RefreshCw className="size-4" aria-hidden="true" />
            Refresh
          </Button>
        }
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Workspace details</CardTitle>
            <CardDescription>
              This context is used by workspace-scoped lists and boards.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <dl className="grid gap-4 sm:grid-cols-2">
              <div>
                <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Name
                </dt>
                <dd className="mt-1 text-sm text-foreground">{workspace.name}</dd>
              </div>
              <div>
                <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Slug
                </dt>
                <dd className="mt-1 font-mono text-sm text-foreground">
                  {workspace.slug}
                </dd>
              </div>
              <div>
                <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Created
                </dt>
                <dd className="mt-1 text-sm text-foreground">
                  {formatDateTime(workspace.created_at)}
                </dd>
              </div>
              <div>
                <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Updated
                </dt>
                <dd className="mt-1 text-sm text-foreground">
                  {formatDateTime(workspace.updated_at)}
                </dd>
              </div>
              <div className="sm:col-span-2">
                <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Workspace ID
                </dt>
                <dd className="mt-1 break-all font-mono text-xs text-foreground">
                  {workspace.workspace_id}
                </dd>
              </div>
            </dl>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Switch workspace</CardTitle>
            <CardDescription>
              You have access to {pluralize(workspaces.length, "workspace")}.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {workspaces.map((item) => (
              <button
                key={item.workspace_id}
                type="button"
                onClick={() => selectWorkspace(item.workspace_id)}
                className="flex w-full items-center gap-2 rounded-md border border-border px-3 py-2 text-left text-sm transition-colors hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <Building2 className="size-4 text-muted-foreground" aria-hidden="true" />
                <span className="min-w-0 flex-1 truncate">{item.name}</span>
                {item.workspace_id === workspace.workspace_id ? (
                  <Check className="size-4 text-primary" aria-hidden="true" />
                ) : null}
              </button>
            ))}
          </CardContent>
        </Card>
      </div>

      <section aria-labelledby="members-heading" className="space-y-3">
        <div>
          <h2
            id="members-heading"
            className="flex items-center gap-2 text-base font-semibold text-foreground"
          >
            <Users className="size-4" aria-hidden="true" />
            Members
          </h2>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Roles and membership state for this workspace.
          </p>
        </div>

        {members.isError ? (
          <QueryErrorState
            error={members.error}
            onRetry={() => void members.refetch()}
          />
        ) : members.isPending ? (
          <div className="space-y-3">
            <Skeleton className="h-12" />
            <Skeleton className="h-12" />
            <Skeleton className="h-12" />
          </div>
        ) : (members.data ?? []).length === 0 ? (
          <EmptyState
            icon={Users}
            title="No members returned"
            description="The workspace membership list is empty or is not visible to your role."
          />
        ) : (
          <TableContainer>
            <Table>
              <caption className="sr-only">
                Members of {workspace.name}
              </caption>
              <TableHead>
                <TableRow>
                  <TableHeaderCell>Member</TableHeaderCell>
                  <TableHeaderCell>User</TableHeaderCell>
                  <TableHeaderCell>Role</TableHeaderCell>
                  <TableHeaderCell>State</TableHeaderCell>
                  <TableHeaderCell>Joined</TableHeaderCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {(members.data ?? []).map((member) => (
                  <TableRow key={member.membership_id}>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {truncateId(member.membership_id)}
                    </TableCell>
                    <TableCell className="font-mono text-xs text-foreground">
                      {member.user_id}
                    </TableCell>
                    <TableCell>
                      <Badge tone="neutral">{humanize(member.role)}</Badge>
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={member.state} />
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                      {formatDateTime(member.created_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </section>
    </PageLayout>
  );
}
