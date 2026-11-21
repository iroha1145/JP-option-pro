/** 登录和注册页：沿用美国站外观，保留日本站账号与来源返回逻辑。 */
import { useState, type FormEvent } from 'react';
import { Link, useLocation, useNavigate } from 'react-router';
import { useAccess } from '@/hooks/useAccess';
import { ApiError } from '@/api/client';
import { useToast } from '@/hooks/useToast';
import { cn } from '@/lib/utils';
import { useCatalogShake } from '@/lib/transitions';
import Icon from '@/components/icons';
import DotsLoader from '@/components/shared/DotsLoader';
import Segmented from '@/components/shared/Segmented';
import ThemeSwitcher from '@/components/ThemeSwitcher';
import type { IconName } from '@/components/icons';
import { t } from '@/i18n/core';

const FEATURES: { icon: IconName; title: string }[] = [
  { icon: 'radar', title: '日线全市场扫描' },
  { icon: 'layers', title: '行业强弱与广度' },
  { icon: 'doc-quote', title: '新闻原文与来源' },
];

/* ---------------- 眼睛切换（手绘细线，与图标库同工艺） ---------------- */
function EyeIcon({ off }: { off?: boolean }) {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M2.8 12S6.2 5.8 12 5.8 21.2 12 21.2 12 17.8 18.2 12 18.2 2.8 12 2.8 12Z" />
      <circle cx="12" cy="12" r="2.6" />
      {off && <path d="M4.5 19.5 19.5 4.5" />}
    </svg>
  );
}

/* ---------------- 页面 ---------------- */
type SubmitState = 'idle' | 'verifying' | 'success' | 'error';

