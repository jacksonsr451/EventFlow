import {
  Check,
  LogOut,
  Monitor,
  Moon,
  ShieldCheck,
  Sun,
} from "lucide-react";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  PageHeader,
  PageLayout,
  Skeleton,
  useToast,
} from "@eventflow/ui";
import { QueryErrorState } from "../components/query-state";
import { useAuth } from "../lib/auth";
import { presentError } from "../lib/errors";
import { formatDateTime, humanize } from "../lib/format";
import { useAuthSessions, useRevokeAuthSession } from "../lib/queries";
import { useTheme, type ThemePreference } from "../lib/theme";
import { useDocumentTitle } from "../lib/use-document-title";
import { useWorkspace } from "../lib/workspace";

const themeChoices: Array<{
  value: ThemePreference;
  label: string;
  description: string;
  icon: typeof Sun;
}> = [
  {
    value: "light",
    label: "Light",
    description: "Bright surfaces with high-contrast text.",
    icon: Sun,
  },
  {
    value: "dark",
    label: "Dark",
    description: "Reduced luminance for low-light environments.",
    icon: Moon,
  },
  {
    value: "system",
    label: "System",
    description: "Follow your operating system appearance.",
    icon: Monitor,
  },
];

export function SettingsPage() {
  const { session, logout } = useAuth();
  const { theme, setTheme } = useTheme();
  const { workspace, project } = useWorkspace();
  const sessions = useAuthSessions();
  const revokeSession = useRevokeAuthSession();
  const { showToast } = useToast();
  useDocumentTitle("Settings");

  async function handleLogout() {
    try {
      await logout();
    } catch (error) {
      showToast({
        tone: "destructive",
        title: "Could not sign out",
        description: presentError(error).description,
      });
    }
  }

  function handleRevoke(sessionId: string) {
    revokeSession.mutate(sessionId, {
      onSuccess: () => {
        showToast({
          tone: "success",
          title: "Session revoked",
          description: "The selected browser session can no longer be used.",
        });
      },
      onError: (error) => {
        showToast({
          tone: "destructive",
          title: "Could not revoke session",
          description: presentError(error).description,
        });
      },
    });
  }

  return (
    <PageLayout className="space-y-5">
      <PageHeader
        title="Settings"
        description="Appearance, session security, and local workspace context."
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Appearance</CardTitle>
            <CardDescription>
              The preference is stored locally and is not sent to the API.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <fieldset>
              <legend className="sr-only">Theme</legend>
              <div className="grid gap-2">
                {themeChoices.map((choice) => {
                  const Icon = choice.icon;
                  const selected = theme === choice.value;
                  return (
                    <label
                      key={choice.value}
                      className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors ${
                        selected
                          ? "border-primary bg-primary/5"
                          : "border-border hover:bg-surface-muted"
                      }`}
                    >
                      <input
                        type="radio"
                        name="theme"
                        value={choice.value}
                        checked={selected}
                        onChange={() => setTheme(choice.value)}
                        className="sr-only"
                      />
                      <span className="mt-0.5 flex size-8 items-center justify-center rounded-md bg-surface-muted text-muted-foreground">
                        <Icon className="size-4" aria-hidden="true" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-sm font-medium text-foreground">
                          {choice.label}
                        </span>
                        <span className="block text-xs text-muted-foreground">
                          {choice.description}
                        </span>
                      </span>
                      {selected ? (
                        <Check
                          className="mt-1 size-4 text-primary"
                          aria-hidden="true"
                        />
                      ) : null}
                    </label>
                  );
                })}
              </div>
            </fieldset>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Current session</CardTitle>
            <CardDescription>
              EventFlow uses server-managed sessions. Tokens are never stored in
              browser storage.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {session ? (
              <dl className="grid gap-4">
                <div>
                  <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    User ID
                  </dt>
                  <dd className="mt-1 break-all font-mono text-xs text-foreground">
                    {session.user_id}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Session ID
                  </dt>
                  <dd className="mt-1 break-all font-mono text-xs text-foreground">
                    {session.session_id}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Expires
                  </dt>
                  <dd className="mt-1 text-sm text-foreground">
                    {formatDateTime(session.expires_at)}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    CSRF protection
                  </dt>
                  <dd className="mt-1 flex items-center gap-1.5 text-sm text-foreground">
                    <ShieldCheck
                      className="size-4 text-success"
                      aria-hidden="true"
                    />
                    Token held in memory for unsafe requests
                  </dd>
                </div>
                <div>
                  <Button variant="outline" onClick={() => void handleLogout()}>
                    <LogOut className="size-4" aria-hidden="true" />
                    Sign out of this browser
                  </Button>
                </div>
              </dl>
            ) : (
              <p className="text-sm text-muted-foreground">No active session.</p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Browser sessions</CardTitle>
          <CardDescription>
            Active sessions associated with your identity. Revoking a session
            removes its access immediately.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {sessions.isError ? (
            <QueryErrorState
              error={sessions.error}
              onRetry={() => void sessions.refetch()}
              className="border-0"
            />
          ) : sessions.isPending ? (
            <div className="space-y-2">
              <Skeleton className="h-12" />
              <Skeleton className="h-12" />
            </div>
          ) : (sessions.data ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No active sessions returned.
            </p>
          ) : (
            <ul className="divide-y divide-border">
              {(sessions.data ?? []).map((item) => (
                <li
                  key={item.session_id}
                  className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0 sm:flex-row sm:items-center sm:justify-between"
                >
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="font-mono text-xs text-foreground">
                        {item.session_id}
                      </p>
                      {item.current ? <Badge tone="accent">Current</Badge> : null}
                      <Badge tone="neutral">{humanize(item.source)}</Badge>
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {item.client_id} · Last seen{" "}
                      {formatDateTime(item.last_seen_at)} · Expires{" "}
                      {formatDateTime(item.expires_at)}
                    </p>
                  </div>
                  {!item.current ? (
                    <Button
                      variant="outline"
                      size="sm"
                      loading={
                        revokeSession.isPending &&
                        revokeSession.variables === item.session_id
                      }
                      onClick={() => handleRevoke(item.session_id)}
                    >
                      Revoke
                    </Button>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Local context</CardTitle>
            <CardDescription>
              Remembered only in this browser.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <dl className="grid gap-4">
              <div>
                <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Workspace
                </dt>
                <dd className="mt-1 text-sm text-foreground">
                  {workspace?.name ?? "None"}
                </dd>
              </div>
              <div>
                <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Project
                </dt>
                <dd className="mt-1 text-sm text-foreground">
                  {project?.name ?? "All projects"}
                </dd>
              </div>
            </dl>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>API boundaries</CardTitle>
            <CardDescription>
              The web client only calls supported Work Management endpoints.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="list-disc space-y-1.5 pl-5 text-sm text-muted-foreground">
              <li>Proposals are loaded per consultation.</li>
              <li>Consultations and work items are workspace-wide.</li>
              <li>Boards can be filtered by project.</li>
              <li>No dashboard totals are fabricated from partial pages.</li>
            </ul>
          </CardContent>
        </Card>
      </div>
    </PageLayout>
  );
}
