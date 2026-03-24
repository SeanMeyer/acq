import { writable } from 'svelte/store';

interface AuthState {
  isAuthenticated: boolean;
  username: string | null;
}

function createAuth() {
  // Safe to call only in browser context; SSR will get empty state
  const isBrowser = typeof localStorage !== 'undefined';
  const token = isBrowser ? localStorage.getItem('acq_token') : null;
  let username: string | null = null;

  if (token) {
    try {
      const payload = JSON.parse(atob(token.split('.')[1]));
      username = payload.sub ?? 'user';
    } catch {
      // Malformed token — treat as unauthenticated
    }
  }

  const { subscribe, set } = writable<AuthState>({
    isAuthenticated: !!token,
    username,
  });

  return {
    subscribe,
    login(token: string, user: string) {
      localStorage.setItem('acq_token', token);
      set({ isAuthenticated: true, username: user });
    },
    logout() {
      localStorage.removeItem('acq_token');
      set({ isAuthenticated: false, username: null });
    },
  };
}

export const auth = createAuth();
