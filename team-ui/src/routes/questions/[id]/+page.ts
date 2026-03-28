import { api } from '$lib/api';
import type { QuestionThread } from '$lib/types';
import { error } from '@sveltejs/kit';

export async function load({ params }: { params: { id: string } }): Promise<{
  thread: QuestionThread;
}> {
  try {
    const thread = await api.questionThread(params.id);
    return { thread };
  } catch (e: any) {
    if (e?.status === 404) {
      error(404, 'Question not found');
    }
    throw e;
  }
}
