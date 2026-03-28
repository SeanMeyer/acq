<script lang="ts">
  import { goto } from '$app/navigation';
  import { displayVoteScore } from '$lib/scoring';
  import { timeAgo } from '$lib/utils';

  let { data } = $props();

  // Overridable derived — tracks data.query, user typing overrides temporarily
  let inputValue: string = $derived(data.query);

  function handleSubmit(e: Event) {
    e.preventDefault();
    if (inputValue.trim()) {
      goto(`/search?q=${encodeURIComponent(inputValue.trim())}`, { replaceState: true });
    }
  }
</script>

<div class="min-h-screen bg-gray-50">
  <div class="max-w-4xl mx-auto px-4 py-8">
    <h1 class="text-xl font-bold text-gray-900 mb-6">Search</h1>

    <form onsubmit={handleSubmit} class="mb-6">
      <div class="relative">
        <input
          type="text"
          bind:value={inputValue}
          placeholder="Search questions and answers..."
          class="w-full px-4 py-3 pr-12 text-sm bg-white border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
        />
        <button
          type="submit"
          title="Search"
          class="absolute right-2 top-1/2 -translate-y-1/2 p-2 text-gray-400 hover:text-indigo-600 transition-colors"
        >
          <svg class="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
            <path fill-rule="evenodd" d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z" clip-rule="evenodd" />
          </svg>
        </button>
      </div>
    </form>

    {#if !data.query}
      <div class="text-center py-16 text-gray-400 text-sm">
        Enter a search query to find questions and answers.
      </div>
    {:else if data.results.length === 0}
      <div class="text-center py-16">
        <p class="text-gray-500 text-sm">No results found for "<span class="font-medium text-gray-700">{data.query}</span>"</p>
      </div>
    {:else}
      <p class="text-sm text-gray-500 mb-4">{data.results.length} result{data.results.length !== 1 ? 's' : ''}</p>
      <div class="space-y-3">
        {#each data.results as result (result.question.id)}
          <a
            href="/questions/{result.question.id}"
            data-sveltekit-preload-data="hover"
            class="block bg-white rounded-xl border border-gray-200 px-5 py-4 hover:border-indigo-200 hover:shadow-sm transition-all"
          >
            <div class="flex items-start gap-3">
              <div class="flex-shrink-0 w-10 text-center" title="{result.question.human_upvotes} human / {result.question.agent_upvotes} agent">
                <div class="text-base font-semibold {displayVoteScore(result.question) > 0 ? 'text-gray-900' : 'text-gray-400'}">
                  {displayVoteScore(result.question)}
                </div>
              </div>
              <div class="flex-1 min-w-0">
                <h3 class="text-sm font-medium text-indigo-700">{result.question.title}</h3>
                <p class="text-xs text-gray-500 mt-1 line-clamp-2">{result.question.body}</p>
                <div class="flex items-center gap-2 mt-2 text-xs text-gray-400">
                  <span>{result.answers.length} answer{result.answers.length !== 1 ? 's' : ''}</span>
                  <span>·</span>
                  <span>{result.question.created_by}</span>
                  <span>·</span>
                  <span>{timeAgo(result.question.created_at)}</span>
                </div>
              </div>
            </div>
          </a>
        {/each}
      </div>
    {/if}
  </div>
</div>
