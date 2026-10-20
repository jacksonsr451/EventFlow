import {
  Bell,
  BellOff,
  Check,
  LogOut,
  Menu,
  Monitor,
  Moon,
  Settings,
  Sun,
} from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import {
  Alert,
  Avatar,
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  EmptyState,
  ErrorState,
  IconButton,
  Spinner,
  useToast,
} from "@eventflow/ui";
import { useAuth } from "../lib/auth";
import { presentError } from "../lib/errors";
import { formatRelativeTime, truncateId } from "../lib/format";
import {
  useMarkNotification,
  useNotifications,
  useUnreadNotificationCount,
} from "../lib/queries";
import { useTheme, type ThemePreference } from "../lib/theme";
import { useWorkspace } from "../lib/workspace";
import { flattenPages } from "../lib/pagination";

const themeOptions: Array<{
  value: ThemePreference;
  label: string;
  icon: typeof Sun;
}> = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
];

function ThemeMenu() {
  const { theme, setTheme } = useTheme();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <IconButton label="Change theme" variant="ghost">
          <Sun className="size-4 dark:hidden" aria-hidden="true" />
          <Moon className="hidden size-4 dark:block" aria-hidden="true" />
        </IconButton>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>Appearance</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {themeOptions.map((option) => {
          const Icon = option.icon;
          return (
            <DropdownMenuItem
              key={option.value}
              onSelect={() => setTheme(option.value)}
            >
              <Icon className="size-4" aria-hidden="true" />
              <span className="flex-1">{option.label}</span>
              {theme === option.value ? (
                <Check className="size-4 text-primary" aria-hidden="true" />
              ) : null}
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function UserMenu() {
  const { session, logout } = useAuth();
  const { showToast } = useToast();
  const [isSigningOut, setIsSigningOut] = useState(false);
  const userId = session?.user_id ?? "unknown";

  async function handleLogout() {
    setIsSigningOut(true);
    try {
      await logout();
    } catch (error) {
      const presented = presentError(error);
      showToast({
        tone: "destructive",
        title: "Could not sign out",
        description: presented.description,
      });
      setIsSigningOut(false);
    }
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="flex items-center gap-2 rounded-md p-1 pr-2 transition-colors hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label="Open account menu"
        >
          <Avatar name="EventFlow user" className="size-7" />
          <span className="hidden max-w-28 truncate font-mono text-xs text-muted-foreground sm:block">
            {truncateId(userId, 10)}
          </span>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel>
          Signed in
          <span className="mt-0.5 block truncate font-mono text-[0.65rem] font-normal">
            {userId}
          </span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link to="/settings">
            <Settings className="size-4" aria-hidden="true" />
            Settings
          </Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          destructive
          disabled={isSigningOut}
          onSelect={(event) => {
            event.preventDefault();
            void handleLogout();
          }}
        >
          <LogOut className="size-4" aria-hidden="true" />
          {isSigningOut ? "Signing out..." : "Sign out"}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function NotificationsButton({ workspaceId }: { workspaceId: string }) {
  const [open, setOpen] = useState(false);
  const countQuery = useUnreadNotificationCount(workspaceId);
  const notificationsQuery = useNotifications(workspaceId, {}, 25);
  const markMutation = useMarkNotification(workspaceId);
  const notifications = flattenPages(notificationsQuery.data?.pages);
  const unreadCount = countQuery.data?.unread_count ?? 0;
  const label =
    unreadCount > 0
      ? `Notifications, ${unreadCount} unread`
      : "Notifications, no unread items";

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <button
          type="button"
          className="relative inline-flex size-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-surface-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={label}
        >
          <Bell className="size-4" aria-hidden="true" />
          {unreadCount > 0 ? (
            <span className="absolute -right-0.5 -top-0.5 flex min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[0.6rem] font-semibold leading-4 text-destructive-foreground">
              {unreadCount > 9 ? "9+" : unreadCount}
            </span>
          ) : null}
        </button>
      </DialogTrigger>
      <DialogContent className="!bottom-0 !left-auto !right-0 !top-0 !h-dvh !w-full !max-w-md !translate-x-0 !translate-y-0 !rounded-none !border-y-0 !border-r-0 !p-0">
        <div className="border-b border-border px-5 py-4 pr-12">
          <DialogTitle>Notifications</DialogTitle>
          <DialogDescription>
            {unreadCount > 0
              ? `${unreadCount} unread notification${unreadCount === 1 ? "" : "s"}`
              : "You are caught up."}
          </DialogDescription>
        </div>
        <div className="h-[calc(100dvh-5.5rem)] overflow-y-auto p-3">
          {notificationsQuery.isPending ? (
            <div className="flex justify-center py-10">
              <Spinner label="Loading notifications" />
            </div>
          ) : notificationsQuery.isError ? (
            <ErrorState
              status={undefined}
              title={presentError(notificationsQuery.error).title}
              description={presentError(notificationsQuery.error).description}
              onRetry={() => void notificationsQuery.refetch()}
              className="border-0"
            />
          ) : notifications.length === 0 ? (
            <EmptyState
              icon={BellOff}
              title="No notifications"
              description="Updates about consultations, proposals, and work items will appear here."
              className="border-0"
            />
          ) : (
            <ul className="space-y-2">
              {notifications.map((notification) => {
                const isUnread = notification.read_at === null;
                const isUpdating =
                  markMutation.isPending &&
                  markMutation.variables?.notificationId ===
                    notification.notification_id;
                return (
                  <li
                    key={notification.notification_id}
                    className={
                      isUnread
                        ? "rounded-lg border border-primary/25 bg-primary/5 p-3"
                        : "rounded-lg border border-border p-3"
                    }
                  >
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-sm font-medium text-foreground">
                        {notification.title}
                      </p>
                      {isUnread ? <Badge tone="accent">Unread</Badge> : null}
                    </div>
                    <p className="mt-1 text-sm text-muted-foreground">
                      {notification.body}
                    </p>
                    <div className="mt-2 flex items-center justify-between gap-2">
                      <span className="text-xs text-muted-foreground">
                        {formatRelativeTime(notification.created_at)}
                      </span>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={isUpdating}
                        onClick={() =>
                          markMutation.mutate({
                            notificationId: notification.notification_id,
                            read: isUnread,
                          })
                        }
                      >
                        {isUpdating
                          ? "Updating..."
                          : isUnread
                            ? "Mark as read"
                            : "Mark as unread"}
                      </Button>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
          {notificationsQuery.hasNextPage ? (
            <div className="mt-3 flex justify-center">
              <Button
                variant="outline"
                size="sm"
                disabled={notificationsQuery.isFetchingNextPage}
                onClick={() => void notificationsQuery.fetchNextPage()}
              >
                {notificationsQuery.isFetchingNextPage
                  ? "Loading..."
                  : "Load more"}
              </Button>
            </div>
          ) : null}
          {markMutation.isError ? (
            <Alert tone="destructive" className="mt-3">
              {presentError(markMutation.error).description}
            </Alert>
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function AppHeader({ onOpenMenu }: { onOpenMenu: () => void }) {
  const { workspace, project, workspaceId } = useWorkspace();
  return (
    <header className="sticky top-0 z-30 flex h-[var(--header-height)] items-center gap-3 border-b border-border bg-background/90 px-4 backdrop-blur sm:px-6">
      <span className="lg:hidden">
        <IconButton label="Open navigation" variant="ghost" onClick={onOpenMenu}>
          <Menu className="size-5" aria-hidden="true" />
        </IconButton>
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-foreground">
          {workspace?.name ?? "EventFlow"}
        </p>
        <p className="truncate text-xs text-muted-foreground">
          {project ? `${project.key} · ${project.name}` : "All projects"}
        </p>
      </div>
      <div className="flex items-center gap-1">
        {workspaceId ? <NotificationsButton workspaceId={workspaceId} /> : null}
        <ThemeMenu />
        <span className="mx-1 hidden h-6 w-px bg-border sm:block" aria-hidden="true" />
        <UserMenu />
      </div>
    </header>
  );
}
