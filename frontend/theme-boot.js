/* 首次绘制前同步执行：按已保存的外观偏好（或系统外观）和界面语言设置 <html>，
   深色用户不再先看到一屏浅色，日文用户的 lang 从第一帧起就正确。
   规则与 src/lib/themePreference.ts、src/i18n/core.ts 保持一致（tests/theme-boot.mjs 核对）。
   后端的内容安全策略只允许同源脚本，所以这是独立文件而不是内联脚本。 */
/* global localStorage, matchMedia, document, navigator */
(() => {
  let theme = null;
  let locale = null;
  try {
    theme = localStorage.getItem('optixjp_theme');
    locale = localStorage.getItem('optixjp:locale');
  } catch {
    /* 隐私模式下读不到存储：按系统外观与浏览器语言处理 */
  }
  const dark = theme === 'dark' || (theme !== 'light' && matchMedia('(prefers-color-scheme: dark)').matches);
  const root = document.documentElement;
  root.classList.toggle('dark', dark);
  root.dataset.theme = dark ? 'dark' : 'light';
  root.style.colorScheme = dark ? 'dark' : 'light';
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', dark ? '#0F0F10' : '#FAFAFA');

  const tags = { en: 'en-US', ja: 'ja-JP', zh: 'zh-CN' };
  if (!Object.hasOwn(tags, locale ?? '')) {
    locale = 'en';
    for (const raw of [navigator.language, ...(navigator.languages ?? [])]) {
      const tag = String(raw ?? '').toLowerCase();
      const match = ['ja', 'zh', 'en'].find((code) => tag.startsWith(code));
      if (match) { locale = match; break; }
    }
  }
  root.lang = tags[locale];
})();
