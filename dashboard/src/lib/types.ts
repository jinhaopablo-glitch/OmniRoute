export type Json = Record<string, unknown>;

export interface Proposal {
  id: string;
  action_type: string;
  title: string;
  summary: string;
  payload: Json;
  payload_hash: string;
  risk_level: "low" | "medium" | "high";
  estimated_cost_eur: string;
  proposed_by_agent: string;
  status: string;
  supervisor_verdict: string | null;
  supervisor_notes: string | null;
  decided_at: string | null;
  decision_note: string | null;
  execution_result: Json | null;
  expires_at: string;
  created_at: string;
}

export interface ContentItem {
  id: string;
  kind: string;
  platform: string | null;
  title: string;
  body: Json;
  status: string;
  parent_id: string | null;
  media_paths: string[];
  scheduled_for: string | null;
  published_url: string | null;
  created_by: string;
  review_notes: string | null;
  created_at: string;
}

export interface Task {
  id: string;
  title: string;
  description: string;
  status: string;
  priority: number;
  assigned_agent: string | null;
  created_by_type: string;
  created_by: string;
  due_date: string | null;
  created_at: string;
}

export interface Job {
  id: string;
  agent_id: string;
  kind: string;
  status: string;
  attempts: number;
  last_error: string | null;
  run_after: string;
  created_at: string;
  finished_at: string | null;
}

export interface AgentRun {
  id: string;
  agent_id: string;
  model: string;
  cost_usd: string;
  status: string;
  summary: string;
  input_tokens: number;
  output_tokens: number;
  web_searches: number;
  created_at: string;
}

export interface Agent {
  id: string;
  name: string;
  description: string;
  model: string;
  effort: string;
  enabled: boolean;
}

export interface AuditRow {
  id: number;
  at: string;
  actor_type: string;
  actor_id: string;
  action: string;
  entity_type: string;
  entity_id: string;
  details: Json;
}

export interface Metric {
  day: string;
  source: string;
  metrics: Json;
}

export interface Report {
  id: string;
  day: string;
  title: string;
  body_md: string;
  created_at: string;
}
