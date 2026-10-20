import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";
import { App } from "./app";
import { queryClient } from "./lib/query-client";
import { server } from "./test/server";

describe("webapp routes", () => {
  beforeEach(() => {
    queryClient.clear();
    window.history.pushState({}, "", "/");
  });

  it("renders the authenticated shell with workspace data", async () => {
    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Workspace overview" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Northstar workspace").length).toBeGreaterThan(0);
    expect(await screen.findByText("Design intake flow")).toBeInTheDocument();
    expect(await screen.findByText("Implement intake flow")).toBeInTheDocument();
  });

  it("renders the sign-in boundary for an unauthenticated route", async () => {
    server.use(
      http.get(
        "http://localhost/v1/auth/session",
        () => HttpResponse.json({ detail: "No session" }, { status: 401 }),
      ),
    );
    window.history.pushState({}, "", "/login");
    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Sign in to your workspace" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /continue to sign in/i }),
    ).toBeEnabled();
  });
});
