import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  type ReactNode,
} from "react";
import { api, setToken, getToken, setOnUnauthorized } from "./api";

interface AuthState {
  username: string | null;
  isAuthenticated: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  // Restore session from localStorage if a token exists
  const [username, setUsername] = useState<string | null>(() => {
    const saved = getToken();
    if (saved) {
      // We have a token but not a username — extract from JWT payload
      try {
        const payload = JSON.parse(atob(saved.split(".")[1]));
        return payload.sub ?? "user";
      } catch {
        return null;
      }
    }
    return null;
  });

  const login = useCallback(async (user: string, pass: string) => {
    const resp = await api.login(user, pass);
    setToken(resp.token);
    setUsername(resp.username);
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    setUsername(null);
  }, []);

  // Register 401 handler so any API call that gets 401 triggers logout.
  useEffect(() => {
    setOnUnauthorized(logout);
    return () => setOnUnauthorized(() => {});
  }, [logout]);

  return (
    <AuthContext.Provider
      value={{ username, isAuthenticated: !!username, login, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components -- Standard React context pattern: provider + hook exported together.
export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
