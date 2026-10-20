import { Building2, LogOut, RefreshCw } from "lucide-react";
import { useState } from "react";
import { Outlet } from "react-router-dom";
import {
  Alert,
  Button,
  EmptyState,
  ErrorState,
  PageLoading,
  SkipLink,
  Spinner,
} from "@eventflow/ui";
import { useAuth } from "../lib/auth";
import { presentError } from "../lib/errors";
import { useWorkspace } from "../lib/workspace";
import { AppHeader } from "./header";
import { DesktopSidebar, MobileNavigation } from "./navigation";

export function AppShell() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const { logout } = useAuth();
  const {
    workspace,
    isWorkspacesLoading,
    workspacesError,
    refreshWorkspaces,
    projectsError,
  } = useWorkspace();

  if (isWorkspacesLoading) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-3">
          <span className="flex size-12 items-center justify-center rounded-xl bg-primary text-lg font-semibold text-primary-foreground">
            EF
          </span>
          <Spinner label="Loading workspaces" />
        </div>
      </div>
    );
  }

  if (workspacesError) {
    const presented = presentError(workspacesError);
    return (
      <main className="flex min-h-dvh items-center justify-center bg-background px-4">
        <div className="w-full max-w-lg">
          <ErrorState
            status={presented.status}
            title={presented.title}
            description={presented.description}
            correlationId={presented.correlationId}
            onRetry={refreshWorkspaces}
            action={
              <Button variant="outline" onClick={() => void logout()}>
                <LogOut className="size-4" aria-hidden="true" />
                Sign out
              </Button>
            }
          />
        </div>
      </main>
    );
  }

  if (!workspace) {
    return (
      <main className="flex min-h-dvh items-center justify-center bg-background px-4">
        <div className="w-full max-w-lg">
          <EmptyState
            icon={Building2}
            title="No accessible workspaces"
            description="You are signed in, but you do not belong to an EventFlow workspace yet. Ask a workspace administrator to add you, then refresh this page."
            action={
              <div className="flex flex-wrap justify-center gap-2">
                <Button onClick={refreshWorkspaces}>
                  <RefreshCw className="size-4" aria-hidden="true" />
                  Refresh
                </Button>
                <Button variant="outline" onClick={() => void logout()}>
                  <LogOut className="size-4" aria-hidden="true" />
                  Sign out
                </Button>
              </div>
            }
          />
        </div>
      </main>
    );
  }

  return (
    <div className="min-h-dvh bg-background">
      <SkipLink />
      <DesktopSidebar />
      <div className="lg:pl-[var(--sidebar-width)]">
        <AppHeader onOpenMenu={() => setMobileOpen(true)} />
        <main id="main-content" tabIndex={-1} className="focus:outline-none">
          {projectsError ? (
            <div className="px-4 pt-4 sm:px-6 lg:px-8">
              <Alert
                tone="warning"
                title="Project context is unavailable"
                action={
                  <Button variant="outline" size="sm" onClick={refreshWorkspaces}>
                    Retry
                  </Button>
                }
              >
                Some project-scoped views may be incomplete. Workspace-wide data
                is still available.
              </Alert>
            </div>
          ) : null}
          <Outlet />
        </main>
      </div>
      <MobileNavigation open={mobileOpen} onOpenChange={setMobileOpen} />
    </div>
  );
}

export function AppBootLoading() {
  return (
    <div className="min-h-dvh bg-background p-6">
      <PageLoading label="Loading EventFlow" />
    </div>
  );
}
