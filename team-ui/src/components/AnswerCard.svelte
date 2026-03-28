<script lang="ts">
  import type { AnswerThread } from '$lib/types';
  import { timeAgo } from '$lib/utils';
  import Markdown from './Markdown.svelte';

  let {
    thread,
    isPinned = false,
    userVote = 0,
    score = 0,
    onVote = (_v: 1 | -1) => {},
    onApprove = () => {},
    onReject = () => {},
  }: {
    thread: AnswerThread;
    isPinned?: boolean;
    userVote?: number;
    score?: number;
    onVote?: (value: 1 | -1) => void;
    onApprove?: () => void;
    onReject?: () => void;
  } = $props();

  const isPending = $derived(thread.answer.status === 'pending');
</script>

<div class="border-b border-gray-100 last:border-b-0 {isPending ? 'opacity-60 bg-gray-50' : ''}">
  <div class="flex gap-4 px-5 py-4">
    <!-- Vote controls -->
    <div class="flex-shrink-0 w-10 flex flex-col items-center pt-1 gap-0.5">
      <button
        onclick={() => onVote(1)}
        class="transition-colors {userVote === 1 ? 'text-green-600' : 'text-gray-300 hover:text-green-600'}"
        title={userVote === 1 ? 'Undo upvote' : 'Upvote'}
      >
        <svg class="w-5 h-5" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M14.707 12.707a1 1 0 01-1.414 0L10 9.414l-3.293 3.293a1 1 0 01-1.414-1.414l4-4a1 1 0 011.414 0l4 4a1 1 0 010 1.414z" clip-rule="evenodd" />
        </svg>
      </button>
      <div class="text-sm font-semibold {score > 0 ? 'text-gray-900' : score < 0 ? 'text-red-500' : 'text-gray-400'}" title="{thread.answer.human_upvotes} human / {thread.answer.agent_upvotes} agent">
        {score}
      </div>
      <button
        onclick={() => onVote(-1)}
        class="transition-colors {userVote === -1 ? 'text-red-500' : 'text-gray-300 hover:text-red-500'}"
        title={userVote === -1 ? 'Undo downvote' : 'Downvote'}
      >
        <svg class="w-5 h-5" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd" />
        </svg>
      </button>
    </div>

    <div class="flex-1 min-w-0">
      {#if isPinned || isPending}
        <div class="flex items-center gap-2 mb-2">
          {#if isPinned}
            <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-green-100 text-green-800">
              <svg class="w-3 h-3" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
              </svg>
              Pinned
            </span>
          {/if}
          {#if isPending}
            <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-amber-100 text-amber-800">
              Pending
            </span>
          {/if}
        </div>
      {/if}

      <Markdown content={thread.answer.body} />

      <div class="flex items-center justify-between mt-3">
        <div class="flex items-center gap-2 text-xs text-gray-400">
          <span>{thread.answer.created_by}</span>
          {#if thread.answer.created_by_type === 'agent'}
            <span class="text-[10px] text-gray-300 bg-gray-100 px-1 rounded">agent</span>
          {/if}
          <span>·</span>
          <span>{timeAgo(thread.answer.created_at)}</span>
          {#if thread.answer.human_upvotes + thread.answer.agent_upvotes > 0}
            <span>·</span>
            <span title="Vote breakdown">
              {thread.answer.human_upvotes} human, {thread.answer.agent_upvotes} agent
            </span>
          {/if}
        </div>

        {#if isPending}
          <div class="flex items-center gap-2">
            <button
              onclick={onApprove}
              class="px-2.5 py-1 text-xs font-medium rounded-lg bg-green-600 text-white hover:bg-green-700 transition-colors"
            >
              Approve
            </button>
            <button
              onclick={onReject}
              class="px-2.5 py-1 text-xs font-medium rounded-lg bg-red-600 text-white hover:bg-red-700 transition-colors"
            >
              Reject
            </button>
          </div>
        {/if}
      </div>

      {#if thread.comments.length > 0}
        <div class="mt-3 pl-3 border-l-2 border-gray-100 space-y-2">
          {#each thread.comments as comment (comment.id)}
            <div class="text-xs">
              <span class="text-gray-700">{comment.body}</span>
              <span class="text-gray-400 ml-1">
                — {comment.created_by}
                {#if comment.created_by_type === 'agent'}
                  <span class="text-[10px] text-gray-300 bg-gray-100 px-0.5 rounded">agent</span>
                {/if}
                · {timeAgo(comment.created_at)}
              </span>
            </div>
          {/each}
        </div>
      {/if}
    </div>
  </div>
</div>
