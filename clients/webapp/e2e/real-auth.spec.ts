import { expect, test } from "@playwright/test";

test.skip(
  process.env.EVENTFLOW_REAL_E2E !== "1",
  "Set EVENTFLOW_REAL_E2E=1 to run against the local BFF and Keycloak.",
);

test("completes real OIDC login, persists the session, and logs out", async ({
  page,
  context,
}) => {
  const username = process.env.EVENTFLOW_TEST_KEYCLOAK_USERNAME;
  const password = process.env.EVENTFLOW_TEST_KEYCLOAK_PASSWORD;

  expect(username).toBeTruthy();
  expect(password).toBeTruthy();

  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Sign in to your workspace" }),
  ).toBeVisible();

  await page.getByRole("button", { name: /continue to sign in/i }).click();
  await page.locator('input[name="username"]').fill(username!);
  await page.locator('input[name="password"]').fill(password!);
  await page.locator('button[type="submit"]').click();

  await expect(page).toHaveURL(/\/$/, { timeout: 30_000 });
  await expect(page.getByText("No accessible workspaces")).toBeVisible({
    timeout: 30_000,
  });

  const sessionCookie = (await context.cookies()).find((cookie) =>
    cookie.name.includes("eventflow_session"),
  );
  expect(sessionCookie?.httpOnly).toBe(true);
  expect(sessionCookie?.sameSite).toBe("Lax");
  expect(sessionCookie?.value).toBeTruthy();

  await page.reload();
  await expect(page.getByText("No accessible workspaces")).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(
    page.getByRole("heading", { name: "Sign in to your workspace" }),
  ).toBeVisible();
});
