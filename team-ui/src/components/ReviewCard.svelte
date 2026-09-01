<script lang="ts">
  import type { ReviewItem, Answer } from '$lib/types';
  import { timeAgo } from '$lib/utils';
  import Markdown from './Markdown.svelte';
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

  const isQuestion = $derived(item.type === 'question');
  const isAnswer = $derived(item.type === 'answer');
  const content = $derived(item.content);
  const answer = $derived(isAnswer ? item.content as Answer : null);
  const question = $derived(item.question);

  async function saveEdit(patch: { body: string; title?: string; tags?: string[] }) {
    if (isQuestion) {
      await api.editQuestion(content.id, patch);
    } else if (isAnswer) {
      await api.editAnswer(content.id, patch.body);
    } else {
      await api.editComment(content.id, patch.body);
    }
    onEditSaved?.();
  }
</script>

<div class="max-w-2xl mx-auto bg-white rounded-2xl shadow-sm border border-gray-200 overflow-hidden">
  {#if isQuestion}
    <!--
      Question path: the question IS the contribution, not context for one.
      Everything between this banner and the footer rides on a single verdict,
      so the card is framed as one unit rather than as stacked sub-decisions.
    -->
    <div class="px-6 py-3 bg-amber-50 border-b border-amber-200">
      <p class="text-xs font-semibold text-amber-800 uppercase tracking-wide">New question for review</p>
      <p class="text-xs text-amber-700 mt-1 leading-relaxed">
        One verdict covers this entire card — the question and
        {item.answers.length === 1 ? 'the answer' : `all ${item.answers.length} answers`} below.
        Rejecting hides the question; its answers never surface on their own.
      </p>
    </div>

    <div class="px-6 py-5">
      <div class="flex items-start justify-between gap-3 mb-2">
        <h3 class="text-base font-semibold text-gray-900 leading-snug flex-1 min-w-0">{question.title}</h3>
        <button
          onclick={() => (showEditModal = true)}
          class="flex-shrink-0 text-xs text-indigo-600 hover:text-indigo-800 font-medium transition-colors hover:underline"
        >
          Edit before approving
        </button>
      </div>

      {#if question.tags && question.tags.length > 0}
        <div class="flex flex-wrap gap-1.5 mb-3">
          {#each question.tags as tag (tag.name)}
            <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs bg-indigo-50 text-indigo-700 font-medium">
              {tag.name}
            </span>
          {/each}
        </div>
      {/if}

      <Markdown content={question.body} />
    </div>

    <div class="mx-6 mb-5 rounded-xl border border-gray-200 bg-gray-50 px-4 py-3">
      <p class="text-sm text-gray-700 leading-relaxed">
        Would this save substantial future investigation or prevent a costly mistake?
        Reject it when the answer is quickly available from code or documentation, or
        when its value ends with the current task.
      </p>
    </div>

    <div class="border-t border-gray-100 bg-gray-50/60 px-6 py-4">
      <p class="text-xs font-medium text-gray-400 uppercase tracking-wide mb-3">
        {item.answers.length}
        {item.answers.length === 1 ? 'answer' : 'answers'} covered by this verdict
      </p>
      {#if item.answers.length === 0}
        <p class="text-sm text-gray-500 italic">
          No answers bundled — approving publishes an unanswered question.
        </p>
      {:else}
        <div class="space-y-3">
          {#each item.answers as bundled (bundled.id)}
            <div class="rounded-xl border border-gray-200 bg-white px-4 py-3">
              <div class="flex items-center justify-between gap-2 mb-2">
                <span class="text-xs text-gray-500">
                  by <span class="font-medium text-gray-700">{bundled.created_by}</span>
                  <span class="text-gray-400">({bundled.created_by_type})</span>
                </span>
                <div class="flex items-center gap-2">
                  {#if bundled.supervised}
                    <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-700">
                      supervised
                    </span>
                  {/if}
                  <span class="text-xs text-gray-400">{timeAgo(bundled.created_at)}</span>
                </div>
              </div>
              <Markdown content={bundled.body} />
            </div>
          {/each}
        </div>
      {/if}
    </div>
  {:else}
    <!-- Question context (collapsible) -->
    <div class="border-b border-gray-100">
      <button
        onclick={() => (questionExpanded = !questionExpanded)}
        class="w-full text-left px-6 py-4 hover:bg-gray-50 transition-colors group"
      >
        <div class="flex items-start justify-between gap-3">
          <div class="flex-1 min-w-0">
            <p class="text-xs font-medium text-gray-400 uppercase tracking-wide mb-1">Question</p>
            <h3 class="text-base font-semibold text-gray-900 leading-snug">{question.title}</h3>
            {#if question.tags && question.tags.length > 0}
              <div class="flex flex-wrap gap-1.5 mt-2">
                {#each question.tags as tag (tag.name)}
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
          <Markdown content={question.body} />
        </div>
      {/if}
    </div>

    <!-- Answer/comment body -->
    <div class="px-6 py-5">
      <div class="flex items-center justify-between mb-3">
        <div class="flex items-center gap-2">
          <p class="text-xs font-medium text-indigo-600 uppercase tracking-wide">
            {isAnswer ? 'Answer for review' : 'Comment for review'}
          </p>
          {#if answer?.supervised}
            <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-700">
              supervised
            </span>
          {/if}
        </div>
        <button
          onclick={() => (showEditModal = true)}
          class="text-xs text-indigo-600 hover:text-indigo-800 font-medium transition-colors hover:underline"
        >
          Edit before approving
        </button>
      </div>

      <Markdown content={content.body} />
    </div>
  {/if}

  <!-- Footer -->
  <div class="px-6 py-3 bg-gray-50 border-t border-gray-100 flex items-center justify-between">
    <span class="text-xs text-gray-500">
      by <span class="font-medium text-gray-700">{content.created_by}</span>
      <span class="text-gray-400">({content.created_by_type})</span>
    </span>
    <span class="text-xs text-gray-400">{timeAgo(content.created_at)}</span>
  </div>
</div>

{#if showEditModal}
  <EditModal
    title={isQuestion ? 'Edit question' : isAnswer ? 'Edit answer' : 'Edit comment'}
    initialBody={content.body}
    initialTitle={isQuestion ? question.title : undefined}
    initialTags={isQuestion ? (question.tags ?? []).map((t) => t.name) : undefined}
    onSave={saveEdit}
    onClose={() => (showEditModal = false)}
  />
{/if}
