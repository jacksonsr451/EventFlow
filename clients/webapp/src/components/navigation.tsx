import {
  Building2,
  Check,
  ChevronsUpDown,
  FileText,
  FolderKanban,
  Inbox,
  KanbanSquare,
  LayoutDashboard,
  ListChecks,
  Settings,
} from "lucide-react";
import { NavLink } from "react-router-dom";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@eventflow/ui";
import { useWorkspace } from "../lib/workspace";

const primaryNavigation = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/consultations", label: "Consultations", icon: Inbox },
  { to: "/proposals", label: "Proposals", icon: FileText },
  { to: "/work-items", label: "Work items", icon: ListChecks },
  { to: "/boards", label: "Boards", icon: KanbanSquare },
  { to: "/projects", label: "Projects", icon: FolderKanban },
  { to: "/workspaces", label: "Workspace", icon: Building2 },
];

function WorkspaceSwitcher() {
  const { workspaces, workspace, selectWorkspace } = useWorkspace();
  if (!workspace) return null;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="flex w-full items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-left transition-colors hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={`Switch workspace. Current workspace: ${workspace.name}`}
        >
          <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
            <Building2 className="size-4" aria-hidden="true" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium text-foreground">
              {workspace.name}
            </span>
            <span className="block truncate text-xs text-muted-foreground">
              {workspace.slug}
            </span>
          </span>
          <ChevronsUpDown className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-[15.5rem]">
        <DropdownMenuLabel>Workspaces</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {workspaces.map((item) => (
          <DropdownMenuItem
            key={item.workspace_id}
            onSelect={() => selectWorkspace(item.workspace_id)}
          >
            <span className="flex size-4 items-center justify-center">
              {item.workspace_id === workspace.workspace_id ? (
                <Check className="size-4 text-primary" aria-hidden="true" />
              ) : null}
            </span>
            <span className="min-w-0 flex-1 truncate">{item.name}</span>
            <span className="text-xs text-muted-foreground">{item.slug}</span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function ProjectSwitcher() {
  const { projects, project, selectProject, isProjectsLoading } = useWorkspace();
  const label = project ? project.name : "All projects";
  return (
    <div className="space-y-1.5">
      <label
        htmlFor="project-context-trigger"
        className="text-[0.68rem] font-semibold uppercase tracking-wider text-muted-foreground"
      >
        Project context
      </label>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            id="project-context-trigger"
            type="button"
            className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label={`Switch project context. Current: ${label}`}
            disabled={isProjectsLoading}
          >
            <FolderKanban className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
            <span className="min-w-0 flex-1 truncate">{label}</span>
            <ChevronsUpDown className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-[15.5rem]">
          <DropdownMenuLabel>Project context</DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={() => selectProject(null)}>
            <span className="flex size-4 items-center justify-center">
              {!project ? <Check className="size-4 text-primary" aria-hidden="true" /> : null}
            </span>
            All projects
          </DropdownMenuItem>
          {projects.map((item) => (
            <DropdownMenuItem
              key={item.project_id}
              onSelect={() => selectProject(item.project_id)}
            >
              <span className="flex size-4 items-center justify-center">
                {item.project_id === project?.project_id ? (
                  <Check className="size-4 text-primary" aria-hidden="true" />
                ) : null}
              </span>
              <span className="min-w-0 flex-1 truncate">{item.name}</span>
              <span className="font-mono text-[0.65rem] text-muted-foreground">
                {item.key}
              </span>
            </DropdownMenuItem>
          ))}
          {projects.length === 0 && !isProjectsLoading ? (
            <p className="px-2 py-2 text-xs text-muted-foreground">
              No projects in this workspace.
            </p>
          ) : null}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

function NavigationLinks({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav aria-label="Primary" className="mt-6 flex-1 space-y-1">
      {primaryNavigation.map((item) => {
        const Icon = item.icon;
        return (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={onNavigate}
            className={({ isActive }) =>
              [
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                isActive
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-surface-muted hover:text-foreground",
              ].join(" ")
            }
          >
            <Icon className="size-4 shrink-0" aria-hidden="true" />
            {item.label}
          </NavLink>
        );
      })}
    </nav>
  );
}

export function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <div className="flex h-full flex-col bg-surface px-3 py-4">
      <NavLink
        to="/"
        onClick={onNavigate}
        className="mx-1 flex items-center gap-2 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        aria-label="EventFlow dashboard"
      >
        <span className="flex size-9 items-center justify-center rounded-lg bg-primary text-sm font-bold text-primary-foreground">
          EF
        </span>
        <span>
          <span className="block text-sm font-semibold tracking-tight text-foreground">
            EventFlow
          </span>
          <span className="block text-[0.68rem] uppercase tracking-wider text-muted-foreground">
            Work management
          </span>
        </span>
      </NavLink>
      <div className="mt-5">
        <WorkspaceSwitcher />
      </div>
      <NavigationLinks onNavigate={onNavigate} />
      <div className="mt-4 border-t border-border pt-4">
        <ProjectSwitcher />
      </div>
      <NavLink
        to="/settings"
        onClick={onNavigate}
        className={({ isActive }) =>
          [
            "mt-2 flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            isActive
              ? "bg-primary/10 text-primary"
              : "text-muted-foreground hover:bg-surface-muted hover:text-foreground",
          ].join(" ")
        }
      >
        <Settings className="size-4" aria-hidden="true" />
        Settings
      </NavLink>
      <p className="mt-4 px-3 text-[0.65rem] text-muted-foreground">
        EventFlow web client · v0.1
      </p>
    </div>
  );
}

export function DesktopSidebar() {
  return (
    <aside className="fixed inset-y-0 left-0 z-30 hidden w-[var(--sidebar-width)] border-r border-border lg:block">
      <SidebarContent />
    </aside>
  );
}

export function MobileNavigation({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="!bottom-0 !left-0 !top-0 !h-dvh !w-[18rem] !max-w-[18rem] !translate-x-0 !translate-y-0 !rounded-none !border-y-0 !border-l-0 !p-0">
        <DialogTitle className="sr-only">Navigation</DialogTitle>
        <DialogDescription className="sr-only">
          Workspace navigation and project context.
        </DialogDescription>
        <SidebarContent onNavigate={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}
