import { useState } from 'react';
import { useNavigate } from 'react-router';
import { useAccess } from '@/hooks/useAccess';
import { ApiError } from '@/api/client';
import { t } from '@/i18n/core';

export default function Login() {
  const { login } = useAccess();
  const navigate = useNavigate();
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  return (
    <div className="flex min-h-screen items-center justify-center bg-paper px-4">
      <form
        className="card-surface w-full max-w-sm rounded-xl p-6 shadow-sh-2"
        onSubmit={async (event) => {
          event.preventDefault();
          setBusy(true);
          setError(null);
          try {
            await login(password);
            navigate('/', { replace: true });
          } catch (err) {
            const apiError = err as ApiError;
            if (apiError.bizCode === 'https_required') setError(t('登录需要 HTTPS'));
            else if (apiError.bizCode === 'login_cooldown') setError(t('尝试过于频繁，请稍后再试'));
            else setError(t('密码错误'));
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="mb-5 flex items-baseline gap-2">
          <span className="font-display text-display-m font-semibold text-ink-900">Optix</span>
          <span className="rounded-sm bg-brand-600 px-1.5 py-0.5 text-micro font-bold uppercase tracking-wider text-white">
            Japan
          </span>
        </div>
        <label className="mb-1 block text-caption text-ink-500" htmlFor="owner-password">
          {t('所有者密码')}
        </label>
        <input
          id="owner-password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className="mb-3 w-full rounded-md border border-line bg-card px-3 py-2 text-body text-ink-900 outline-none focus-ring"
        />
        {error && <p className="mb-3 text-body-s text-down-700">{error}</p>}
        <button
          type="submit"
          disabled={busy || password.length === 0}
          className="w-full rounded-md bg-brand-600 py-2 text-body font-medium text-white transition-opacity disabled:opacity-50"
        >
          {t('登录')}
        </button>
        <p className="mt-3 text-center text-caption text-ink-400">{t('访客只读模式')}</p>
      </form>
    </div>
  );
}
