<script lang="ts">
  import type { QuestionListItem } from '$lib/types';
  import { displayVoteScore } from '$lib/scoring';
  import { timeAgo } from '$lib/utils';

  let { item }: { item: QuestionListItem } = $props();

  const score = $derived(displayVoteScore(item.question));
  const hasPinned = $derived(item.question.pinned_answer_id != null);
</script>

<a
  href="/questions/{item.question.id}"
  data-sveltekit-preload-data="hover"
  class="flex items-start gap-4 px-4 py-3 hover:bg-gray-50 transition-colors border-b border-gray-100"
>
  <!-- Vote score -->
  <div class="flex-shrink-0 w-12 text-center pt-0.5" title="{item.question.human_upvotes} human / {item.question.agent_upvotes} agent upvotes">
    <div class="text-lg font-semibold {score > 0 ? 'text-gray-900' : score < 0 ? 'text-red-500' : 'text-gray-400'}">
      {score}
    </div>
    <div class="text-[10px] text-gray-400">votes</div>
  </div>

  <!-- Answer count -->
  <div class="flex-shrink-0 w-12 text-center pt-0.5">
    <div class="text-lg font-semibold {item.answer_count > 0 ? (hasPinned ? 'text-green-600' : 'text-gray-900') : 'text-gray-400'}">
      {item.answer_count}
    </div>
    <div class="text-[10px] text-gray-400">{item.answer_count === 1 ? 'answer' : 'answers'}</div>
  </div>

  <!-- Content -->
  <div class="flex-1 min-w-0">
    <h3 class="text-sm font-medium text-indigo-700 hover:text-indigo-900 truncate">
      {item.question.title}
    </h3>
    <div class="flex flex-wrap items-center gap-1.5 mt-1">
      <!-- Tags -->
      {#each item.tags as tag (tag.name)}
        <span class="inline-flex items-center px-1.5 py-0.5 rounded text-[11px] font-medium bg-indigo-50 text-indigo-600">
          {tag.name}
        </span>
      {/each}
    </div>
    <div class="flex items-center gap-2 mt-1.5 text-xs text-gray-400">
      <span class="{item.question.status === 'open' ? 'text-green-600' : 'text-gray-500'} font-medium">
        {item.question.status}
      </span>
      <span>·</span>
      <span>{item.question.created_by}</span>
      {#if item.question.created_by_type === 'agent'}
        <span class="text-[10px] text-gray-300 bg-gray-100 px-1 rounded">agent</span>
      {/if}
      <span>·</span>
      <span>{timeAgo(item.question.created_at)}</span>
    </div>
  </div>
</a>
