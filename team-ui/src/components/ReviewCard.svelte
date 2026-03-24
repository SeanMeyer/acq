<script lang="ts">
  import type { ReviewItem, Answer } from '$lib/types';
  import { timeAgo } from '$lib/utils';
  import Markdown from './Markdown.svelte';
  import VoteBadge from './VoteBadge.svelte';
  import StatusBadge from './StatusBadge.svelte';
  import EditModal from './EditModal.svelte';
  import { api } from '$lib/api';

  let {
    item,
    onEditSaved,
  }: {
    item: ReviewItem;
    onEditSaved?: () => void;
  } = $props();

  let questionExpanded = $state(false);
  let showEditModal = $state(false);

  const isAnswer = $derived(item.type === 'answer');
  const content = $derived(item.content as Answer);

  async function saveEdit(body: string) {
    if (isAnswer) {
      await api.editAnswer(item.content.id, body);
    } else {
      // Comments don't have a dedicated edit endpoint in the spec, fall back to answer edit
      await api.editAnswer(item.content.id, body);
    }
    onEditSaved?.();
  }
</script>

<div class="max-w-2xl mx-auto bg-white rounded-2xl shadow-sm border border-gray-200 overflow-hidden">
  <!-- Question context (collapsible) -->
  <div class="border-b border-gray-100">
    <button
      onclick={() => (questionExpanded = !questionExpanded)}
      class="w-full text-left px-6 py-4 hover:bg-gray-50 transition-colors group"
    >
      <div class="flex items-start justify-between gap-3">
        <div class="flex-1 min-w-0">
          <p class="text-xs font-medium text-gray-400 uppercase tracking-wide mb-1">Question</p>
          <h3 class="text-base font-semibold text-gray-900 leading-snug">{item.question.title}</h3>
          {#if item.question.tags && item.question.tags.length > 0}
            <div class="flex flex-wrap gap-1.5 mt-2">
              {#each item.question.tags as tag}
                <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs bg-indigo-50 text-indigo-700 font-medium">
                  {tag.name}
                </span>
              {/each}
            </div>
          {/if}
          {#if !questionExpanded}
            <p class="text-xs text-gray-400 mt-1.5 group-hover:text-gray-500 transition-colors">
              click to expand
            </p>
          {/if}
        </div>
        <svg
          class="w-4 h-4 text-gray-400 flex-shrink-0 mt-1 transition-transform {questionExpanded ? 'rotate-180' : ''}"
          viewBox="0 0 20 20"
          fill="currentColor"
        >
          <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd" />
        </svg>
      </div>
    </button>

    {#if questionExpanded}
      <div class="px-6 pb-4">
        <Markdown content={item.question.body} />
      </div>
    {/if}
  </div>

  <!-- Answer/comment body -->
  <div class="px-6 py-5">
    <div class="flex items-center justify-between mb-3">
      <div class="flex items-center gap-2">
        <p class="text-xs font-medium text-gray-400 uppercase tracking-wide">
          {isAnswer ? 'Answer' : 'Comment'}
        </p>
        <StatusBadge status={item.content.status} />
        {#if isAnswer && (content as Answer).supervised}
          <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-700">
            supervised
          </span>
        {/if}
      </div>
      <button
        onclick={() => (showEditModal = true)}
        class="text-xs text-indigo-600 hover:text-indigo-800 font-medium transition-colors"
      >
        Edit before approving
      </button>
    </div>

    <Markdown content={item.content.body} />

    <!-- Votes (answers only) -->
    {#if isAnswer && (content as Answer).votes}
      <div class="mt-3">
        <VoteBadge
          agent_upvotes={(content as Answer).votes.agent_upvotes}
          agent_downvotes={(content as Answer).votes.agent_downvotes}
          human_upvotes={(content as Answer).votes.human_upvotes}
          human_downvotes={(content as Answer).votes.human_downvotes}
        />
      </div>
    {/if}
  </div>

  <!-- Footer -->
  <div class="px-6 py-3 bg-gray-50 border-t border-gray-100 flex items-center justify-between">
    <span class="text-xs text-gray-500">
      by <span class="font-medium text-gray-700">{item.content.author}</span>
    </span>
    <span class="text-xs text-gray-400">{timeAgo(item.content.created_at)}</span>
  </div>
</div>

{#if showEditModal}
  <EditModal
    title="Edit {isAnswer ? 'answer' : 'comment'}"
    initialBody={item.content.body}
    onSave={saveEdit}
    onClose={() => (showEditModal = false)}
  />
{/if}
