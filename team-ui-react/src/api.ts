import type {
  ReviewItem,
  ReviewQueueResponse,
  ReviewDecisionResponse,
  ReviewStats,
  EditHistoryEntry,
} from "./types";

const API_BASE = "/api";

let token: string | null = localStorage.getItem("acq_token");

export function setToken(t: string | null) {
  token = t;
  if (t) {
    localStorage.setItem("acq_token", t);
  } else {
    localStorage.removeItem("acq_token");
  }
}

export function getToken(): string | null {
  return token;
}

class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

let onUnauthorized: (() => void) | null = null;

export function setOnUnauthorized(callback: () => void) {
  onUnauthorized = callback;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  const resp = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!resp.ok) {
    if (resp.status === 401 && onUnauthorized) {
      onUnauthorized();
    }
    const body = await resp.json().catch(() => ({}));
    throw new ApiError(resp.status, body.detail || `HTTP ${resp.status}`);
  }
  return resp.json();
}

export const api = {
  login: (username: string, password: string) =>
    request<{ token: string; username: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),

  reviewQueue: (limit = 20, offset = 0) =>
    request<ReviewQueueResponse>(
      `/review/queue?limit=${limit}&offset=${offset}`,
    ),

  approve: (id: string) =>
    request<ReviewDecisionResponse>(`/review/${id}/approve`, {
      method: "POST",
    }),

  reject: (id: string) =>
    request<ReviewDecisionResponse>(`/review/${id}/reject`, {
      method: "POST",
    }),

  reviewStats: () => request<ReviewStats>("/review/stats"),

  editQuestion: (id: string, body: string) =>
    request<ReviewItem>(`/questions/${id}`, {
      method: "PUT",
      body: JSON.stringify({ body }),
    }),

  editAnswer: (id: string, body: string) =>
    request<ReviewItem>(`/answers/${id}`, {
      method: "PUT",
      body: JSON.stringify({ body }),
    }),

  pinAnswer: (questionId: string, answerId: string) =>
    request<void>(`/questions/${questionId}/pin`, {
      method: "PUT",
      body: JSON.stringify({ answer_id: answerId }),
    }),

  unpinAnswer: (questionId: string) =>
    request<void>(`/questions/${questionId}/pin`, {
      method: "DELETE",
    }),

  getHistory: (type: "question" | "answer", id: string) => {
    const base = type === "question" ? "questions" : "answers";
    return request<EditHistoryEntry[]>(`/${base}/${id}/history`);
  },

  mergeTags: (sourceId: string, targetId: string) =>
    request<void>("/tags/merge", {
      method: "POST",
      body: JSON.stringify({ source_id: sourceId, target_id: targetId }),
    }),
};

export { ApiError };
