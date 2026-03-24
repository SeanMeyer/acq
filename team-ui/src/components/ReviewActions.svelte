<script lang="ts">
  let {
    onApprove,
    onReject,
    onSkip,
    disabled = false,
  }: {
    onApprove: () => void;
    onReject: () => void;
    onSkip: () => void;
    disabled?: boolean;
  } = $props();

  type Selection = 'approve' | 'reject' | null;
  let selected = $state<Selection>(null);

  function select(action: 'approve' | 'reject') {
    if (selected === action) {
      confirm_action();
    } else {
      selected = action;
    }
  }

  function confirm_action() {
    if (selected === 'approve') onApprove();
    else if (selected === 'reject') onReject();
    selected = null;
  }

  function cancel() {
    selected = null;
  }

  function handleKeydown(e: KeyboardEvent) {
    if (disabled) return;
    if (e.key === 'ArrowLeft') { e.preventDefault(); select('reject'); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); select('approve'); }
    else if (e.key === 'ArrowUp' || e.key === 'ArrowDown' || e.key === 's' || e.key === 'S') {
      e.preventDefault();
      selected = null;
      onSkip();
    }
    else if ((e.key === ' ' || e.key === 'Enter') && selected) {
      e.preventDefault();
      confirm_action();
    }
    else if (e.key === 'Escape') {
      e.preventDefault();
      cancel();
    }
  }
</script>

<svelte:window onkeydown={handleKeydown} />

<div class="flex flex-col items-center gap-3">
  <div class="flex items-center gap-3">
    <!-- Reject -->
    <button
      onclick={() => select('reject')}
      {disabled}
      class="flex items-center gap-2 px-5 py-3 rounded-xl font-medium text-sm transition-all
        {selected === 'reject'
          ? 'bg-red-600 text-white shadow-lg scale-105 ring-2 ring-red-400'
          : 'bg-red-100 text-red-700 hover:bg-red-200 hover:scale-105'}
        disabled:opacity-40 disabled:cursor-not-allowed"
    >
      <svg class="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
        <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd" />
      </svg>
      {selected === 'reject' ? 'Confirm reject' : 'Reject'}
    </button>

    <!-- Skip -->
    <button
      onclick={() => { selected = null; onSkip(); }}
      {disabled}
      class="flex items-center gap-2 px-5 py-3 rounded-xl font-medium text-sm transition-all
        bg-gray-100 text-gray-600 hover:bg-gray-200 hover:scale-105
        disabled:opacity-40 disabled:cursor-not-allowed"
    >
      <svg class="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM7 9a1 1 0 000 2h6a1 1 0 100-2H7z" clip-rule="evenodd" />
      </svg>
      Skip
    </button>

    <!-- Approve -->
    <button
      onclick={() => select('approve')}
      {disabled}
      class="flex items-center gap-2 px-5 py-3 rounded-xl font-medium text-sm transition-all
        {selected === 'approve'
          ? 'bg-green-600 text-white shadow-lg scale-105 ring-2 ring-green-400'
          : 'bg-green-100 text-green-700 hover:bg-green-200 hover:scale-105'}
        disabled:opacity-40 disabled:cursor-not-allowed"
    >
      <svg class="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
        <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
      </svg>
      {selected === 'approve' ? 'Confirm approve' : 'Approve'}
    </button>
  </div>

  <p class="text-xs text-gray-400">
    {#if selected}
      Click again or press <kbd class="px-1 py-0.5 bg-gray-100 rounded text-gray-600 font-mono text-xs">Space</kbd> /
      <kbd class="px-1 py-0.5 bg-gray-100 rounded text-gray-600 font-mono text-xs">Enter</kbd> to confirm ·
      <kbd class="px-1 py-0.5 bg-gray-100 rounded text-gray-600 font-mono text-xs">Esc</kbd> to cancel
    {:else}
      <kbd class="px-1 py-0.5 bg-gray-100 rounded text-gray-600 font-mono text-xs">←</kbd> reject ·
      <kbd class="px-1 py-0.5 bg-gray-100 rounded text-gray-600 font-mono text-xs">S</kbd> skip ·
      <kbd class="px-1 py-0.5 bg-gray-100 rounded text-gray-600 font-mono text-xs">→</kbd> approve
    {/if}
  </p>
</div>