export default function Login() {
  const navigate = useNavigate();
  const {
    login,
    register,
    isOwner,
    isCustomer,
    mode: accessMode,
    username: signedInName,
    logout,
    loading,
    identityUnavailable: serviceDown,
    refresh: probeService,
  } = useAccess();
  const location = useLocation();
  /* 从别处「去登录」带来的来源页（#21）：登录成功回到出发点而不是固定 /watchlist */
  const fromPath = (location.state as { from?: string } | null)?.from ?? null;
  const toast = useToast();

  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [capsLock, setCapsLock] = useState(false);
  const [state, setState] = useState<SubmitState>('idle');
  const [statusMsg, setStatusMsg] = useState<{ text: string; tone: 'error' | 'warn' } | null>(null);
  /* catalog 12 一个实例管一块字段：哪个字段出错抖哪个，服务端失败抖密码框
     （凭证类错误）但不带行内文案——那份文案由底部 aria-live 状态行独占，
     避免同一段话在两处同时出现。 */
  const { inputRef: userInputRef, ...userShake } = useCatalogShake(1200);
  const { inputRef: passwordInputRef, ...pwShake } = useCatalogShake(1200);


  /* 账号相关的错误后端已给出中文说明，直接用；其余保持原有映射。 */
  const ACCOUNT_ERROR_CODES = new Set([
    'username_required',
    'username_too_long',
    'username_invalid_characters',
    'username_reserved',
    'username_taken',
    'password_required',
    'password_too_long',
    'password_invalid_characters',
    'registration_closed',
    'invalid_credentials',
  ]);

  const mapError = (e: unknown): { text: string; tone: 'error' | 'warn' } => {
    if (e instanceof ApiError) {
      if (e.bizCode === 'password_too_short') return { text: t('新密码至少需要 15 个字符'), tone: 'error' };
      if (e.bizCode === 'password_too_common') return { text: t('这个密码过于常见，请换一个较长的短语'), tone: 'error' };
      if (e.bizCode === 'login_cooldown') return { text: t('连续登录失败，请稍后再试'), tone: 'warn' };
      if (e.bizCode === 'registration_rate_limited') {
        return { text: e.message || t('注册过于频繁，请稍后再试'), tone: 'warn' };
      }
      if (e.bizCode === 'https_required') return { text: e.message || t('登录需要 HTTPS'), tone: 'warn' };
      if (e.bizCode && ACCOUNT_ERROR_CODES.has(e.bizCode)) {
        return { text: e.message || t('用户名或密码不正确'), tone: 'error' };
      }
      if (e.code === 429 || e.code >= 500) return { text: t('服务暂时不可用，稍后重试'), tone: 'warn' };
      if (e.code === 408 || e.code === 0) return { text: t('网络连接超时，请检查网络后重试'), tone: 'warn' };
    }
    if (e instanceof TypeError) {
      // fetch 网络层失败（断网/DNS）不是凭据错误，谎报会引导用户改密码
      return { text: t('网络连接失败，请检查网络后重试'), tone: 'warn' };
    }
    return { text: mode === 'register' ? t('注册失败，请重试') : t('用户名或密码不正确'), tone: 'error' };
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (state === 'verifying' || state === 'success' || serviceDown) return;
    if (!username.trim()) {
      setStatusMsg({ text: t('请输入用户名'), tone: 'error' });
      userShake.play({ message: true });
      return;
    }
    if (!password.trim()) {
      setStatusMsg({ text: t('请输入密码'), tone: 'error' });
      pwShake.play({ message: true });
      return;
    }
    if (mode === 'register' && Array.from(password).length < 15) {
      setStatusMsg({ text: t('新密码至少需要 15 个字符'), tone: 'error' });
      pwShake.play();
      return;
    }
    setState('verifying');
    setStatusMsg(null);
    userShake.clear();
    pwShake.clear();
    try {
      const name = username.trim();
      if (mode === 'register') await register(name, password);
      else await login(password, name);
      setState('success');
      const isAdmin = name.toLowerCase() === 'admin';
      toast.success(
        mode === 'register' ? t('账号已创建') : t('欢迎回来'),
        isAdmin ? t('管理员已登录') : t('已登录 {name}', { name }),
      );
      navigate(fromPath ?? '/watchlist', { replace: true });
    } catch (err) {
      setState('error');
      setStatusMsg(mapError(err));
      pwShake.play();
    }
  };


  const hasAccountSession = isCustomer || (accessMode === 'password' && isOwner);
  /* 私网 Owner 是网络授权，不是账号会话。退出只清 cookie，is_owner 仍为 true，
     不能把登录表单藏掉。密码模式 Owner / 访客账号才算「已登录」。
     加载、已登录、登录表单共用同一个根节点和同一个主题控件，状态切换时已打开的菜单不会消失。 */
  return (
    <main id="login-root" className="login-page">
      <div className="absolute right-4 top-4 z-20 md:right-8 md:top-6"><ThemeSwitcher /></div>
      {loading ? (
        <div className="grid min-h-[100dvh] place-items-center">
          <DotsLoader label={t('加载中')} />
        </div>
      ) : hasAccountSession ? (
        <div className="grid min-h-[100dvh] place-items-center px-4">
          <div className="card-surface w-full max-w-[360px] p-6 text-center">
            <p className="eyebrow">{t('当前会话')}</p>
            <h1 className="mt-2 text-h3 text-ink-800">
              {isOwner ? t('管理员已登录') : t('已登录 {name}', { name: signedInName ?? '' })}
            </h1>
            <div className="mt-5 flex flex-col gap-2.5">
              <button
                type="button"
                onClick={() => navigate(fromPath ?? '/watchlist', { replace: true })}
                className="btn-primary h-11 w-full"
              >
                {t('继续浏览')}
              </button>
              <button
                type="button"
                onClick={() => void logout()}
                className="h-11 rounded-pill border border-line bg-card text-caption text-ink-600 transition-colors hover:border-brand-400 hover:text-brand-600"
              >
                {t('退出并换账号')}
              </button>
            </div>
          </div>
        </div>
      ) : (
        <div className="login-layout">
          <section className="login-intro">
            <Link to="/" className="inline-flex items-center gap-3">
              <img src="/logo.svg" alt="" width="40" height="40" className="dark:brightness-0 dark:invert" />
              <span className="font-display text-h2 font-medium text-ink-900">Optix Japan</span>
            </Link>
            <h1 className="mt-6 font-display text-display-m text-ink-900 lg:mt-10 lg:text-display-xl">
              <span>{t('日股研究')}</span><br />
              <span className="text-brand-600">{t('从这里开始。')}</span>
            </h1>
            <div className="mt-10 hidden grid-cols-3 gap-3 lg:grid">
              {FEATURES.map((feature) => (
                <div key={feature.title} className="paper-panel p-4">
                  <Icon name={feature.icon} size={22} className="text-brand-600" />
                  <p className="mt-4 text-body-s font-medium text-ink-900">{t(feature.title)}</p>
                </div>
              ))}
            </div>
          </section>
          <div className="min-w-0">
            <div className="glass-panel w-full p-5 sm:p-8">
              <div className="flex items-start gap-3">
                <span className="mt-0.5 text-brand-600">
                  <Icon name="command" size={20} />
                </span>
                <div>
                  <h2 className="font-display text-h2 text-ink-900">{t('登录账号')}</h2>
                  <p className="mt-0.5 text-caption text-ink-400">{t('登录后可保存关注股票，未登录亦可浏览全站行情与分析。')}</p>
                </div>
              </div>

            <Segmented<'login' | 'register'>
              options={[{ value: 'login', label: t('登录') }, { value: 'register', label: t('注册账号') }]}
              value={mode}
              onChange={(value) => { setMode(value); setStatusMsg(null); }}
              ariaLabel={t('登录')}
              className="mt-5 w-full justify-center [&>div]:flex-1 [&>div>button]:w-full"
            />

            {serviceDown && (
              <p role="status" className="mt-4 flex items-center justify-between gap-2 rounded-[var(--r-control)] border border-warn-600/30 bg-warn-50 px-2.5 py-1.5 text-caption text-warn-600">
                {t('无法连接服务，登录暂不可用')}
                <button type="button" onClick={() => void probeService()} className="shrink-0 font-medium underline underline-offset-2">
                  {t('重试')}
                </button>
              </p>
            )}

            <form onSubmit={onSubmit} className="mt-5" noValidate>
              <div className={cn('t-input-wrap mb-5', userShake.classes.wrap)}>
                <label htmlFor="login-username" className="mb-2 block text-caption text-ink-500">{t('用户名')}</label>
                <div
                  ref={userInputRef}
                  className={cn(
                    't-input flex h-12 items-center gap-2 rounded-[var(--r-control)] border bg-card px-3',
                    'transition-[box-shadow,border-color] duration-fast',
                    'focus-within:border-brand-600 focus-within:shadow-focus-ring',
                    userShake.classes.input,
                    userShake.error ? 'border-down-600' : 'border-line-strong',
                  )}
                >
                  <Icon name="command" size={16} className="shrink-0 text-ink-400" />
                  <input
                    id="login-username"
                    name="username"
                    type="text"
                    required
                    value={username}
                    disabled={serviceDown || state === 'verifying' || state === 'success'}
                    onChange={(e) => {
                      setUsername(e.target.value);
                      userShake.clear();
                    }}
                    placeholder={mode === 'register' ? t('起一个用户名') : t('用户名')}
                    maxLength={32}
                    enterKeyHint="next"
                    className="h-full min-w-0 flex-1 bg-transparent text-body text-ink-800 outline-none placeholder:text-ink-400 disabled:opacity-60"
                    autoComplete="username"
                    autoCapitalize="off"
                    autoCorrect="off"
                    spellCheck={false}
                    aria-invalid={userShake.error || undefined}
                    aria-describedby={userShake.error ? 'login-username-error' : undefined}
                  />
                </div>
                <div className="t-error-track">
                  <div className="t-error-clip">
                    <p id="login-username-error" className="t-error-msg text-caption text-down-700">{t('请输入用户名')}</p>
                  </div>
                </div>
              </div>
              <div className={cn('t-input-wrap', pwShake.classes.wrap)}>
                <label htmlFor="login-password" className="mb-2 block text-caption text-ink-500">{t('密码')}</label>
                <div
                  ref={passwordInputRef}
                  className={cn(
                    't-input flex h-12 items-center gap-2 rounded-[var(--r-control)] border bg-card px-3 transition-[box-shadow,border-color] duration-fast',
                    'focus-within:border-brand-600 focus-within:shadow-focus-ring',
                    pwShake.classes.input,
                    pwShake.error ? 'border-down-600' : 'border-line-strong',
                  )}
                >
                  <Icon name="shield" size={16} className="shrink-0 text-ink-400" />
                  <input
                    id="login-password"
                    name="password"
                    type={showPw ? 'text' : 'password'}
                    required
                    minLength={mode === 'register' ? 15 : undefined}
                    value={password}
                    disabled={serviceDown || state === 'verifying' || state === 'success'}
                    onChange={(e) => {
                      setPassword(e.target.value);
                      pwShake.clear();
                    }}
                    onKeyDown={(e) => setCapsLock(e.getModifierState?.('CapsLock') ?? false)}
                    onKeyUp={(e) => setCapsLock(e.getModifierState?.('CapsLock') ?? false)}
                    placeholder={mode === 'register' ? t('设置密码') : t('输入密码')}
                    enterKeyHint="go"
                    className="h-full min-w-0 flex-1 bg-transparent tnum text-body text-ink-800 outline-none placeholder:text-ink-400 disabled:opacity-60"
                    autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
                    aria-invalid={pwShake.error || undefined}
                    aria-describedby={
                      [mode === 'register' ? 'registration-password-hint' : '', pwShake.error ? 'login-password-error' : '']
                        .filter(Boolean)
                        .join(' ') || undefined
                    }
                  />
                  <button
                    type="button"
                    onClick={() => setShowPw((v) => !v)}
                    className="touch-target flex shrink-0 items-center justify-center rounded-xs p-1 text-ink-400 transition-colors hover:text-ink-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-600"
                    aria-label={showPw ? t('隐藏密码') : t('显示密码')}
                  >
                    <EyeIcon off={!showPw} />
                  </button>
                </div>
                {mode === 'register' && (
                  <p id="registration-password-hint" className="mt-2 text-caption text-ink-500">
                    {t('至少 15 个字符，可使用一句容易记住的长短语')}
                  </p>
                )}
                <div className="t-error-track">
                  <div className="t-error-clip">
                    <p id="login-password-error" className="t-error-msg text-caption text-down-700">{t('请输入密码')}</p>
                  </div>
                </div>
              </div>
              <p className={cn('mt-1.5 h-4 text-caption text-warn-600 transition-opacity', capsLock ? 'opacity-100' : 'opacity-0')}>
                {t('Caps Lock 已开启')}
              </p>

              <button
                type="submit"
                disabled={serviceDown || state === 'verifying' || state === 'success'}
                aria-busy={state === 'verifying'}
                className="btn-primary h-12 w-full text-body-s"
              >
                {state === 'verifying' ? (
                  <>
                    <span className="size-4 animate-spin rounded-full border-2 border-white/40 border-t-white" aria-hidden="true" />
                    {t('验证中…')}
                  </>
                ) : state === 'success' ? (
                  <>
                    <Icon name="check" size={16} strokeWidth={1.45} />
                    {mode === 'register' ? t('已创建') : t('验证通过')}
                  </>
                ) : mode === 'register' ? (
                  t('注册并登录')
                ) : (
                  t('登录')
                )}
              </button>

              {/* 状态行（预留 20px 避免跳动） */}
              {/* 常驻 live region（审计 2.5.11）：节点先于内容存在，冷却/HTTPS/
                  服务不可用等 warn 语调的提示也会被播报；在已存在节点上动态
                  挂 role=alert 往往不触发播报，所以 role 恒为 status、错误
                  升为 assertive。 */}
              <p
                className={cn(
                  'mt-3 min-h-5 text-caption',
                  statusMsg?.tone === 'warn' ? 'text-warn-600' : 'text-down-700',
                  !statusMsg && 'opacity-0',
                )}
                role={statusMsg?.tone === 'error' ? 'alert' : 'status'}
                aria-live={statusMsg?.tone === 'error' ? 'assertive' : 'polite'}
              >
                {statusMsg ? statusMsg.text : '·'}
              </p>
            </form>

            <div className="mt-4 border-t border-line pt-4 text-center">
              <button
                type="button"
                onClick={() => navigate(fromPath && fromPath !== '/watchlist' ? fromPath : '/')}
                className="inline-flex items-center gap-1 text-caption font-medium text-brand-600 transition-colors hover:text-brand-700"
              >
                <Icon name="chevron-right" size={13} className="rotate-180" />
                {t('暂不登录，直接浏览')}
              </button>
            </div>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
