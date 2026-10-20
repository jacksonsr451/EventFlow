import { queryKeys } from "@eventflow/api-client";
import { QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import {
  ToastProvider,
  TooltipProvider,
} from "@eventflow/ui";
import { AppErrorBoundary } from "./components/error-boundary";
import { AppShell } from "./components/app-shell";
import { AuthCompletePage, LoginPage } from "./pages/auth";
import { BoardDetailPage } from "./pages/board-detail";
import { BoardsPage } from "./pages/boards";
import { ConsultationDetailPage } from "./pages/consultation-detail";
import { ConsultationsPage } from "./pages/consultations";
import { DashboardPage } from "./pages/dashboard";
import { NotFoundPage } from "./pages/not-found";
import { ProposalDetailPage } from "./pages/proposal-detail";
import { ProposalsPage } from "./pages/proposals";
import { ProjectDetailPage } from "./pages/project-detail";
import { ProjectsPage } from "./pages/projects";
import { SettingsPage } from "./pages/settings";
import { WorkItemDetailPage } from "./pages/work-item-detail";
import { WorkItemsPage } from "./pages/work-items";
import { WorkspacePage } from "./pages/workspace";
import { apiClient, setCsrfToken } from "./lib/api";
import { AuthProvider, RequireAuth } from "./lib/auth";
import { queryClient } from "./lib/query-client";
import { ThemeProvider } from "./lib/theme";
import { WorkspaceProvider } from "./lib/workspace";

function UnauthorizedBridge() {
  const navigate = useNavigate();
  const location = useLocation();
  const client = useQueryClient();
  const redirecting = useRef(false);

  useEffect(() => {
    apiClient.setUnauthorizedHandler(() => {
      if (
        redirecting.current ||
        location.pathname === "/login" ||
        location.pathname === "/auth/complete"
      ) {
        return;
      }
      redirecting.current = true;
      setCsrfToken(null);
      client.setQueryData(queryKeys.session, null);
      navigate("/login?expired=1", { replace: true });
      window.setTimeout(() => {
        redirecting.current = false;
      }, 500);
    });

    return () => apiClient.setUnauthorizedHandler(undefined);
  }, [client, location.pathname, navigate]);

  return null;
}

function ProtectedRoutes() {
  return (
    <RequireAuth>
      <WorkspaceProvider>
        <AppShell />
      </WorkspaceProvider>
    </RequireAuth>
  );
}

function ApplicationRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/auth/complete" element={<AuthCompletePage />} />
      <Route element={<ProtectedRoutes />}>
        <Route index element={<DashboardPage />} />
        <Route path="consultations" element={<ConsultationsPage />} />
        <Route path="consultations/:consultationId" element={<ConsultationDetailPage />} />
        <Route path="proposals" element={<ProposalsPage />} />
        <Route path="proposals/:proposalId" element={<ProposalDetailPage />} />
        <Route path="work-items" element={<WorkItemsPage />} />
        <Route path="work-items/:workItemId" element={<WorkItemDetailPage />} />
        <Route path="boards" element={<BoardsPage />} />
        <Route path="boards/:boardId" element={<BoardDetailPage />} />
        <Route path="projects" element={<ProjectsPage />} />
        <Route path="projects/:projectId" element={<ProjectDetailPage />} />
        <Route path="workspaces" element={<WorkspacePage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export function App() {
  return (
    <AppErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>
          <BrowserRouter>
            <AuthProvider>
              <UnauthorizedBridge />
              <ToastProvider>
                <TooltipProvider>
                  <ApplicationRoutes />
                </TooltipProvider>
              </ToastProvider>
            </AuthProvider>
          </BrowserRouter>
        </ThemeProvider>
      </QueryClientProvider>
    </AppErrorBoundary>
  );
}
