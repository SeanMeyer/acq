<script lang="ts">
  import type { Tag } from '$lib/types';
  import { api } from '$lib/api';

  let {
    tags,
    onMerged,
  }: {
    tags: Tag[];
    onMerged?: () => void;
  } = $props();

  let expanded = $state(false);
  let mergingTagId = $state<string | null>(null);
  let mergeTargetId = $state<string>('');
  let merging = $state(false);
  let mergeError = $state('');

  function startMerge(tagId: string) {
    mergingTagId = tagId;
    mergeTargetId = '';
    mergeError = '';
  }

  function cancelMerge() {
    mergingTagId = null;
    mergeTargetId = '';
    mergeError = '';
  }

  async function confirmMerge() {
    if (!mergingTagId || !mergeTargetId) return;
    merging = true;
    mergeError = '';
    try {
      await api.mergeTags(mergingTagId, mergeTargetId);
      mergingTagId = null;
      mergeTargetId = '';
      onMerged?.();
    } catch (e) {
      mergeError = e instanceof Error ? e.message : 'Merge failed';
    } finally {
      merging = false;
    }
  }

  const otherTags = $derived(tags.filter(t => t.id !== mergingTagId));
</script>

<div class="bg-white rounded-xl border border-gray-200 overflow-hidden">
  <button
    onclick={() => (expanded = !expanded)}
    class="w-full flex items-center justify-between px-5 py-4 hover:bg-gray-50 transition-colors"
  >
    <div class="flex items-center gap-2">
      <svg class="w-4 h-4 text-gray-500" viewBox="0 0 20 20" fill="currentColor">
        <path fill-rule="evenodd" d="M17.707 9.293a1 1 0 010 1.414l-7 7a1 1 0 01-1.414 0l-7-7A.997.997 0 012 10V5a3 3 0 013-3h5c.256 0 .512.098.707.293l7 7zM5 6a1 1 0 100-2 1 1 0 000 2z" clip-rule="evenodd" />
      </svg>
      <h3 class="text-sm font-semibold text-gray-900">Tag Manager</h3>
      <span class="text-xs text-gray-500">({tags.length} tags)</span>
    </div>
    <svg
      class="w-4 h-4 text-gray-400 transition-transform {expanded ? 'rotate-180' : ''}"
      viewBox="0 0 20 20"
      fill="currentColor"
    >
      <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd" />
    </svg>
  </button>

  {#if expanded}
    <div class="border-t border-gray-100 divide-y divide-gray-50">
      {#each tags as tag}
        <div class="px-5 py-3 flex items-center justify-between gap-3">
          <div class="flex items-center gap-2">
            <span class="text-sm font-medium text-gray-800">{tag.name}</span>
            <span class="text-xs text-gray-400">{tag.usage_count} uses</span>
          </div>

          {#if mergingTagId === tag.id}
            <div class="flex items-center gap-2">
              <select
                bind:value={mergeTargetId}
                class="text-xs border border-gray-300 rounded px-2 py-1 text-gray-700 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              >
                <option value="">Merge into…</option>
                {#each otherTags as other}
                  <option value={other.id}>{other.name}</option>
                {/each}
              </select>
              <button
                onclick={confirmMerge}
                disabled={!mergeTargetId || merging}
                class="text-xs px-2 py-1 bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-40 transition-colors"
              >
                {merging ? '…' : 'Merge'}
              </button>
              <button
                onclick={cancelMerge}
                class="text-xs px-2 py-1 text-gray-500 hover:text-gray-700 transition-colors"
              >
                Cancel
              </button>
            </div>
          {:else}
            <button
              onclick={() => startMerge(tag.id)}
              class="text-xs text-gray-400 hover:text-indigo-600 transition-colors"
            >
              Merge into…
            </button>
          {/if}
        </div>
        {#if mergingTagId === tag.id && mergeError}
          <p class="px-5 pb-2 text-xs text-red-600">{mergeError}</p>
        {/if}
      {/each}
    </div>
  {/if}
</div>
