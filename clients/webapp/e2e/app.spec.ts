import { expect, test, type Page, type Route } from "@playwright/test";

const workspaceId = "00000000-0000-4000-8000-000000000001";
const projectId = "00000000-0000-4000-8000-000000000002";
const now = "2026-01-01T12:00:00Z";

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function mockAuthenticatedApi(page: Page) {
  await page.route("**/v1/auth/session", (route) =>
    fulfillJson(route, {
      user_id: "00000000-0000-4000-8000-000000000010",
      session_id: "00000000-0000-4000-8000-000000000011",
      expires_at: "2026-01-01T20:00:00Z",
      csrf_token: "browser-test-csrf",
    }),
  );
  await page.route("**/v1/workspaces", (route) =>
    fulfillJson(route, [
      {
        workspace_id: workspaceId,
        name: "Northstar workspace",
        slug: "northstar",
        created_at: now,
        updated_at: now,
      },
    ]),
  );
  await page.route("**/v1/workspaces/*/projects", (route) =>
    fulfillJson(route, [
      {
        project_id: projectId,
        workspace_id: workspaceId,
        key: "WEB",
        name: "Web platform",
        description: "Customer-facing platform",
        created_at: now,
        updated_at: now,
      },
    ]),
  );
  await page.route("**/v1/workspaces/*/consultations**", (route) =>
    fulfillJson(route, {
      items: [],
      page_info: { next_cursor: null, has_more: false },
    }),
  );
  await page.route("**/v1/workspaces/*/work-items**", (route) =>
    fulfillJson(route, {
      items: [],
      page_info: { next_cursor: null, has_more: false },
    }),
  );
  await page.route("**/v1/workspaces/*/boards**", (route) => fulfillJson(route, []));
  await page.route("**/v1/workspaces/*/notifications**", (route) =>
    fulfillJson(route, {
      items: [],
      unread_count: 0,
      page_info: { next_cursor: null, has_more: false },
    }),
  );
}

test("authenticated dashboard renders a truthful empty state", async ({ page }) => {
  await mockAuthenticatedApi(page);
  await page.goto("/");

  await expect(
    page.getByRole("heading", { name: "Workspace overview" }),
  ).toBeVisible();
  await expect(page.getByText("No consultations yet")).toBeVisible();
  await expect(page.getByText("No work items yet")).toBeVisible();
  await expect(page.getByText("No boards in this context")).toBeVisible();
});

test("mobile navigation exposes the primary routes", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockAuthenticatedApi(page);
  await page.goto("/");

  await page.getByRole("button", { name: "Open navigation" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("link", { name: "Consultations" })).toBeVisible();
  await dialog.getByRole("link", { name: "Consultations" }).click();
  await expect(page).toHaveURL(/\/consultations$/);
  await expect(
    page.getByRole("heading", { name: "Consultations", exact: true }),
  ).toBeVisible();
});

test("unauthenticated users are shown the sign-in boundary", async ({ page }) => {
  await page.route("**/v1/auth/session", (route) =>
    fulfillJson(route, { detail: "No session" }, 401),
  );
  await page.goto("/login");

  await expect(
    page.getByRole("heading", { name: "Sign in to your workspace" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: /continue to sign in/i }),
  ).toBeEnabled();
});
