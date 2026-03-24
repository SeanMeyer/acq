<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { ReviewItem } from '$lib/types';
  import ReviewCard from '../../components/ReviewCard.svelte';
  import ReviewActions from '../../components/ReviewActions.svelte';

  let items = $state<ReviewItem[]>([]);
  let total = $state(0);
  let loading = $state(true);
  let error = $state('');
  let actionInProgress = $state(false);

  // Session stats
  let sessionApproved = $state(0);
  let sessionRejected = $state(0);
  let sessionSkipped = $state(0);

  // Index into current items array; skipped items are tracked separately so
  // we can cycle past them without losing the other items.
  let currentIndex = $state(0);
  let skippedIds = $state<Set<string>>(new Set());

  const availableItems = $derived(
    items.filter(i => !skippedIds.has(i.id))
  );

  const currentItem = $derived(
    availableItems[currentIndex] ?? null
  );

  const queueEmpty = $derived(
    !loading && availableItems.length === 0
  );

  async function loadQueue() {
    loading = true;
    error = '';
    try {
      const res = await api.reviewQueue(50, 0);
      items = res.items;
      total = res.total;
      currentIndex = 0;
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to load queue';
    } finally {
      loading = false;
    }
  }

  function advance() {
    // Move to next available item, wrapping around if needed
    if (availableItems.length <= 1) {
      currentIndex = 0;
    } else if (currentIndex >= availableItems.length - 1) {
      currentIndex = 0;
    } else {
      currentIndex += 1;
    }
  }

  async function handleApprove() {
    if (!currentItem || actionInProgress) return;
    const id = currentItem.id;
    actionInProgress = true;
    // Optimistic: remove from local list
    items = items.filter(i => i.id !== id);
    skippedIds = new Set([...skippedIds].filter(sid => sid !== id));
    sessionApproved += 1;
    try {
      await api.approve(id);
    } catch {
      // Non-fatal — item already removed from view
    } finally {
      actionInProgress = false;
      // Clamp index if needed
      if (currentIndex >= availableItems.length) currentIndex = 0;
    }
  }

  async function handleReject() {
    if (!currentItem || actionInProgress) return;
    const id = currentItem.id;
    actionInProgress = true;
    items = items.filter(i => i.id !== id);
    skippedIds = new Set([...skippedIds].filter(sid => sid !== id));
    sessionRejected += 1;
    try {
      await api.reject(id);
    } catch {
      // Non-fatal
    } finally {
      actionInProgress = false;
      if (currentIndex >= availableItems.length) currentIndex = 0;
    }
  }

  function handleSkip() {
    if (!currentItem) return;
    skippedIds = new Set([...skippedIds, currentItem.id]);
    sessionSkipped += 1;
    // Don't advance index — the derived list will shift, showing next item
  }

  onMount(loadQueue);
</script>

<div class="min-h-screen bg-gray-50">
  <div class="max-w-3xl mx-auto px-4 py-8">
    <!-- Header -->
    <div class="flex items-center justify-between mb-6">
      <div>
        <h1 class="text-xl font-bold text-gray-900">Review Queue</h1>
        {#if !loading}
          <p class="text-sm text-gray-500 mt-0.5">
            {availableItems.length} items remaining
            {#if skippedIds.size > 0}
              · {skippedIds.size} skipped
            {/if}
          </p>
        {/if}
      </div>

      <!-- Session stats -->
      {#if sessionApproved + sessionRejected + sessionSkipped > 0}
        <div class="flex items-center gap-4 text-sm">
          {#if sessionApproved > 0}
            <span class="text-green-700 font-medium">{sessionApproved} approved</span>
          {/if}
          {#if sessionRejected > 0}
            <span class="text-red-600 font-medium">{sessionRejected} rejected</span>
          {/if}
          {#if sessionSkipped > 0}
            <span class="text-gray-500">{sessionSkipped} skipped</span>
          {/if}
        </div>
      {/if}
    </div>

    <!-- Loading state -->
    {#if loading}
      <div class="flex items-center justify-center py-24">
        <svg class="w-8 h-8 text-indigo-400 animate-spin" viewBox="0 0 24 24" fill="none">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      </div>

    <!-- Error state -->
    {:else if error}
      <div class="rounded-xl bg-red-50 border border-red-200 p-6 text-center">
        <p class="text-red-700 mb-4">{error}</p>
        <button
          onclick={loadQueue}
          class="px-4 py-2 bg-red-600 text-white text-sm rounded-lg hover:bg-red-700 transition-colors"
        >
          Retry
        </button>
      </div>

    <!-- Empty queue -->
    {:else if queueEmpty}
      <div class="flex flex-col items-center justify-center py-24 text-center">
        <div class="w-16 h-16 rounded-full bg-green-100 flex items-center justify-center mb-4">
          <svg class="w-8 h-8 text-green-600" viewBox="0 0 20 20" fill="currentColor">
            <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
          </svg>
        </div>
        <h2 class="text-lg font-semibold text-gray-900 mb-1">All caught up!</h2>
        <p class="text-sm text-gray-500 mb-6">
          {#if skippedIds.size > 0}
            You skipped {skippedIds.size} item{skippedIds.size !== 1 ? 's' : ''}.
          {:else}
            No pending items in the queue.
          {/if}
        </p>
        <div class="flex gap-3">
          {#if skippedIds.size > 0}
            <button
              onclick={() => { skippedIds = new Set(); }}
              class="px-4 py-2 bg-indigo-600 text-white text-sm rounded-lg hover:bg-indigo-700 transition-colors"
            >
              Review skipped items
            </button>
          {/if}
          <button
            onclick={loadQueue}
            class="px-4 py-2 bg-white border border-gray-300 text-gray-700 text-sm rounded-lg hover:bg-gray-50 transition-colors"
          >
            Refresh queue
          </button>
        </div>
      </div>

    <!-- Review card -->
    {:else if currentItem}
      <div class="space-y-6">
        <!-- Progress indicator -->
        <div class="flex items-center gap-2">
          <div class="flex-1 h-1.5 bg-gray-200 rounded-full overflow-hidden">
            <div
              class="h-full bg-indigo-500 rounded-full transition-all"
              style="width: {total > 0 ? Math.round(((total - availableItems.length) / total) * 100) : 0}%"
            ></div>
          </div>
          <span class="text-xs text-gray-400 flex-shrink-0">
            {total - availableItems.length} / {total}
          </span>
        </div>

        <ReviewCard item={currentItem} onEditSaved={() => {}} />

        <div class="flex justify-center pt-2">
          <ReviewActions
            onApprove={handleApprove}
            onReject={handleReject}
            onSkip={handleSkip}
            disabled={actionInProgress}
          />
        </div>
      </div>
    {/if}
  </div>
</div>
