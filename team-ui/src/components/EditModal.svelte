<script lang="ts">
  import { untrack } from 'svelte';

  let {
    title,
    initialBody,
    initialTitle,
    initialTags,
    onSave,
    onClose,
  }: {
    title: string;
    initialBody: string;
    initialTitle?: string;
    initialTags?: string[];
    onSave: (patch: { body: string; title?: string; tags?: string[] }) => Promise<void>;
    onClose: () => void;
  } = $props();

  const editTitle = $derived(initialTitle !== undefined);
  const editTags = $derived(initialTags !== undefined);

  // The modal owns the edit buffer independently from the parent prop.
  // untrack breaks the reactive chain so Svelte won't warn about stale capture.
  let body = $state(untrack(() => initialBody));
  let titleValue = $state(untrack(() => initialTitle ?? ''));
  let tagsValue = $state(untrack(() => (initialTags ?? []).join(', ')));
  let saving = $state(false);
  let error = $state('');

  async function handleSave() {
    saving = true;
    error = '';
    try {
      const patch: { body: string; title?: string; tags?: string[] } = { body };
      if (editTitle) patch.title = titleValue;
      if (editTags) {
        patch.tags = tagsValue
          .split(',')
          .map((t) => t.trim())
          .filter((t) => t.length > 0);
      }
      await onSave(patch);
      onClose();
    } catch (e) {
      error = e instanceof Error ? e.message : 'Save failed';
    } finally {
      saving = false;
    }
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') onClose();
  }
</script>

<svelte:window onkeydown={handleKeydown} />

<!-- Backdrop -->
<div
  class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
  role="dialog"
  aria-modal="true"
>
  <!-- Click outside to close -->
  <button
    class="absolute inset-0 w-full h-full cursor-default"
    onclick={onClose}
    aria-label="Close modal"
  ></button>

  <!-- Modal panel -->
  <div class="relative z-10 bg-white rounded-xl shadow-2xl w-full max-w-2xl mx-4 flex flex-col">
    <div class="flex items-center justify-between px-6 py-4 border-b border-gray-200">
      <h2 class="text-lg font-semibold text-gray-900">{title}</h2>
      <button
        onclick={onClose}
        class="text-gray-400 hover:text-gray-600 transition-colors"
        aria-label="Close"
      >
        <svg class="w-5 h-5" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
        </svg>
      </button>
    </div>

    <div class="px-6 py-4 space-y-3">
      {#if editTitle}
        <div>
          <label class="block text-xs font-medium text-gray-500 mb-1" for="edit-modal-title">Title</label>
          <input
            id="edit-modal-title"
            type="text"
            bind:value={titleValue}
            class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            placeholder="Question title..."
          />
        </div>
      {/if}
      <textarea
        bind:value={body}
        rows={12}
        class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono text-gray-900 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent resize-y"
        placeholder="Content body..."
      ></textarea>
      {#if editTags}
        <div>
          <label class="block text-xs font-medium text-gray-500 mb-1" for="edit-modal-tags">Tags</label>
          <input
            id="edit-modal-tags"
            type="text"
            bind:value={tagsValue}
            class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            placeholder="comma, separated, tags"
          />
          <p class="mt-1 text-xs text-gray-400">Comma-separated. Saving replaces the full tag set.</p>
        </div>
      {/if}
      {#if error}
        <p class="text-sm text-red-600">{error}</p>
      {/if}
    </div>

    <div class="flex justify-end gap-3 px-6 py-4 border-t border-gray-200">
      <button
        onclick={onClose}
        disabled={saving}
        class="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
      >
        Cancel
      </button>
      <button
        onclick={handleSave}
        disabled={saving}
        class="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 transition-colors disabled:opacity-50 flex items-center gap-2"
      >
        {#if saving}
          <svg class="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          Saving…
        {:else}
          Save
        {/if}
      </button>
    </div>
  </div>
</div>
