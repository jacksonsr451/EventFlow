import type {
  ConsultationStatus,
  Priority,
  ProposalStatus,
  TriageCategory,
  WorkItemStatus,
} from "@eventflow/domain";

export interface AuthSessionListItem {
  session_id: string;
  client_id: string;
  source: string;
  created_at: string;
  last_seen_at: string;
  expires_at: string;
  current: boolean;
}

export interface SessionResponse {
  user_id: string;
  session_id: string;
  expires_at: string;
  csrf_token: string;
}

export interface ConsultationFilters {
  status?: ConsultationStatus;
  category?: TriageCategory;
  priority?: Priority;
  limit?: number;
  cursor?: string | null;
  sort?: string;
}

export interface ProposalFilters {
  status?: ProposalStatus;
  limit?: number;
  cursor?: string | null;
  sort?: string;
}

export interface WorkItemFilters {
  status?: WorkItemStatus;
  category?: TriageCategory;
  priority?: Priority;
  assignee_id?: string;
  limit?: number;
  cursor?: string | null;
  sort?: string;
}

export interface BoardCardFilters {
  column_id?: string;
  limit?: number;
  cursor?: string | null;
  sort?: string;
}

export interface NotificationFilters {
  unread_only?: boolean;
  limit?: number;
  cursor?: string | null;
  sort?: string;
}

export interface TriageTemplateFilters {
  category?: TriageCategory;
  status?: "active" | "deprecated" | "archived";
  sort?: string;
  limit?: number;
  cursor?: string | null;
}
