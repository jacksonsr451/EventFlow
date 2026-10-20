import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { describe, expect, it, vi } from "vitest";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
  EmptyState,
  ErrorState,
  FormField,
  IconButton,
  Input,
  PriorityBadge,
  StatusBadge,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "../src";

describe("design system primitives", () => {
  it("renders accessible buttons and icon buttons", async () => {
    const onClick = vi.fn();
    render(
      <div>
        <Button onClick={onClick}>Create consultation</Button>
        <IconButton label="Open settings">
          <span aria-hidden="true">*</span>
        </IconButton>
      </div>,
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Create consultation" }),
    );
    expect(onClick).toHaveBeenCalledOnce();
    expect(
      screen.getByRole("button", { name: "Open settings" }),
    ).toBeInTheDocument();
  });

  it("associates a form label and hints with an input", () => {
    render(
      <FormField
        label="Priority"
        htmlFor="priority"
        description="Choose a priority"
      >
        <Input id="priority" aria-describedby="priority-help" />
      </FormField>,
    );
    expect(screen.getByLabelText("Priority")).toHaveAttribute(
      "id",
      "priority",
    );
    expect(screen.getByText("Choose a priority")).toHaveAttribute(
      "id",
      "priority-help",
    );
  });

  it("renders status through text as well as color", () => {
    render(
      <div>
        <StatusBadge status="in_review" />
        <PriorityBadge priority="critical" />
      </div>,
    );
    expect(screen.getByText("In review")).toBeInTheDocument();
    expect(screen.getByText("Critical")).toBeInTheDocument();
  });

  it("shows empty and error states with recovery", async () => {
    const onRetry = vi.fn();
    render(
      <div>
        <EmptyState
          title="No consultations"
          description="New requests will appear here."
        />
        <ErrorState
          status={500}
          title="Service unavailable"
          onRetry={onRetry}
        />
      </div>,
    );
    expect(screen.getByRole("heading", { name: "No consultations" })).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("closes a dialog with Escape and restores focus", async () => {
    const user = userEvent.setup();
    render(
      <Dialog>
        <DialogTrigger asChild>
          <Button>Open details</Button>
        </DialogTrigger>
        <DialogContent>
          <DialogTitle>Consultation details</DialogTitle>
          <DialogDescription>Read-only detail dialog.</DialogDescription>
        </DialogContent>
      </Dialog>,
    );
    const trigger = screen.getByRole("button", { name: "Open details" });
    await user.click(trigger);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("supports keyboard tab navigation", async () => {
    const user = userEvent.setup();
    render(
      <Tabs defaultValue="overview">
        <TabsList aria-label="Settings sections">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="members">Members</TabsTrigger>
        </TabsList>
        <TabsContent value="overview">Overview content</TabsContent>
        <TabsContent value="members">Members content</TabsContent>
      </Tabs>,
    );
    const overview = screen.getByRole("tab", { name: "Overview" });
    await user.click(overview);
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Members" })).toHaveFocus();
    expect(screen.getByText("Members content")).toBeVisible();
  });

  it("has no structural axe violations in a representative form", async () => {
    const { container } = render(
      <main>
        <h1>Consultation filters</h1>
        <FormField label="Status" htmlFor="status">
          <Input id="status" />
        </FormField>
        <Button>Apply filters</Button>
        <StatusBadge status="open" />
      </main>,
    );
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations).toEqual([]);
    const heading = within(container).getByRole("heading", {
      name: "Consultation filters",
    });
    expect(heading).toBeVisible();
  });
});
