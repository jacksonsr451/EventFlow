export type { components, operations, paths } from "./work-management.schema";

import type { components } from "./work-management.schema";

type Schemas = components["schemas"];

export type Workspace = Schemas["Workspace"];
export type Project = Schemas["Project"];
export type Consultation = Schemas["Consultation"];
export type ConsultationPage = Schemas["ConsultationPage"];
export type ConsultationStatus = Schemas["ConsultationStatus"];
export type Proposal = Schemas["Proposal"];
export type ProposalPage = Schemas["ProposalPage"];
export type ProposalStatus = Schemas["ProposalStatus"];
export type WorkItem = Schemas["WorkItem"];
export type WorkItemPage = Schemas["WorkItemPage"];
export type WorkItemStatus = Schemas["WorkItemStatus"];
export type Board = Schemas["Board"];
export type BoardColumn = Schemas["BoardColumn"];
export type BoardCard = Schemas["BoardCard"];
export type BoardCardPage = Schemas["BoardCardPage"];
export type WorkspaceMember = Schemas["WorkspaceMember"];
export type Notification = Schemas["Notification"];
export type NotificationPage = Schemas["NotificationPage"];
export type ProjectRepository = Schemas["ProjectRepository"];
export type ProjectTriageConfiguration = Schemas["ProjectTriageConfiguration"];
export type ProjectTriageTemplate = Schemas["ProjectTriageTemplate"];
export type ProjectTriageTemplateVersion = Schemas["ProjectTriageTemplateVersion"];
export type ProjectTriageTemplatePage = Schemas["ProjectTriageTemplatePage"];
export type PageInfo = Schemas["PageInfo"];
export type Problem = Schemas["ErrorResponse"];
export type Role = Schemas["Role"];
export type TriageCategory = Schemas["TriageCategory"];
export type Priority = Schemas["Priority"];
export type Origin = Schemas["Origin"];
export type MembershipState = Schemas["MembershipState"];
