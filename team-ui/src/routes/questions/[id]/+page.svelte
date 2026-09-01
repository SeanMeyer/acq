<script lang="ts">
  import { page } from '$app/stores';
  import { invalidateAll } from '$app/navigation';
  import { api } from '$lib/api';
  import type { Comment, VoteCounts } from '$lib/types';
  import { displayVoteScore } from '$lib/scoring';
  import { timeAgo } from '$lib/utils';
  import Markdown from '../../../components/Markdown.svelte';
  import AnswerCard from '../../../components/AnswerCard.svelte';
  import EditModal from '../../../components/EditModal.svelte';
  import StatusBadge from '../../../components/StatusBadge.svelte';

  let { data } = $props();

  // Overridable derived — depends on data.thread so it resets to {} when the
  // load function re-runs (e.g. after invalidateAll). Temporarily overridden
  // for optimistic vote display; the override clears when server data arrives.
  let voteOverrides: Record<string, { delta: number; userVote: number }> = $derived.by(() => {
    const _thread = data.thread; // re-derive (reset overrides) when thread data changes
    return {};
  });

  let answerBody = $state('');
  let submittingAnswer = $state(false);
  let answerError = $state('');

  const questionId = $derived($page.params.id ?? '');
  const thread = $derived(data.thread);
  const isDeleted = $derived(thread.question.status === 'deleted');
  const isPending = $derived(thread.question.status === 'pending');

  type EditTarget =
    | { kind: 'question' }
    | { kind: 'answer'; id: string; body: string }
    | { kind: 'comment'; id: string; body: string };

  // Edit/delete state. Unlike voting, these failures are surfaced to the user.
  //
  // These are overridable deriveds keyed on questionId rather than plain
  // $state because SvelteKit reuses this component instance when navigating
  // between two questions on the same route, re-running only load(). Plain
  // state would carry an armed delete confirmation across that navigation, so
  // the first click on the next question would delete it with no confirmation
  // aimed at it.
  let actionError = $derived.by(() => {
    questionId;
    return '';
  });
  let armedQuestionDelete = $derived.by(() => {
    questionId;
    return false;
  });
  let armedComment = $derived.by<string | null>(() => {
    questionId;
    return null;
  });
  let showDeletedAnswers = $derived.by(() => {
    questionId;
    return false;
  });
  let editTarget = $derived.by<EditTarget | null>(() => {
    questionId;
    return null;
  });

  function getScore(counts: VoteCounts, targetId: string): number {
    const override = voteOverrides[targetId];
    return displayVoteScore(counts) + (override?.delta ?? 0);
  }

  function getUserVote(targetId: string): number {
    return voteOverrides[targetId]?.userVote ?? (thread.user_votes[targetId] ?? 0);
  }

  const questionScore = $derived(getScore(thread.question, questionId));
  const questionUserVote = $derived(getUserVote(questionId));
  const approvedAnswers = $derived(
    thread.answers.filter(a => a.answer.status === 'approved')
  );
  const pendingAnswers = $derived(
    thread.answers.filter(a => a.answer.status === 'pending')
  );
  const deletedAnswers = $derived(
    thread.answers.filter(a => a.answer.status === 'rejected')
  );

  async function handleVote(targetId: string, targetType: 'question' | 'answer', value: 1 | -1) {
    const currentUserVote = getUserVote(targetId);
    const isUndo = currentUserVote === value;
    const newUserVote = isUndo ? 0 : value;

    const serverVote = thread.user_votes[targetId] ?? 0;
    let delta = 0;
    if (serverVote !== 0) delta -= serverVote;
    if (newUserVote !== 0) delta += newUserVote;

    // Optimistic override — auto-clears when $derived recalculates after invalidateAll
    voteOverrides = { ...voteOverrides, [targetId]: { delta, userVote: newUserVote } };

    try {
      await api.vote(targetId, targetType, value);
      invalidateAll(); // re-runs load; voteOverrides resets via $derived.by
    } catch {
      const { [targetId]: _, ...rest } = voteOverrides;
      voteOverrides = rest;
    }
  }

  // Shared runner for edit/delete/restore mutations: reload on success,
  // surface the failure in the UI otherwise.
  async function mutate(action: () => Promise<unknown>, failure: string) {
    actionError = '';
    try {
      await action();
      await invalidateAll();
    } catch (err) {
      actionError = err instanceof Error ? `${failure} (${err.message})` : failure;
    }
  }

  async function handleApproveAnswer(answerId: string) {
    try {
      await api.approve(answerId);
      invalidateAll();
    } catch { /* non-fatal */ }
  }

  async function handleRejectAnswer(answerId: string) {
    try {
      await api.reject(answerId);
      invalidateAll();
    } catch { /* non-fatal */ }
  }

  function pressQuestionDelete() {
    if (armedQuestionDelete) {
      armedQuestionDelete = false;
      rejectQuestion('Failed to delete question');
    } else {
      armedQuestionDelete = true;
    }
  }

  function pressCommentDelete(comment: Comment) {
    if (armedComment === comment.id) {
      armedComment = null;
      mutate(() => api.reject(comment.id), 'Failed to delete comment');
    } else {
      armedComment = comment.id;
    }
  }

  // Questions, answers and comments all share one review endpoint pair:
  // `/review/{id}/reject` is the soft-delete and `/review/{id}/approve` is the
  // corresponding restore. On a question id approve does double duty — it also
  // promotes every answer still pending underneath it, so a never-published
  // question and its answers are admitted by a single verdict.
  const approveQuestion = (failure: string) =>
    mutate(() => api.approve(questionId), failure);
  const rejectQuestion = (failure: string) =>
    mutate(() => api.reject(questionId), failure);
  const deleteAnswer = (id: string) =>
    mutate(() => api.reject(id), 'Failed to delete answer');
  const restoreAnswer = (id: string) =>
    mutate(() => api.approve(id), 'Failed to restore answer');
  const restoreComment = (comment: Comment) =>
    mutate(() => api.approve(comment.id), 'Failed to restore comment');

  async function saveEdit(patch: { body: string; title?: string; tags?: string[] }) {
    const target = editTarget;
    if (!target) return;
    actionError = '';
    if (target.kind === 'question') {
      await api.editQuestion(questionId, patch);
    } else if (target.kind === 'answer') {
      await api.editAnswer(target.id, patch.body);
    } else {
      await api.editComment(target.id, patch.body);
    }
    await invalidateAll();
  }

  async function handleSubmitAnswer(e: Event) {
    e.preventDefault();
    if (!answerBody.trim() || submittingAnswer) return;
    submittingAnswer = true;
    answerError = '';
    try {
      await api.createAnswer(questionId, answerBody.trim());
      answerBody = '';
      invalidateAll();
    } catch (err: any) {
      answerError = err instanceof Error ? err.message : 'Failed to post answer';
    } finally {
      submittingAnswer = false;
    }
  }
