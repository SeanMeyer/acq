<script lang="ts">
  import { goto } from '$app/navigation';
  import { api } from '$lib/api';
  import { auth } from '$lib/auth';

  let username = $state('');
  let password = $state('');
  let error = $state('');
  let loading = $state(false);

  async function handleSubmit(e: SubmitEvent) {
    e.preventDefault();
    error = '';
    loading = true;
    try {
      const res = await api.login(username, password);
      auth.login(res.token, res.username);
      goto('/review');
    } catch (e_) {
      error = e_ instanceof Error ? e_.message : 'Login failed. Check your credentials.';
    } finally {
      loading = false;
    }
  }
</script>

<div class="min-h-screen bg-gray-50 flex items-center justify-center px-4">
  <div class="w-full max-w-sm">
    <!-- Logo / heading -->
    <div class="text-center mb-8">
      <h1 class="text-3xl font-bold text-indigo-700 tracking-tight">acq</h1>
      <p class="mt-2 text-sm text-gray-500">Q&A knowledge commons · review dashboard</p>
    </div>

    <div class="bg-white rounded-2xl shadow-sm border border-gray-200 px-8 py-8">
      <form onsubmit={handleSubmit} class="space-y-5">
        <div>
          <label for="username" class="block text-sm font-medium text-gray-700 mb-1.5">
            Username
          </label>
          <input
            id="username"
            type="text"
            bind:value={username}
            required
            autocomplete="username"
            class="w-full px-3 py-2.5 rounded-lg border border-gray-300 text-sm text-gray-900
              placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500
              focus:border-transparent transition"
            placeholder="your username"
          />
        </div>

        <div>
          <label for="password" class="block text-sm font-medium text-gray-700 mb-1.5">
            Password
          </label>
          <input
            id="password"
            type="password"
            bind:value={password}
            required
            autocomplete="current-password"
            class="w-full px-3 py-2.5 rounded-lg border border-gray-300 text-sm text-gray-900
              placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500
              focus:border-transparent transition"
            placeholder="••••••••"
          />
        </div>

        {#if error}
          <div class="rounded-lg bg-red-50 border border-red-200 px-4 py-3">
            <p class="text-sm text-red-700">{error}</p>
          </div>
        {/if}

        <button
          type="submit"
          disabled={loading}
          class="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg
            bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium
            transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {#if loading}
            <svg class="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            Signing in…
          {:else}
            Sign in
          {/if}
        </button>
      </form>
    </div>
  </div>
</div>
