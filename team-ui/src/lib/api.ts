import type { QuestionListResponse, QuestionThread, ReviewQueueResponse, ReviewStats, SearchResponse } from './types';

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
  listQuestions: (params: { status?: string; tag?: string; limit?: number; offset?: number } = {}) => {
    const qs = new URLSearchParams();
    if (params.status) qs.set('status', params.status);
    if (params.tag) qs.set('tag', params.tag);
    if (params.limit) qs.set('limit', String(params.limit));
    if (params.offset) qs.set('offset', String(params.offset));
    const query = qs.toString();
    return request<QuestionListResponse>(`/questions${query ? `?${query}` : ''}`);
  },

  searchQuestions: (q: string) =>
    request<SearchResponse>(`/questions/search?q=${encodeURIComponent(q)}`),

  questionThread: (id: string) =>
    request<QuestionThread>(`/questions/${id}/thread`),

  vote: (targetId: string, targetType: 'question' | 'answer', value: 1 | -1) =>
    request<Record<string, number>>('/questions/vote', {
      method: 'POST',
      body: JSON.stringify({ target_id: targetId, target_type: targetType, value }),
    }),

  createQuestion: (title: string, body: string, tags: string[] = []) =>
    request<{ question: Record<string, unknown> }>('/questions/new', {
      method: 'POST',
      body: JSON.stringify({ title, body, tags }),
    }),

  createAnswer: (questionId: string, body: string) =>
    request<{ answer: Record<string, unknown> }>(`/questions/${questionId}/answer`, {
      method: 'POST',
      body: JSON.stringify({ body }),
    }),

  listTags: () =>
    request<{ name: string; usage_count: number }[]>('/questions/tags'),

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