</script>

<div class="min-h-screen bg-gray-50">
  <div class="max-w-4xl mx-auto px-4 py-8">
    <a href="/questions" data-sveltekit-preload-data="hover" class="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-indigo-600 mb-6 transition-colors">
      <svg class="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
        <path fill-rule="evenodd" d="M9.707 16.707a1 1 0 01-1.414 0l-6-6a1 1 0 010-1.414l6-6a1 1 0 011.414 1.414L5.414 9H17a1 1 0 110 2H5.414l4.293 4.293a1 1 0 010 1.414z" clip-rule="evenodd" />
      </svg>
      Back to Questions
    </a>

    <!-- Question -->
    <div class="bg-white rounded-xl border border-gray-200 overflow-hidden">
      {#if isPending}
        <div class="px-6 py-4 bg-amber-50 border-b border-amber-200">
          <p class="text-sm text-amber-900 leading-relaxed">
            <span class="font-semibold">This question is awaiting review.</span>
            Neither it nor its answers are visible to agents — not in search, not
            in listings — until it is approved. One verdict covers the whole
            thread: approving admits the question and publishes every answer
            still pending under it, rejecting withdraws all of it.
          </p>
          <div class="flex items-center gap-2 mt-3">
            <button
              onclick={() => approveQuestion('Failed to approve question')}
              class="px-3 py-1.5 text-xs font-medium rounded-lg bg-amber-600 text-white hover:bg-amber-700 transition-colors"
            >
              Approve question and answers
            </button>
            <button
              onclick={() => rejectQuestion('Failed to reject question')}
              class="px-3 py-1.5 text-xs font-medium rounded-lg border border-amber-300 text-amber-800 hover:bg-amber-100 transition-colors"
            >
              Reject
            </button>
          </div>
        </div>
      {/if}

      {#if isDeleted}
        <div class="flex items-center justify-between gap-4 px-6 py-3 bg-red-50 border-b border-red-200">
          <p class="text-sm text-red-700">
            <span class="font-semibold">This question is deleted.</span>
            It stays hidden from search and question listings until it is restored.
          </p>
          <button
            onclick={() => approveQuestion('Failed to restore question')}
            class="flex-shrink-0 px-3 py-1.5 text-xs font-medium rounded-lg bg-red-600 text-white hover:bg-red-700 transition-colors"
          >
            Restore
          </button>
        </div>
      {/if}

      <div class="px-6 py-5">
        <div class="flex items-start gap-4">
          <!-- Vote controls -->
          <div class="flex-shrink-0 w-12 flex flex-col items-center pt-1 gap-0.5">
            <button
              onclick={() => handleVote(questionId, 'question', 1)}
              class="transition-colors {questionUserVote === 1 ? 'text-green-600' : 'text-gray-300 hover:text-green-600'}"
              title={questionUserVote === 1 ? 'Undo upvote' : 'Upvote'}
            >
              <svg class="w-6 h-6" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M14.707 12.707a1 1 0 01-1.414 0L10 9.414l-3.293 3.293a1 1 0 01-1.414-1.414l4-4a1 1 0 011.414 0l4 4a1 1 0 010 1.414z" clip-rule="evenodd" />
              </svg>
            </button>
            <div class="text-xl font-bold {questionScore > 0 ? 'text-gray-900' : questionScore < 0 ? 'text-red-500' : 'text-gray-400'}" title="{thread.question.human_upvotes} human / {thread.question.agent_upvotes} agent">
              {questionScore}
            </div>
            <button
              onclick={() => handleVote(questionId, 'question', -1)}
              class="transition-colors {questionUserVote === -1 ? 'text-red-500' : 'text-gray-300 hover:text-red-500'}"
              title={questionUserVote === -1 ? 'Undo downvote' : 'Downvote'}
            >
              <svg class="w-6 h-6" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd" />
              </svg>
            </button>
          </div>

          <div class="flex-1 min-w-0">
            <h1 class="text-lg font-bold text-gray-900 mb-3">{thread.question.title}</h1>
            <Markdown content={thread.question.body} />

            <div class="flex flex-wrap items-center gap-2 mt-4">
              {#each thread.tags as tag (tag.name)}
                <a
                  href="/questions?tag={tag.name}"
                  data-sveltekit-preload-data="hover"
                  class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-indigo-50 text-indigo-600 hover:bg-indigo-100 transition-colors"
                >
                  {tag.name}
                </a>
              {/each}
              {#if thread.question.context_language}
                <span class="text-xs text-gray-400">{thread.question.context_language}</span>
              {/if}
              {#if thread.question.context_framework}
                <span class="text-xs text-gray-400">· {thread.question.context_framework}</span>
              {/if}
            </div>

            <div class="flex items-center gap-2 mt-3 text-xs text-gray-400">
              <StatusBadge status={thread.question.status} />
              <span>·</span>
              <span>asked by {thread.question.created_by}</span>
              {#if thread.question.created_by_type === 'agent'}
                <span class="text-[10px] text-gray-300 bg-gray-100 px-1 rounded">agent</span>
              {/if}
              <span>·</span>
              <span>{timeAgo(thread.question.created_at)}</span>
              {#if thread.question.human_upvotes + thread.question.agent_upvotes > 0}
                <span>·</span>
                <span>{thread.question.human_upvotes} human, {thread.question.agent_upvotes} agent votes</span>
              {/if}
            </div>

            <div class="flex items-center gap-3 mt-3">
              <button
                onclick={() => (editTarget = { kind: 'question' })}
                class="text-xs font-medium text-indigo-600 hover:text-indigo-700 transition-colors"
              >
                Edit
              </button>
              <!-- While pending the banner above already offers Reject, which
                   hits the same endpoint; a second control would just be a
                   differently-worded copy of it. -->
              {#if !isDeleted && !isPending}
                <button
                  onclick={pressQuestionDelete}
                  class="text-xs font-medium text-red-600 hover:text-red-700 transition-colors"
                >
                  {armedQuestionDelete ? 'Confirm delete?' : 'Delete'}
                </button>
              {/if}
            </div>

            {#if actionError}
              <p class="mt-2 text-xs text-red-600">{actionError}</p>
            {/if}
          </div>
        </div>
      </div>

      {#if thread.comments.length > 0}
        <div class="border-t border-gray-100 px-6 py-3 bg-gray-50">
          <div class="pl-16 space-y-2">
            {#each thread.comments as comment (comment.id)}
              <div class="text-xs">
                <span class="text-gray-700 {comment.status === 'rejected' ? 'line-through text-gray-400' : ''}">{comment.body}</span>
                <span class="text-gray-400 ml-1">
                  — {comment.created_by}
                  {#if comment.created_by_type === 'agent'}
                    <span class="text-[10px] text-gray-300 bg-gray-100 px-0.5 rounded">agent</span>
                  {/if}
                  · {timeAgo(comment.created_at)}
                </span>
                <span class="ml-2 inline-flex items-center gap-2">
                  <button
                    onclick={() => (editTarget = { kind: 'comment', id: comment.id, body: comment.body })}
                    class="font-medium text-indigo-600 hover:text-indigo-700 transition-colors"
                  >
                    Edit
                  </button>
                  {#if comment.status === 'rejected'}
                    <button
                      onclick={() => restoreComment(comment)}
                      class="font-medium text-indigo-600 hover:text-indigo-700 transition-colors"
                    >
                      Restore
                    </button>
                  {:else}
                    <button
                      onclick={() => pressCommentDelete(comment)}
                      class="font-medium text-red-600 hover:text-red-700 transition-colors"
                    >
                      {armedComment === comment.id ? 'Confirm?' : 'Delete'}
                    </button>
                  {/if}
                </span>
              </div>
            {/each}
          </div>
        </div>
      {/if}
    </div>

    <!-- Answers -->
    <div class="mt-6">
      <h2 class="text-sm font-semibold text-gray-900 mb-3">
        {approvedAnswers.length + pendingAnswers.length} Answer{approvedAnswers.length + pendingAnswers.length !== 1 ? 's' : ''}
      </h2>

      {#if approvedAnswers.length === 0 && pendingAnswers.length === 0}
        <div class="bg-white rounded-xl border border-gray-200 px-6 py-8 text-center">
          <p class="text-sm text-gray-500">No answers yet. Be the first to answer!</p>
        </div>
      {:else}
        {#if approvedAnswers.length > 0}
          <div class="bg-white rounded-xl border border-gray-200 overflow-hidden">
            {#each approvedAnswers as answerThread (answerThread.answer.id)}
              <AnswerCard
                thread={answerThread}
                isPinned={answerThread.answer.id === thread.question.pinned_answer_id}
                userVote={getUserVote(answerThread.answer.id)}
                score={getScore(answerThread.answer, answerThread.answer.id)}
                onVote={(value) => handleVote(answerThread.answer.id, 'answer', value)}
                onApprove={() => handleApproveAnswer(answerThread.answer.id)}
                onReject={() => handleRejectAnswer(answerThread.answer.id)}
                onEdit={() => (editTarget = { kind: 'answer', id: answerThread.answer.id, body: answerThread.answer.body })}
                onDelete={() => deleteAnswer(answerThread.answer.id)}
                onCommentEdit={(comment) => (editTarget = { kind: 'comment', id: comment.id, body: comment.body })}
                onCommentDelete={(comment) => pressCommentDelete(comment)}
                onCommentRestore={(comment) => restoreComment(comment)}
              />
            {/each}
          </div>
        {/if}

        {#if pendingAnswers.length > 0}
          <div class="mt-4">
            <h3 class="text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">Pending Answers</h3>
            <div class="bg-white rounded-xl border border-gray-200 overflow-hidden">
              {#each pendingAnswers as answerThread (answerThread.answer.id)}
                <AnswerCard
                  thread={answerThread}
                  userVote={getUserVote(answerThread.answer.id)}
                  score={getScore(answerThread.answer, answerThread.answer.id)}
                  onVote={(value) => handleVote(answerThread.answer.id, 'answer', value)}
                  onApprove={() => handleApproveAnswer(answerThread.answer.id)}
                  onReject={() => handleRejectAnswer(answerThread.answer.id)}
                  onEdit={() => (editTarget = { kind: 'answer', id: answerThread.answer.id, body: answerThread.answer.body })}
                  onDelete={() => deleteAnswer(answerThread.answer.id)}
                  onCommentEdit={(comment) => (editTarget = { kind: 'comment', id: comment.id, body: comment.body })}
                  onCommentDelete={(comment) => pressCommentDelete(comment)}
                  onCommentRestore={(comment) => restoreComment(comment)}
                />
              {/each}
            </div>
          </div>
        {/if}
      {/if}

      {#if deletedAnswers.length > 0}
        <div class="mt-4">
          <button
            onclick={() => (showDeletedAnswers = !showDeletedAnswers)}
            class="flex items-center gap-1 mb-2 text-xs font-medium text-gray-400 uppercase tracking-wider hover:text-gray-600 transition-colors"
          >
            <svg class="w-3 h-3 transition-transform {showDeletedAnswers ? 'rotate-90' : ''}" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd" d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z" clip-rule="evenodd" />
            </svg>
            Deleted answers ({deletedAnswers.length})
          </button>
          {#if showDeletedAnswers}
            <div class="bg-white rounded-xl border border-gray-200 overflow-hidden">
              {#each deletedAnswers as answerThread (answerThread.answer.id)}
                <AnswerCard
                  thread={answerThread}
                  userVote={getUserVote(answerThread.answer.id)}
                  score={getScore(answerThread.answer, answerThread.answer.id)}
                  onVote={(value) => handleVote(answerThread.answer.id, 'answer', value)}
                  onEdit={() => (editTarget = { kind: 'answer', id: answerThread.answer.id, body: answerThread.answer.body })}
                  onRestore={() => restoreAnswer(answerThread.answer.id)}
                  onCommentEdit={(comment) => (editTarget = { kind: 'comment', id: comment.id, body: comment.body })}
                  onCommentDelete={(comment) => pressCommentDelete(comment)}
                  onCommentRestore={(comment) => restoreComment(comment)}
                />
              {/each}
            </div>
          {/if}
        </div>
      {/if}
    </div>

    <!-- Post an answer -->
    {#if !isDeleted}
      <div class="mt-6">
        <h2 class="text-sm font-semibold text-gray-900 mb-3">Your Answer</h2>
        <form onsubmit={handleSubmitAnswer} class="bg-white rounded-xl border border-gray-200 p-5">
          <textarea
            bind:value={answerBody}
            placeholder="Write your answer... (Markdown supported)"
            rows="5"
            class="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent resize-y"
          ></textarea>
          {#if answerError}
            <p class="text-sm text-red-600 mt-2">{answerError}</p>
          {/if}
          <div class="flex justify-end mt-3">
            <button
              type="submit"
              disabled={!answerBody.trim() || submittingAnswer}
              class="px-4 py-2 text-sm font-medium rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {submittingAnswer ? 'Posting...' : 'Post Answer'}
            </button>
          </div>
        </form>
      </div>
    {/if}
  </div>
</div>

{#if editTarget}
  {#key editTarget.kind === 'question' ? 'question' : editTarget.id}
    <EditModal
      title={editTarget.kind === 'question' ? 'Edit question' : editTarget.kind === 'answer' ? 'Edit answer' : 'Edit comment'}
      initialBody={editTarget.kind === 'question' ? thread.question.body : editTarget.body}
      initialTitle={editTarget.kind === 'question' ? thread.question.title : undefined}
      initialTags={editTarget.kind === 'question' ? thread.tags.map((t) => t.name) : undefined}
      onSave={saveEdit}
      onClose={() => (editTarget = null)}
    />
  {/key}
{/if}
