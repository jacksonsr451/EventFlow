import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

const workspaceId = "00000000-0000-4000-8000-000000000001";
const projectId = "00000000-0000-4000-8000-000000000002";
const consultationId = "00000000-0000-4000-8000-000000000003";
const workItemId = "00000000-0000-4000-8000-000000000004";
const now = "2026-01-01T12:00:00Z";

export const handlers = [
  http.get("http://localhost/v1/auth/session", () =>
    HttpResponse.json({
      user_id: "00000000-0000-4000-8000-000000000010",
      session_id: "00000000-0000-4000-8000-000000000011",
      expires_at: "2026-01-01T20:00:00Z",
      csrf_token: "test-csrf-token",
    }),
  ),
  http.get("http://localhost/v1/workspaces", () =>
    HttpResponse.json([
      {
        workspace_id: workspaceId,
        name: "Northstar workspace",
        slug: "northstar",
        created_at: now,
        updated_at: now,
      },
    ]),
  ),
  http.get("http://localhost/v1/workspaces/:workspaceId/projects", () =>
    HttpResponse.json([
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
  ),
  http.get("http://localhost/v1/workspaces/:workspaceId/consultations", () =>
    HttpResponse.json({
      items: [
        {
          consultation_id: consultationId,
          workspace_id: workspaceId,
          project_id: projectId,
          author_id: "00000000-0000-4000-8000-000000000010",
          assignee_id: null,
          origin: "web",
          title: "Design intake flow",
          description: "Improve incoming request handling.",
          category: "feature",
          status: "open",
          priority: "high",
          business_impact: "moderate",
          business_urgency: "normal",
          priority_override_reason: null,
          editor_context: null,
          external_references: [],
          active_proposal_id: null,
          triage_custom_fields: null,
          triage_template_id: null,
          triage_template_version: null,
          triage_template_schema_version: null,
          triage_template_snapshot: null,
          created_at: now,
          updated_at: now,
        },
      ],
      page_info: { next_cursor: null, has_more: false },
    }),
  ),
  http.get("http://localhost/v1/workspaces/:workspaceId/work-items", () =>
    HttpResponse.json({
      items: [
        {
          work_item_id: workItemId,
          workspace_id: workspaceId,
          project_id: projectId,
          origin_proposal_id: "00000000-0000-4000-8000-000000000005",
          origin_proposal_version: 1,
          origin_approval_id: "00000000-0000-4000-8000-000000000006",
          title: "Implement intake flow",
          description: "Build the request intake path.",
          acceptance_criteria: ["Requests can be submitted"],
          category: "feature",
          priority: "high",
          status: "in_progress",
          assignee_id: null,
          external_issue_links: [],
          created_at: now,
          updated_at: now,
        },
      ],
      page_info: { next_cursor: null, has_more: false },
    }),
  ),
  http.get("http://localhost/v1/workspaces/:workspaceId/boards", () =>
    HttpResponse.json([
      {
        board_id: "00000000-0000-4000-8000-000000000007",
        workspace_id: workspaceId,
        project_id: projectId,
        name: "Delivery flow",
        columns: ["backlog", "doing", "done"],
        version: 1,
        archived_at: null,
        created_at: now,
        updated_at: now,
      },
    ]),
  ),
  http.get("http://localhost/v1/workspaces/:workspaceId/notifications", () =>
    HttpResponse.json({
      items: [],
      unread_count: 0,
      page_info: { next_cursor: null, has_more: false },
    }),
  ),
];

export const server = setupServer(...handlers);
