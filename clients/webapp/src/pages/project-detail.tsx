import {
  ArrowLeft,
  ExternalLink,
  FolderKanban,
  RefreshCw,
} from "lucide-react";
import { useEffect } from "react";
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
  Skeleton,
  StatusBadge,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeaderCell,
  TableRow,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@eventflow/ui";
import { DetailField } from "../components/detail";
import { QueryErrorState } from "../components/query-state";
import {
  formatDateTime,
  formatRelativeTime,
  humanize,
  pluralize,
} from "../lib/format";
import {
  useProject,
  useRepositories,
  useTriageConfiguration,
  useTriageTemplates,
} from "../lib/queries";
import { useDocumentTitle } from "../lib/use-document-title";
import { isSafeHttpUrl } from "../lib/url";
import { useWorkspace } from "../lib/workspace";

export function ProjectDetailPage() {
  const { projectId: routeProjectId } = useParams();
  const {
    workspace,
    workspaceId,
    projects,
    projectId: contextProjectId,
    selectProject,
  } = useWorkspace();
  const projectQuery = useProject(workspaceId ?? undefined, routeProjectId);
  const repositories = useRepositories(
    workspaceId ?? undefined,
    routeProjectId,
  );
  const triageConfiguration = useTriageConfiguration(
    workspaceId ?? undefined,
    routeProjectId,
  );
  const triageTemplates = useTriageTemplates(
    workspaceId ?? undefined,
    routeProjectId,
  );
  useDocumentTitle(projectQuery.data?.name ?? "Project");

  useEffect(() => {
    if (
      routeProjectId &&
      contextProjectId !== routeProjectId &&
      projects.some((item) => item.project_id === routeProjectId)
    ) {
      selectProject(routeProjectId);
    }
  }, [contextProjectId, projects, routeProjectId, selectProject]);

  if (!workspace) return null;

  if (projectQuery.isPending) {
    return (
      <PageLayout className="space-y-4">
        <Skeleton className="h-4 w-72" />
        <Skeleton className="h-9 w-1/3" />
        <Skeleton className="h-96" />
      </PageLayout>
    );
  }

  if (projectQuery.isError) {
    return (
      <PageLayout>
        <QueryErrorState
          error={projectQuery.error}
          onRetry={() => void projectQuery.refetch()}
        />
        <div className="mt-4 text-center">
          <Link
            to="/projects"
            className="text-sm font-medium text-primary underline-offset-4 hover:underline"
          >
            Back to projects
          </Link>
        </div>
      </PageLayout>
    );
  }

  const project = projectQuery.data;
  const repositoryItems = repositories.data ?? [];
  const configuration = triageConfiguration.data;
  const templateItems = triageTemplates.data?.items ?? [];

  return (
    <PageLayout className="space-y-5">
      <Breadcrumb
        items={[
          { label: workspace.name, href: "/" },
          { label: "Projects", href: "/projects" },
          { label: project.name },
        ]}
      />
      <PageHeader
        eyebrow={project.key}
        title={project.name}
        description={project.description?.trim() || "No description provided."}
        actions={
          <>
            <Button
              variant="outline"
              onClick={() => {
                void projectQuery.refetch();
                void repositories.refetch();
                void triageConfiguration.refetch();
                void triageTemplates.refetch();
              }}
            >
              <RefreshCw className="size-4" aria-hidden="true" />
              Refresh
            </Button>
            <Link
              to="/boards"
              className="inline-flex h-10 items-center gap-2 rounded-md border border-border-strong bg-surface px-4 text-sm font-medium text-foreground transition-colors hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <FolderKanban className="size-4" aria-hidden="true" />
              Boards
            </Link>
            <Link
              to="/projects"
              className="inline-flex h-10 items-center gap-2 rounded-md px-3 text-sm font-medium text-muted-foreground transition-colors hover:bg-surface-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <ArrowLeft className="size-4" aria-hidden="true" />
              Back
            </Link>
          </>
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="accent">Project {project.key}</Badge>
        {contextProjectId === project.project_id ? (
          <Badge tone="success">Active project context</Badge>
        ) : null}
        <span className="text-xs text-muted-foreground">
          Created {formatDateTime(project.created_at)}
        </span>
      </div>

      <Tabs defaultValue="overview">
        <TabsList aria-label="Project sections">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="repositories">
            Repositories
            {!repositories.isPending ? ` (${repositoryItems.length})` : ""}
          </TabsTrigger>
          <TabsTrigger value="triage">Triage configuration</TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          <div className="grid gap-4 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle>Project description</CardTitle>
                <CardDescription>
                  Shared context for delivery and triage.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">
                  {project.description?.trim() || "No description provided."}
                </p>
                <dl className="mt-6 grid gap-4 sm:grid-cols-2">
                  <DetailField label="Workspace">
                    {workspace.name}
                  </DetailField>
                  <DetailField label="Project key">{project.key}</DetailField>
                  <DetailField label="Created">
                    {formatDateTime(project.created_at)}
                  </DetailField>
                  <DetailField label="Updated">
                    {formatDateTime(project.updated_at)}
                  </DetailField>
                </dl>
              </CardContent>
            </Card>
            <Card className="h-fit">
              <CardHeader>
                <CardTitle>Context actions</CardTitle>
                <CardDescription>
                  Scoped views use this project selection.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                <Link
                  to="/boards"
                  className="block rounded-md border border-border px-3 py-2 text-sm font-medium text-foreground transition-colors hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  View project boards
                </Link>
                <Link
                  to="/consultations"
                  className="block rounded-md border border-border px-3 py-2 text-sm font-medium text-foreground transition-colors hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  Browse consultations
                </Link>
                <Link
                  to="/work-items"
                  className="block rounded-md border border-border px-3 py-2 text-sm font-medium text-foreground transition-colors hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  Browse work items
                </Link>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="repositories">
          {repositories.isError ? (
            <QueryErrorState
              error={repositories.error}
              onRetry={() => void repositories.refetch()}
            />
          ) : repositories.isPending ? (
            <Skeleton className="h-64" />
          ) : repositoryItems.length === 0 ? (
            <EmptyState
              icon={FolderKanban}
              title="No linked repositories"
              description="Remote repositories linked to this project will appear here once configured."
            />
          ) : (
            <TableContainer>
              <Table>
                <caption className="sr-only">
                  Repositories linked to {project.name}
                </caption>
                <TableHead>
                  <TableRow>
                    <TableHeaderCell>Repository</TableHeaderCell>
                    <TableHeaderCell>Provider</TableHeaderCell>
                    <TableHeaderCell>Default branch</TableHeaderCell>
                    <TableHeaderCell>Status</TableHeaderCell>
                    <TableHeaderCell>Verification</TableHeaderCell>
                    <TableHeaderCell>Updated</TableHeaderCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {repositoryItems.map((repository) => (
                    <TableRow key={repository.repository_id}>
                      <TableCell>
                        <p className="font-medium text-foreground">
                          {repository.display_name}
                        </p>
                        {isSafeHttpUrl(repository.repository_url) ? (
                          <a
                            href={repository.repository_url}
                            target="_blank"
                            rel="noreferrer noopener"
                            className="mt-0.5 inline-flex items-center gap-1 break-all text-xs text-primary underline-offset-4 hover:underline"
                          >
                            {repository.repository_full_path}
                            <ExternalLink
                              className="size-3"
                              aria-hidden="true"
                            />
                          </a>
                        ) : (
                          <span className="mt-0.5 block break-all text-xs text-muted-foreground">
                            {repository.repository_full_path}
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {humanize(repository.provider)}
                      </TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">
                        {repository.default_branch ?? "Not set"}
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={repository.status} />
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={repository.verification_status} />
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                        {formatRelativeTime(repository.updated_at)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          )}
        </TabsContent>

        <TabsContent value="triage">
          {triageConfiguration.isError ? (
            <QueryErrorState
              error={triageConfiguration.error}
              onRetry={() => void triageConfiguration.refetch()}
            />
          ) : triageConfiguration.isPending ? (
            <Skeleton className="h-64" />
          ) : configuration ? (
            <div className="space-y-4">
              <div className="grid gap-4 lg:grid-cols-3">
                <Card>
                  <CardHeader>
                    <CardTitle>Configuration</CardTitle>
                    <CardDescription>
                      Effective triage settings for this project.
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <dl className="grid gap-4">
                      <DetailField label="Triage enabled">
                        <Badge
                          tone={configuration.enabled ? "success" : "neutral"}
                        >
                          {configuration.enabled ? "Enabled" : "Disabled"}
                        </Badge>
                      </DetailField>
                      <DetailField label="Version">
                        {configuration.version}
                      </DetailField>
                      <DetailField label="Updated">
                        {formatDateTime(configuration.updated_at)}
                      </DetailField>
                      <DetailField label="Custom fields">
                        {configuration.custom_fields.length}
                      </DetailField>
                    </dl>
                  </CardContent>
                </Card>
                <Card className="lg:col-span-2">
                  <CardHeader>
                    <CardTitle>Required fields by category</CardTitle>
                    <CardDescription>
                      Categories without entries use domain defaults.
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    {Object.keys(configuration.required_fields).length === 0 ? (
                      <p className="text-sm text-muted-foreground">
                        No additional required fields configured.
                      </p>
                    ) : (
                      <dl className="grid gap-4 sm:grid-cols-2">
                        {Object.entries(configuration.required_fields).map(
                          ([category, fields]) => (
                            <DetailField key={category} label={humanize(category)}>
                              <div className="flex flex-wrap gap-1.5">
                                {fields.map((field) => (
                                  <Badge key={field} tone="neutral">
                                    {humanize(field)}
                                  </Badge>
                                ))}
                              </div>
                            </DetailField>
                          ),
                        )}
                      </dl>
                    )}
                  </CardContent>
                </Card>
              </div>

              <Card>
                <CardHeader>
                  <CardTitle>Custom fields</CardTitle>
                  <CardDescription>
                    Declarative fields collected during triage.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {configuration.custom_fields.length === 0 ? (
                    <p className="text-sm text-muted-foreground">
                      No custom triage fields configured.
                    </p>
                  ) : (
                    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                      {configuration.custom_fields.map((field) => (
                        <div
                          key={field.key}
                          className="rounded-md border border-border p-3"
                        >
                          <div className="flex items-start justify-between gap-2">
                            <p className="text-sm font-medium text-foreground">
                              {field.label}
                            </p>
                            {field.required ? (
                              <Badge tone="warning">Required</Badge>
                            ) : null}
                          </div>
                          <p className="mt-1 font-mono text-xs text-muted-foreground">
                            {field.key} · {humanize(field.type)}
                          </p>
                          {field.description ? (
                            <p className="mt-2 text-xs text-muted-foreground">
                              {field.description}
                            </p>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Template versions</CardTitle>
                  <CardDescription>
                    {triageTemplates.isPending
                      ? "Loading templates..."
                      : `${pluralize(templateItems.length, "template")} available.`}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {triageTemplates.isError ? (
                    <QueryErrorState
                      error={triageTemplates.error}
                      onRetry={() => void triageTemplates.refetch()}
                      className="border-0"
                    />
                  ) : templateItems.length === 0 ? (
                    <p className="text-sm text-muted-foreground">
                      No triage templates configured for this project.
                    </p>
                  ) : (
                    <ul className="divide-y divide-border">
                      {templateItems.map((template) => (
                        <li
                          key={template.template_id}
                          className="flex flex-wrap items-center justify-between gap-2 py-3 first:pt-0 last:pb-0"
                        >
                          <div>
                            <p className="text-sm font-medium text-foreground">
                              {template.name}
                            </p>
                            <p className="mt-0.5 text-xs text-muted-foreground">
                              {template.key} · {humanize(template.category)}
                            </p>
                          </div>
                          <div className="flex items-center gap-2">
                            <StatusBadge status={template.status} />
                            <span className="text-xs text-muted-foreground">
                              Updated {formatRelativeTime(template.updated_at)}
                            </span>
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </CardContent>
              </Card>
            </div>
          ) : null}
        </TabsContent>
      </Tabs>
    </PageLayout>
  );
}
