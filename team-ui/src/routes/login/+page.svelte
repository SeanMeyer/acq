<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import { auth } from '$lib/auth';
  import { setToken } from '$lib/api';

  let error = $state('');

  const API_BASE = import.meta.env.VITE_API_BASE || '';

  onMount(() => {
    // Handle redirect from GitHub OAuth callback — backend passes JWT as ?token=
    const token = $page.url.searchParams.get('token');
    if (token) {
      try {
        const payload = JSON.parse(atob(token.split('.')[1]));
        const username = payload.sub ?? 'user';
        setToken(token);
        auth.login(token, username);
        goto('/review');
      } catch {
        error = 'Invalid token received. Please try again.';
      }
    }
  });
</script>

<div class="min-h-screen bg-gray-50 flex items-center justify-center px-4">
  <div class="w-full max-w-sm">
    <!-- Logo / heading -->
    <div class="text-center mb-8">
      <h1 class="text-3xl font-bold text-indigo-700 tracking-tight">acq</h1>
      <p class="mt-2 text-sm text-gray-500">Accrue — shared Q&A knowledge commons</p>
    </div>

    <div class="bg-white rounded-2xl shadow-sm border border-gray-200 px-8 py-8">
      {#if error}
        <div class="rounded-lg bg-red-50 border border-red-200 px-4 py-3 mb-5">
          <p class="text-sm text-red-700">{error}</p>
        </div>
      {/if}

      <a
        href="{API_BASE}/auth/github"
        class="w-full flex items-center justify-center gap-3 px-4 py-2.5 rounded-lg
          bg-gray-900 hover:bg-gray-800 text-white text-sm font-medium
          transition-colors no-underline"
      >
        <svg class="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/>
        </svg>
        Sign in with GitHub
      </a>

      <p class="mt-4 text-xs text-center text-gray-400">
        Authenticate with your GitHub account to review Q&A entries.
      </p>
    </div>
  </div>
</div>
