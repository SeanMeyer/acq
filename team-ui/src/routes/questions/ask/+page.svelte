<script lang="ts">
  import { onMount } from 'svelte';
  import { goto, invalidateAll } from '$app/navigation';
  import { api } from '$lib/api';

  let title = $state('');
  let body = $state('');
  let selectedTags = $state<string[]>([]);
  let tagInput = $state('');
  let allTags = $state.raw<{ name: string; usage_count: number }[]>([]);
  let submitting = $state(false);
  let error = $state('');

  const suggestions = $derived(
    tagInput.trim()
      ? allTags
          .filter(t => t.name.toLowerCase().includes(tagInput.trim().toLowerCase()))
          .filter(t => !selectedTags.includes(t.name))
          .slice(0, 8)
      : []
  );

  onMount(async () => {
    try {
      allTags = await api.listTags();
    } catch {
      // non-critical
    }
  });

  function addTag(name: string) {
    const n = name.trim().toLowerCase();
    if (n && !selectedTags.includes(n)) {
      selectedTags = [...selectedTags, n];
    }
    tagInput = '';
  }

  function removeTag(name: string) {
    selectedTags = selectedTags.filter(t => t !== name);
  }

  function handleTagKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      if (tagInput.trim()) addTag(tagInput);
    }
    if (e.key === 'Backspace' && !tagInput && selectedTags.length > 0) {
      selectedTags = selectedTags.slice(0, -1);
    }
  }

  async function handleSubmit(e: Event) {
    e.preventDefault();
    if (!title.trim() || !body.trim() || submitting) return;
    submitting = true;
    error = '';
    try {
      const res = await api.createQuestion(title.trim(), body.trim(), selectedTags);
      await invalidateAll();
      goto(`/questions/${res.question.id}`);
    } catch (err: any) {
      error = err instanceof Error ? err.message : 'Failed to post question';
    } finally {
      submitting = false;
    }
  }
</script>

<div class="min-h-screen bg-gray-50">
  <div class="max-w-3xl mx-auto px-4 py-8">
    <a href="/questions" data-sveltekit-preload-data="hover" class="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-indigo-600 mb-6 transition-colors">
      <svg class="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
        <path fill-rule="evenodd" d="M9.707 16.707a1 1 0 01-1.414 0l-6-6a1 1 0 010-1.414l6-6a1 1 0 011.414 1.414L5.414 9H17a1 1 0 110 2H5.414l4.293 4.293a1 1 0 010 1.414z" clip-rule="evenodd" />
      </svg>
      Back to Questions
    </a>

    <h1 class="text-xl font-bold text-gray-900 mb-6">Ask a Question</h1>

    <form onsubmit={handleSubmit} class="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
      <div>
        <label for="title" class="block text-sm font-medium text-gray-700 mb-1">Title</label>
        <input
          id="title"
          type="text"
          bind:value={title}
          placeholder="What's your question? Be specific."
          class="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
        />
      </div>

      <div>
        <label for="body" class="block text-sm font-medium text-gray-700 mb-1">Body</label>
        <textarea
          id="body"
          bind:value={body}
          placeholder="Include all the information someone would need to answer your question. Markdown supported."
          rows="8"
          class="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent resize-y"
        ></textarea>
      </div>

      <div>
        <label for="tags" class="block text-sm font-medium text-gray-700 mb-1">Tags</label>
        <div class="flex flex-wrap items-center gap-1.5 px-3 py-2 border border-gray-200 rounded-lg focus-within:ring-2 focus-within:ring-indigo-500 focus-within:border-transparent">
          {#each selectedTags as tag (tag)}
            <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-indigo-50 text-indigo-700">
              {tag}
              <button type="button" onclick={() => removeTag(tag)} class="hover:text-red-500" title="Remove tag">
                <svg class="w-3 h-3" viewBox="0 0 20 20" fill="currentColor">
                  <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
                </svg>
              </button>
            </span>
          {/each}
          <input
            id="tags"
            type="text"
            bind:value={tagInput}
            onkeydown={handleTagKeydown}
            placeholder={selectedTags.length === 0 ? 'Type to add tags...' : ''}
            class="flex-1 min-w-[120px] text-sm border-0 outline-none p-0 focus:ring-0"
          />
        </div>
        {#if suggestions.length > 0}
          <div class="mt-1 border border-gray-200 rounded-lg bg-white shadow-sm overflow-hidden">
            {#each suggestions as tag (tag.name)}
              <button
                type="button"
                onclick={() => addTag(tag.name)}
                class="w-full text-left px-3 py-1.5 text-sm hover:bg-indigo-50 transition-colors flex items-center justify-between"
              >
                <span class="text-gray-700">{tag.name}</span>
                <span class="text-xs text-gray-400">{tag.usage_count} uses</span>
              </button>
            {/each}
          </div>
        {/if}
      </div>

      {#if error}
        <div class="rounded-lg bg-red-50 border border-red-200 px-4 py-3">
          <p class="text-sm text-red-700">{error}</p>
        </div>
      {/if}

      <div class="flex justify-end pt-2">
        <button
          type="submit"
          disabled={!title.trim() || !body.trim() || submitting}
          class="px-4 py-2 text-sm font-medium rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {submitting ? 'Posting...' : 'Post Question'}
        </button>
      </div>
    </form>
  </div>
</div>
