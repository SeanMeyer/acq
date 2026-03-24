<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { ReviewStats } from '$lib/types';
  import TagManager from '../../components/TagManager.svelte';
  import { timeAgo } from '$lib/utils';

  let stats = $state<ReviewStats | null>(null);
  let loading = $state(true);
  let error = $state('');
  let refreshInterval: ReturnType<typeof setInterval> | null = null;

  async function loadStats() {
    error = '';
    try {
      stats = await api.reviewStats();
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to load stats';
    } finally {
      loading = false;
    }
  }

  const topTags = $derived(
    stats?.tags
      ? [...stats.tags].sort((a, b) => b.usage_count - a.usage_count).slice(0, 10)
      : []
  );

  const maxTagCount = $derived(
    topTags.length > 0 ? topTags[0].usage_count : 1
  );

  const statCards = $derived(stats ? [
    { label: 'Pending Review', value: stats.total_pending, color: 'text-amber-600', bg: 'bg-amber-50', border: 'border-amber-100' },
    { label: 'Questions', value: stats.total_questions, color: 'text-indigo-600', bg: 'bg-indigo-50', border: 'border-indigo-100' },
    { label: 'Answers', value: stats.total_answers, color: 'text-green-600', bg: 'bg-green-50', border: 'border-green-100' },
    { label: 'Unanswered', value: stats.total_unanswered, color: 'text-red-500', bg: 'bg-red-50', border: 'border-red-100' },
  ] : []);

  onMount(() => {
    loadStats();
    refreshInterval = setInterval(loadStats, 15_000);
    return () => {
      if (refreshInterval) clearInterval(refreshInterval);
    };
  });
</script>

<div class="min-h-screen bg-gray-50">
  <div class="max-w-5xl mx-auto px-4 py-8">
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-xl font-bold text-gray-900">Dashboard</h1>
      {#if !loading}
        <button
          onclick={loadStats}
          class="text-sm text-gray-500 hover:text-gray-700 transition-colors flex items-center gap-1.5"
        >
          <svg class="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
            <path fill-rule="evenodd" d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 010 2H4a1 1 0 01-1-1V3a1 1 0 011-1zm.008 9.057a1 1 0 011.276.61A5.002 5.002 0 0014.001 13H11a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0v-2.101a7.002 7.002 0 01-11.601-2.566 1 1 0 01.61-1.276z" clip-rule="evenodd" />
          </svg>
          Refresh
        </button>
      {/if}
    </div>

    {#if loading && !stats}
      <div class="flex items-center justify-center py-24">
        <svg class="w-8 h-8 text-indigo-400 animate-spin" viewBox="0 0 24 24" fill="none">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      </div>

    {:else if error && !stats}
      <div class="rounded-xl bg-red-50 border border-red-200 p-6 text-center">
        <p class="text-red-700 mb-4">{error}</p>
        <button
          onclick={loadStats}
          class="px-4 py-2 bg-red-600 text-white text-sm rounded-lg hover:bg-red-700 transition-colors"
        >
          Retry
        </button>
      </div>

    {:else if stats}
      <!-- Stat cards -->
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
        {#each statCards as card}
          <div class="rounded-xl {card.bg} border {card.border} px-5 py-4">
            <p class="text-xs font-medium text-gray-500 mb-1">{card.label}</p>
            <p class="text-2xl font-bold {card.color}">{card.value ?? 0}</p>
          </div>
        {/each}
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <!-- Top tags chart -->
        <div class="lg:col-span-2 bg-white rounded-xl border border-gray-200 p-5">
          <h2 class="text-sm font-semibold text-gray-900 mb-4">Top Tags</h2>
          {#if topTags.length > 0}
            <div class="space-y-2.5">
              {#each topTags as tag}
                {@const pct = maxTagCount > 0 ? Math.round((tag.usage_count / maxTagCount) * 100) : 0}
                <div class="flex items-center gap-3">
                  <span class="text-xs text-gray-600 w-28 truncate flex-shrink-0">{tag.name}</span>
                  <div class="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
                    <div
                      class="h-full bg-indigo-500 rounded-full transition-all"
                      style="width: {pct}%"
                    ></div>
                  </div>
                  <span class="text-xs text-gray-400 w-6 text-right flex-shrink-0">{tag.usage_count}</span>
                </div>
              {/each}
            </div>
          {:else}
            <p class="text-sm text-gray-400 text-center py-4">No tags yet</p>
          {/if}
        </div>

        <!-- Tag manager -->
        <div class="lg:col-span-1">
          <TagManager tags={stats.tags ?? []} onMerged={loadStats} />
        </div>
      </div>

      <!-- Recent activity -->
      {#if stats.recent_activity && stats.recent_activity.length > 0}
        <div class="mt-6 bg-white rounded-xl border border-gray-200 overflow-hidden">
          <div class="px-5 py-4 border-b border-gray-100">
            <h2 class="text-sm font-semibold text-gray-900">Recent Activity</h2>
          </div>
          <div class="divide-y divide-gray-50">
            {#each stats.recent_activity as event}
              <div class="px-5 py-3 flex items-start justify-between gap-4">
                <div class="flex-1 min-w-0">
                  <p class="text-sm text-gray-800 truncate">{event.description}</p>
                  <p class="text-xs text-gray-400 mt-0.5">by {event.actor}</p>
                </div>
                <span class="text-xs text-gray-400 flex-shrink-0 mt-0.5">{timeAgo(event.created_at)}</span>
              </div>
            {/each}
          </div>
        </div>
      {/if}
    {/if}
  </div>
</div>
