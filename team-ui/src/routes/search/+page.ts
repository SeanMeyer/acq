import { api } from '$lib/api';
import type { SearchResult } from '$lib/types';

export async function load({ url }: { url: URL }): Promise<{
  query: string;
  results: SearchResult[];
}> {
  const query = url.searchParams.get('q') ?? '';
  if (!query.trim()) {
    return { query, results: [] };
  }
  const res = await api.searchQuestions(query);
  return { query, results: res.results };
}
