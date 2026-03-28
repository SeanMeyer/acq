<script lang="ts">
  import '../app.css';
  import { goto, afterNavigate } from '$app/navigation';
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import { auth } from '$lib/auth';
  import { api } from '$lib/api';

  let { children } = $props();

  let pendingCount = $state(0);
  let refreshInterval: ReturnType<typeof setInterval> | null = null;
  let searchQuery = $state('');

  const isLoginPage = $derived($page.url.pathname === '/login');

  async function fetchPendingCount() {
    if (!$auth.isAuthenticated) return;
    try {
      const stats = await api.reviewStats();
      pendingCount = stats.total_pending ?? 0;
    } catch {
      // silently ignore — badge is non-critical
    }
  }

  $effect(() => {
    if (!$auth.isAuthenticated && !isLoginPage) {
      goto('/login');
    }
  });

  $effect(() => {
    if ($auth.isAuthenticated) {
      fetchPendingCount();
      refreshInterval = setInterval(fetchPendingCount, 30_000);
    }
    return () => {
      if (refreshInterval) clearInterval(refreshInterval);
    };
  });

  // Refresh badge count after each navigation (e.g., after reviewing items)
  afterNavigate(() => {
    if ($auth.isAuthenticated) fetchPendingCount();
  });

  function handleLogout() {
    auth.logout();
    goto('/login');
  }
</script>

{#if !isLoginPage && $auth.isAuthenticated}
  <nav class="bg-white border-b border-gray-200 sticky top-0 z-40">
    <div class="max-w-5xl mx-auto px-4 sm:px-6">
      <div class="flex items-center justify-between h-14">
        <!-- Logo -->
        <a href="/review" class="text-lg font-bold text-indigo-700 tracking-tight hover:text-indigo-900 transition-colors">
          acq
        </a>

        <!-- Nav links -->
        <div class="flex items-center gap-1">
          <a
            href="/review"
            data-sveltekit-preload-data="hover"
            class="relative flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors
              {$page.url.pathname.startsWith('/review')
                ? 'bg-indigo-50 text-indigo-700'
                : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'}"
          >
            Review
            {#if pendingCount > 0}
              <span class="inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1 rounded-full text-xs font-bold bg-indigo-600 text-white">
                {pendingCount > 99 ? '99+' : pendingCount}
              </span>
            {/if}
          </a>
          <a
            href="/questions"
            data-sveltekit-preload-data="hover"
            class="px-3 py-1.5 rounded-lg text-sm font-medium transition-colors
              {$page.url.pathname.startsWith('/questions')
                ? 'bg-indigo-50 text-indigo-700'
                : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'}"
          >
            Questions
          </a>
          <a
            href="/dashboard"
            data-sveltekit-preload-data="hover"
            class="px-3 py-1.5 rounded-lg text-sm font-medium transition-colors
              {$page.url.pathname.startsWith('/dashboard')
                ? 'bg-indigo-50 text-indigo-700'
                : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'}"
          >
            Dashboard
          </a>
        </div>

        <!-- Search + User section -->
        <div class="flex items-center gap-3">
          <form
            onsubmit={(e) => { e.preventDefault(); if (searchQuery.trim()) { goto(`/search?q=${encodeURIComponent(searchQuery.trim())}`); searchQuery = ''; } }}
            class="hidden sm:block"
          >
            <input
              type="text"
              bind:value={searchQuery}
              placeholder="Search..."
              class="w-36 px-2.5 py-1 text-sm bg-gray-50 border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-indigo-500 focus:w-48 transition-all"
            />
          </form>
        </div>
        <div class="flex items-center gap-3">
          {#if $auth.username}
            <span class="text-sm text-gray-500 hidden sm:block">{$auth.username}</span>
          {/if}
          <button
            onclick={handleLogout}
            class="text-sm text-gray-500 hover:text-gray-900 transition-colors"
          >
            Logout
          </button>
        </div>
      </div>
    </div>
  </nav>
{/if}

{@render children()}
