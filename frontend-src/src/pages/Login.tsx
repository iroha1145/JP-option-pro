/**
 * 登录 / 注册 — 与美股版共用的账号体系。
 * 用户名 admin = 所有者（APP_PASSWORD_HASH）；其他用户名 = 访客账号（共享 accounts.db，
 * 同一账号在美股/日股两个站点通用）。注册走 /api/account/register。
 */
import { useState } from 'react';
import { useNavigate } from 'react-router';
import { useAccess } from '@/hooks/useAccess';
import { accountApi } from '@/api/modules';
import { ApiError } from '@/api/client';
import { t } from '@/i18n/core';

export default function Login() {
  const { login, refresh } = useAccess();
  const navigate = useNavigate();
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      if (mode === 'register') {
        await accountApi.register(username.trim(), password);
        await refresh();
      } else {
        await login(password, username.trim() || 'admin');
      }
      navigate('/', { replace: true });
    } catch (err) {
      const apiError = err as ApiError;
      if (apiError.bizCode === 'https_required') setError(t('登录需要 HTTPS'));
      else if (apiError.bizCode === 'login_cooldown') setError(t('尝试过于频繁，请稍后再试'));
      else if (apiError.bizCode === 'username_taken') setError(t('该用户名已被占用'));
      else if (apiError.bizCode === 'username_reserved') setError(t('该用户名已被保留，请换一个'));
      else if (apiError.bizCode === 'registration_rate_limited') setError(t('注册过于频繁，请稍后再试'));
      else if (mode === 'register') setError(apiError.message || t('注册失败'));
      else setError(t('用户名或密码不正确'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-paper px-4">
      <form
        className="card-surface w-full max-w-sm rounded-xl p-6 shadow-sh-2"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <div className="mb-5 flex items-baseline gap-2">
          <span className="font-display text-display-m font-semibold text-ink-900">Optix</span>
          <span className="rounded-sm bg-brand-600 px-1.5 py-0.5 text-micro font-bold uppercase tracking-wider text-white">
            Japan
          </span>
        </div>

        <div className="mb-4 flex rounded-md border border-line bg-card-warm p-0.5">
          {(['login', 'register'] as const).map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => {
                setMode(value);
                setError(null);
              }}
              className={
                mode === value
                  ? 'flex-1 rounded-[6px] bg-card px-3 py-1.5 text-caption font-medium text-ink-800 shadow-sh-1'
                  : 'flex-1 rounded-[6px] px-3 py-1.5 text-caption text-ink-400 hover:text-ink-600'
              }
            >
              {value === 'login' ? t('登录') : t('注册新账号')}
            </button>
          ))}
        </div>

        <label className="mb-1 block text-caption text-ink-500" htmlFor="login-username">
          {t('用户名')}
        </label>
        <input
          id="login-username"
          autoComplete="username"
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          placeholder={mode === 'login' ? 'admin' : t('新用户名')}
          maxLength={32}
          className="mb-3 w-full rounded-md border border-line bg-card px-3 py-2 text-body text-ink-900 outline-none focus-ring"
        />
        <label className="mb-1 block text-caption text-ink-500" htmlFor="login-password">
          {t('密码')}
        </label>
        <input
          id="login-password"
          type="password"
          autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className="mb-3 w-full rounded-md border border-line bg-card px-3 py-2 text-body text-ink-900 outline-none focus-ring"
        />
        {error && <p className="mb-3 text-body-s text-down-700">{error}</p>}
        <button
          type="submit"
          disabled={busy || password.length === 0 || (mode === 'register' && username.trim().length === 0)}
          className="w-full rounded-md bg-brand-600 py-2 text-body font-medium text-white transition-opacity disabled:opacity-50"
        >
          {mode === 'login' ? t('登录') : t('注册并登录')}
        </button>
        <p className="mt-3 text-center text-caption text-ink-400">
          {mode === 'login'
            ? t('账号与美股版通用 · admin 为所有者')
            : t('注册的账号在美股/日股两个站点通用')}
        </p>
      </form>
    </div>
  );
}
