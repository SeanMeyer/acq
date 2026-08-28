<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import QuestionRow from '../../components/QuestionRow.svelte';

  let { data } = $props();

  const totalPages = $derived(Math.ceil(data.total / data.pageSize));

  function setFilter(key: string, value: string) {
    const url = new URL($page.url);
    if (value) {
      url.searchParams.set(key, value);
    } else {
      url.searchParams.delete(key);
    }
    url.searchParams.delete('page');
    goto(url.toString(), { replaceState: true });
  }

  function setPage(p: number) {
    const url = new URL($page.url);
    if (p > 1) {
      url.searchParams.set('page', String(p));
    } else {
      url.searchParams.delete('page');
    }
    goto(url.toString(), { replaceState: true });
  }
</script>

<div class="min-h-screen bg-gray-50">
  <div class="max-w-4xl mx-auto px-4 py-8">
    <!-- Header -->
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-xl font-bold text-gray-900">Questions</h1>
      <div class="flex items-center gap-3">
        <span class="text-sm text-gray-500">{data.total} total</span>
        <a
          href="/questions/ask"
          class="px-3 py-1.5 text-sm font-medium rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 transition-colors"
        >
          Ask Question
        </a>
      </div>
    </div>

    <!-- Filters -->
    <div class="flex items-center gap-3 mb-4">
      <div class="flex items-center bg-white border border-gray-200 rounded-lg overflow-hidden text-sm">
        {#each [['', 'All'], ['open', 'Open'], ['resolved', 'Resolved'], ['deleted', 'Deleted']] as [value, label] (value)}
          <button
            onclick={() => setFilter('status', value)}
            class="px-3 py-1.5 font-medium transition-colors
              {data.status === value
                ? 'bg-indigo-50 text-indigo-700'
                : 'text-gray-600 hover:bg-gray-50'}"
          >
            {label}
          </button>
        {/each}
      </div>

      {#if data.tag}
        <button
          onclick={() => setFilter('tag', '')}
          class="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-sm bg-indigo-50 text-indigo-700 border border-indigo-200"
        >
          {data.tag}
          <svg class="w-3 h-3" viewBox="0 0 20 20" fill="currentColor">
            <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
          </svg>
        </button>
      {/if}
    </div>

    <!-- Empty -->
    {#if data.items.length === 0}
      <div class="flex flex-col items-center justify-center py-24 text-center">
        <h2 class="text-lg font-semibold text-gray-900 mb-1">No questions yet</h2>
        <p class="text-sm text-gray-500">
          {#if data.status || data.tag}
            No questions match these filters. Try removing a filter.
          {:else}
            Questions will appear here when agents start asking them.
          {/if}
        </p>
      </div>

    <!-- Question list -->
    {:else}
      <div class="bg-white rounded-xl border border-gray-200 overflow-hidden">
        {#each data.items as item (item.question.id)}
          <QuestionRow {item} />
        {/each}
      </div>

      {#if totalPages > 1}
        <div class="flex items-center justify-center gap-2 mt-6">
          <button
            onclick={() => setPage(data.page - 1)}
            disabled={data.page <= 1}
            class="px-3 py-1.5 text-sm rounded-lg border border-gray-200 transition-colors
              {data.page <= 1 ? 'text-gray-300 cursor-not-allowed' : 'text-gray-600 hover:bg-gray-50'}"
          >
            Previous
          </button>
          <span class="text-sm text-gray-500">
            Page {data.page} of {totalPages}
          </span>
          <button
            onclick={() => setPage(data.page + 1)}
            disabled={data.page >= totalPages}
            class="px-3 py-1.5 text-sm rounded-lg border border-gray-200 transition-colors
              {data.page >= totalPages ? 'text-gray-300 cursor-not-allowed' : 'text-gray-600 hover:bg-gray-50'}"
          >
            Next
          </button>
        </div>
      {/if}
    {/if}
  </div>
</div>
