// SPDX-License-Identifier: MIT
// Copyright (c) 2026 John-IDK

export type Role = "admin" | "reviewer" | "reader";

export interface User {
  id: number;
  username: string;
  role: Role;
}

export interface Source {
  id: number;
  kind: "file" | "folder" | "website";
  uri: string;
  title?: string;
  allowed_domains: string[];
  created_at: string;
  branch?: string;
}

export interface Branch { id: number; name: string; is_canonical: number | boolean; protected: number | boolean; member_role?: Role; }
export interface Publication { id: string; concept_id: string; title: string; branch: string; candidate_branch: string; state: string; commit_hash?: string; error?: string; created_at: string; }
export interface EntityHub { id: number; name: string; slug: string; aliases: string[]; pagerank: number; concept_count: number; concepts?: Array<Pick<Concept, "id" | "title" | "type" | "description" | "path" | "pagerank">>; }

export interface Job {
  id: number;
  source_id: number;
  status: string;
  attempts: number;
  error?: string;
  result_json?: string;
  created_at: string;
  branch?: string;
}

export interface Quality {
  coverage: number;
  minimum_confidence: number;
  average_confidence: number;
  publishable: boolean;
  reasons: string[];
}

export interface Concept {
  id: string;
  type: string;
  title: string;
  description: string;
  body?: string;
  status: string;
  tags: string[];
  path?: string;
  quality: Quality;
  score?: number;
  channels?: string[];
  endorsements: number;
  usage_count: number;
  pagerank?: number;
  maturity?: number;
  legacy?: number;
}

function cookie(name: string): string {
  const value = document.cookie.split("; ").find((item) => item.startsWith(`${name}=`));
  return value ? decodeURIComponent(value.split("=").slice(1).join("=")) : "";
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const csrf = cookie("ckb_csrf");
  if (csrf && init.method && !["GET", "HEAD"].includes(init.method)) headers.set("X-CSRF-Token", csrf);
  const response = await fetch(`/api/v1${path}`, { ...init, headers, credentials: "include" });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const data = await response.json();
      message = data.detail || message;
    } catch {
      // Keep the HTTP status when the response is not JSON.
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export const api = {
  me: () => request<User>("/auth/me"),
  login: (username: string, password: string) => request<{ user: User }>("/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),
  logout: () => request<{ ok: boolean }>("/auth/logout", { method: "POST" }),
  health: () => request<Record<string, unknown>>("/health"),
  sources: () => request<Source[]>("/sources"),
  addSource: (payload: Pick<Source, "kind" | "uri" | "allowed_domains"> & { title?: string; branch?: string }) => request<{ id: number }>("/sources", { method: "POST", body: JSON.stringify(payload) }),
  ingest: (sourceId: number) => request<{ job_id: number }>(`/sources/${sourceId}/ingest`, { method: "POST" }),
  jobs: () => request<Job[]>("/jobs"),
  runJob: (jobId: number) => request<Record<string, unknown>>(`/jobs/${jobId}/run`, { method: "POST" }),
  cancelJob: (jobId: number) => request<Record<string, unknown>>(`/jobs/${jobId}/cancel`, { method: "POST" }),
  retryJob: (jobId: number) => request<Record<string, unknown>>(`/jobs/${jobId}/retry`, { method: "POST" }),
  concepts: (status?: string, branch?: string) => { const params = new URLSearchParams(); if (status) params.set("status_filter", status); if (branch) params.set("branch", branch); return request<Concept[]>(`/concepts${params.size ? `?${params}` : ""}`); },
  concept: (id: string) => request<Concept & { claims: unknown[] }>(`/concepts/${id}`),
  review: (id: string, decision: "approve" | "reject", editedBody?: string) => request<Record<string, unknown>>(`/concepts/${id}/review`, { method: "POST", body: JSON.stringify({ decision, edited_body: editedBody }) }),
  endorse: (id: string) => request<{ endorsements: number }>(`/concepts/${id}/endorse`, { method: "POST" }),
  removeEndorsement: (id: string) => request<{ endorsements: number }>(`/concepts/${id}/endorse`, { method: "DELETE" }),
  usage: (id: string) => request<{ usage_count: number }>(`/concepts/${id}/usage`, { method: "POST" }),
  reviseClaim: (conceptId: string, claimId: number, text: string, locator: string, excerpt: string) => request<Record<string, unknown>>(`/concepts/${conceptId}/claims/${claimId}`, { method: "PATCH", body: JSON.stringify({ text, locator, excerpt }) }),
  search: (query: string, branch?: string) => request<{ semantic_available: boolean; results: Concept[] }>("/search", { method: "POST", body: JSON.stringify({ query, branch }) }),
  feedback: (query: string, details: string, conceptId?: string) => request<{ id: number }>("/feedback", { method: "POST", body: JSON.stringify({ query, details, concept_id: conceptId }) }),
  feedbackList: () => request<Array<{ id: number; query: string; details: string; status: string; created_at: string }>>("/feedback"),
  resolveFeedback: (id: number, status: "open" | "resolved") => request<Record<string, unknown>>(`/feedback/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }),
  users: () => request<Array<User & { active: number }>>("/users"),
  addUser: (username: string, password: string, role: Role) => request<User>("/users", { method: "POST", body: JSON.stringify({ username, password, role }) }),
  branches: () => request<Branch[]>("/branches"),
  addBranch: (name: string) => request<Branch>("/branches", { method: "POST", body: JSON.stringify({ name }) }),
  branchMembers: (id: number) => request<Array<User & { role: Role }>>(`/branches/${id}/members`),
  setBranchMember: (branchId: number, userId: number, role: Role) => request<Record<string, unknown>>(`/branches/${branchId}/members`, { method: "POST", body: JSON.stringify({ user_id: userId, role }) }),
  publications: () => request<Publication[]>("/publications"),
  mergePublication: (id: string) => request<Record<string, unknown>>(`/publications/${id}/merge`, { method: "POST" }),
  entities: (branch?: string) => request<EntityHub[]>(`/entities${branch ? `?branch=${encodeURIComponent(branch)}` : ""}`),
  entity: (id: number, branch?: string) => request<EntityHub>(`/entities/${id}${branch ? `?branch=${encodeURIComponent(branch)}` : ""}`),
  secretStatus: () => request<Record<string, unknown>>("/secrets/status"),
  setLmSecret: (value: string) => request<{ configured: boolean }>("/secrets/lm-studio", { method: "PUT", body: JSON.stringify({ value }) }),
  deleteLmSecret: () => request<{ deleted: boolean }>("/secrets/lm-studio", { method: "DELETE" }),
  setGitSecret: (username: string, token: string) => request<{ configured: boolean }>("/secrets/git", { method: "PUT", body: JSON.stringify({ username, token }) }),
  deleteGitSecret: () => request<{ deleted: boolean }>("/secrets/git", { method: "DELETE" }),
  gitStatus: () => request<{ branch: string; head: string; changes: string; remotes: string }>("/git/status"),
  gitPull: () => request<{ branch: string; head: string; changes: string; remotes: string }>("/git/pull", { method: "POST" }),
  gitPush: () => request<{ ok: boolean }>("/git/push", { method: "POST" })
};
