import { api } from '$lib/api';
import type { QuestionListResponse } from '$lib/types';

const PAGE_SIZE = 20;

export async function load({ url }: { url: URL }): Promise<{
  items: QuestionListResponse['items'];
  total: number;
  status: string;
  tag: string;
  page: number;
  pageSize: number;
}> {
  const status = url.searchParams.get('status') ?? '';
  const tag = url.searchParams.get('tag') ?? '';
  const page = Number(url.searchParams.get('page') ?? '1');

  const res = await api.listQuestions({
    status: status || undefined,
    tag: tag || undefined,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  });

  return {
    items: res.items,
    total: res.total,
    status,
    tag,
    page,
    pageSize: PAGE_SIZE,
  };
}
