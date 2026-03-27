import type { ReviewQueueResponse, ReviewStats } from './types';

const API_BASE = import.meta.env.VITE_API_BASE || '';

function getToken(): string | null {
  return localStorage.getItem('acq_token');
}

export function setToken(t: string | null) {
  if (t) localStorage.setItem('acq_token', t);
  else localStorage.removeItem('acq_token');
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  if (options.body) headers['Content-Type'] = 'application/json';

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (res.status === 401) {
    setToken(null);
    window.location.href = '/login';
    throw new Error('Unauthorized');
  }
  if (!res.ok) {
    const err = new Error(`HTTP ${res.status}`) as Error & { status: number };
    err.status = res.status;
    throw err;
  }
  return res.json();
}

export const api = {
  login: (username: string, password: string) =>
    request<{ token: string; username: string }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),

  reviewQueue: (limit = 20, offset = 0) =>
    request<ReviewQueueResponse>(`/review/queue?limit=${limit}&offset=${offset}`),

  approve: (id: string) =>
    request<{ id: string; status: string }>(`/review/${id}/approve`, { method: 'POST' }),

  reject: (id: string) =>
    request<{ id: string; status: string }>(`/review/${id}/reject`, { method: 'POST' }),

  reviewStats: () =>
    request<ReviewStats>('/review/stats'),

  editQuestion: (id: string, body: string) =>
    request(`/questions/${id}`, { method: 'PUT', body: JSON.stringify({ body }) }),

  editAnswer: (id: string, body: string) =>
    request(`/answers/${id}`, { method: 'PUT', body: JSON.stringify({ body }) }),

  questionHistory: (id: string) =>
    request(`/questions/${id}/history`),

  answerHistory: (id: string) =>
    request(`/answers/${id}/history`),

  pinAnswer: (questionId: string, answerId: string) =>
    request(`/questions/${questionId}/pin`, { method: 'PUT', body: JSON.stringify({ answer_id: answerId }) }),

  unpinAnswer: (questionId: string) =>
    request(`/questions/${questionId}/pin`, { method: 'DELETE' }),

  mergeTags: (sourceId: string, targetId: string) =>
    request('/tags/merge', {
      method: 'POST',
      body: JSON.stringify({ source_tag_id: sourceId, target_tag_id: targetId }),
    }),
};
