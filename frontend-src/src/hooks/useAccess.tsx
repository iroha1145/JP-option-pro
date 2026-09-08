/**
 * 访问上下文（单主体版）：visitor | owner。
 * 身份变化时清空共享查询注册表，防止跨主体数据残留。
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { accessApi, accountApi } from '@/api/modules';
import { PRINCIPAL_INVALID_EVENT } from '@/api/client';
import { dropQueryRegistry, setQueryPrincipal } from '@/api/queryRegistry';
import type { AccessStatus } from '@/api/types';

interface AccessContextValue {
  status: AccessStatus | null;
  isOwner: boolean;
  mode: 'private_network' | 'password' | null;
  /** 访客账号（与美股版共库；不含任何 owner 权限）。 */
  accountUsername: string | null;
  /** 任一主体已登录（Owner 或访客账号）。 */
  isSignedIn: boolean;
  /** 显示用用户名：Owner 为 admin，访客为账号名。 */
  username: string | null;
  isCustomer: boolean;
  loading: boolean;
  /** 自选可写主体：owner 或已登录的访客账号。 */
  canManageWatchlist: boolean;
  identityUnavailable: boolean;
  refresh: () => Promise<void>;
  login: (password: string, username?: string) => Promise<void>;
  register: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AccessContext = createContext<AccessContextValue | null>(null);

export function AccessProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AccessStatus | null>(null);
  const [identityUnavailable, setIdentityUnavailable] = useState(false);
  const generationRef = useRef(0);
  const lastPrincipalRef = useRef<string>('unknown');

  const applyStatus = useCallback((next: AccessStatus | null) => {
    if (next) {
      const principal = next.is_owner
        ? 'owner'
        : next.account?.logged_in
          ? `account:${next.account.username ?? ''}`
          : 'visitor';
      if (lastPrincipalRef.current !== principal) {
        lastPrincipalRef.current = principal;
        setQueryPrincipal(principal);
        void dropQueryRegistry();
      }
    }
    setStatus(next);
  }, []);

  const refresh = useCallback(async () => {
    const generation = ++generationRef.current;
    try {
      const next = await accessApi.status();
      if (generation === generationRef.current) {
        applyStatus(next);
        setIdentityUnavailable(false);
      }
    } catch {
      if (generation === generationRef.current) setIdentityUnavailable(true);
    }
  }, [applyStatus]);

  useEffect(() => {
    void refresh();
    const onVisible = () => {
      if (document.visibilityState === 'visible') void refresh();
    };
    const onPrincipalInvalid = () => void refresh();
    document.addEventListener('visibilitychange', onVisible);
    window.addEventListener(PRINCIPAL_INVALID_EVENT, onPrincipalInvalid);
    const timer = window.setInterval(() => void refresh(), 60_000);
    return () => {
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener(PRINCIPAL_INVALID_EVENT, onPrincipalInvalid);
      window.clearInterval(timer);
    };
  }, [refresh]);

  const login = useCallback(
    async (password: string, username = 'admin') => {
      await accessApi.login(password, username);
      await refresh();
    },
    [refresh],
  );

  const register = useCallback(
    async (username: string, password: string) => {
      await accountApi.register(username, password);
      await refresh();
    },
    [refresh],
  );

  const logout = useCallback(async () => {
    await accessApi.logout();
    await refresh();
  }, [refresh]);

  const isOwner = Boolean(status?.is_owner);
  const accountUsername = status?.account?.logged_in ? (status.account.username ?? null) : null;
  const isCustomer = Boolean(!isOwner && accountUsername);
  const isSignedIn = isOwner || isCustomer;

  const value = useMemo<AccessContextValue>(
    () => ({
      status,
      isOwner,
      mode: status?.mode ?? null,
      accountUsername,
      isSignedIn,
      username: isOwner ? 'admin' : accountUsername,
      isCustomer,
      loading: status === null && !identityUnavailable,
      canManageWatchlist: isSignedIn,
      identityUnavailable,
      refresh,
      login,
      register,
      logout,
    }),
    [status, isOwner, accountUsername, isSignedIn, isCustomer, identityUnavailable, refresh, login, register, logout],
  );

  return <AccessContext.Provider value={value}>{children}</AccessContext.Provider>;
}

export function useAccess(): AccessContextValue {
  const context = useContext(AccessContext);
  if (!context) throw new Error('useAccess must be used inside AccessProvider');
  return context;
}
