/** @type {import('tailwindcss').Config} */
const token = (name) =>
  `color-mix(in srgb, var(${name}) calc(100% * <alpha-value>), transparent)`;

module.exports = {
  darkMode: ["class"],
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  future: {
    hoverOnlyWhenSupported: true,
  },
  theme: {
    extend: {
      colors: {
        'on-accent': token('--on-accent'),
        action: {
          DEFAULT: token('--action'),
          hover: token('--action-hover'),
        },
        'on-action': token('--on-action'),
        /* ---- Optix 纸面终端 tokens：从 CSS 变量生成，html.dark 换盘后工具类一起换 ---- */
        paper: {
          DEFAULT: token('--paper'),
          2: token('--paper-2'),
        },
        card: {
          DEFAULT: token('--card'),
          warm: token('--card-warm'),
          foreground: token('--ink-900'),
        },
        ink: {
          900: token('--ink-900'),
          800: token('--ink-800'),
          /* 700：源码里 18 处「比正文重一档」的用法此前落在不存在的档位上，
             类名不生成任何规则、全部退回继承色（审计 2.4.7/3.2）。 */
          700: token('--ink-700'),
          600: token('--ink-600'),
          500: token('--ink-500'),
          400: token('--ink-400'),
          300: token('--ink-300'),
        },
        line: {
          DEFAULT: token('--line'),
          strong: token('--line-strong'),
          chart: token('--line-chart'),
        },
        /* 群青只做同色相深浅：hover 一律深一档 brand-700，夜间抬升对比度 */
        brand: {
          700: token('--brand-700'),
          600: token('--brand-600'),
          500: token('--brand-500'),
          400: token('--brand-400'),
          100: token('--brand-100'),
          50: token('--brand-50'),
        },
        /* 涨跌色走 CSS 变量，html[data-color-mode=asian] 换盘后工具类一起换。
           <alpha-value> 保住 bg-up-600/20 这类透明度变体。 */
        up: {
          700: 'color-mix(in srgb, var(--up-700) calc(100% * <alpha-value>), transparent)',
          600: 'color-mix(in srgb, var(--up-600) calc(100% * <alpha-value>), transparent)',
          50: 'color-mix(in srgb, var(--up-50) calc(100% * <alpha-value>), transparent)',
        },
        down: {
          700: 'color-mix(in srgb, var(--down-700) calc(100% * <alpha-value>), transparent)',
          600: 'color-mix(in srgb, var(--down-600) calc(100% * <alpha-value>), transparent)',
          50: 'color-mix(in srgb, var(--down-50) calc(100% * <alpha-value>), transparent)',
        },
        /* 状态色（index.css 说明）：不随红涨绿跌互换。 */
        ok: {
          700: token('--ok-700'),
          600: token('--ok-600'),
          50: token('--ok-50'),
        },
        danger: {
          700: token('--danger-700'),
          600: token('--danger-600'),
          50: token('--danger-50'),
        },
        warn: {
          /* 700：警示横幅主文案用档（warn-50 底上比 600 重一档，审计 2.4.5） */
          700: token('--warn-700'),
          600: token('--warn-600'),
          50: token('--warn-50'),
        },
        ai: {
          600: token('--ai-600'),
          50: token('--ai-50'),
        },
        'cat-sky': { 50: token('--cat-sky-50'), 600: token('--cat-sky-600'), 700: token('--cat-sky-700') },
        'cat-amber': { 50: token('--cat-amber-50'), 600: token('--cat-amber-600'), 700: token('--cat-amber-700') },
        'cat-orange': { 50: token('--cat-orange-50'), 600: token('--cat-orange-600'), 700: token('--cat-orange-700') },
      },
      borderRadius: {
        xs: '4px',
        sm: '6px',
        md: '8px',
        lg: '24px',
        xl: '28px',
        '2xl': '32px',
        pill: '999px',
      },
      boxShadow: {
        /* v8 清新：墨色 rgba(16,24,40,*) 三层制，更柔更大；内高光 .7 保持；聚焦环即时出现 */
        'sh-1': 'var(--shadow-sh-1)',
        'sh-2': 'var(--shadow-sh-2)',
        'sh-3': 'var(--shadow-sh-3)',
        'card': 'var(--card-shadow)',
        'card-hover': 'var(--card-hover-shadow)',
        'inset-hi': 'var(--inset-hi-shadow)',
        'focus-ring': '0 0 0 3px color-mix(in srgb, var(--brand-600) 25%, transparent)',
        /* 开关旋钮、小件影、轨道井与悬浮层走 CSS 变量，便于夜间覆盖。 */
        knob: 'var(--knob-shadow)',
        xs: 'var(--shadow-xs)',
        track: 'var(--track-shadow)',
        overlay: 'var(--overlay-shadow)',
        dock: 'var(--dock-shadow)',
        zone: 'var(--zone-shadow)',
        /* 按钮立体三档（与 sh-* 同族墨影）：btn-hi 实心主按钮 > btn 描边次按钮 >
           幽灵/文字按钮平面。chip 给选中态胶囊/页码/分段滑块（介于两者之间）；
           track 是开关轨道的内凹井。按下收拢/禁用摊平的全局规则在 index.css。 */
        btn: 'var(--btn-shadow)',
        'btn-hi': 'var(--btn-hi-shadow)',
        chip: 'var(--chip-shadow)',
      },
      fontFamily: {
        /* v8：display 换系统 sans 栈（与 sans 相同但独立变量保留，大标不再用衬线） */
        display: ['-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', '"PingFang SC"', '"Hiragino Sans GB"', '"Noto Sans SC"', '"Microsoft YaHei UI"', 'sans-serif'],
        /* 衬线只保留给新闻原文摘要这类「编辑式引文」：font-quote。模型与系统生成的文字用无衬线。 */
        quote: ['Georgia', '"Songti SC"', '"Noto Serif SC"', 'serif'],
        sans: ['-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', '"PingFang SC"', '"Hiragino Sans GB"', '"Noto Sans SC"', '"Microsoft YaHei UI"', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', '"SF Mono"', 'Menlo', 'Consolas', '"Liberation Mono"', 'monospace'],
      },
      fontSize: {
        'display-xl': ['3.25rem', { lineHeight: '1.1', fontWeight: '500', letterSpacing: '-0.035em' }],
        'display-l': ['2.25rem', { lineHeight: '1.2', fontWeight: '500', letterSpacing: '-0.035em' }],
        'display-m': ['1.75rem', { lineHeight: '1.25', fontWeight: '500', letterSpacing: '-0.025em' }],
        h2: ['1.375rem', { lineHeight: '1.4', fontWeight: '500' }],
        h3: ['1.0625rem', { lineHeight: '1.5', fontWeight: '500' }],
        body: ['1rem', { lineHeight: '1.625', fontWeight: '400' }],
        'body-s': ['.875rem', { lineHeight: '1.5', fontWeight: '400' }],
        caption: ['.8125rem', { lineHeight: '1.5', fontWeight: '400' }],
        eyebrow: ['.8125rem', { lineHeight: '1.5', fontWeight: '500' }],
        'data-xxl': ['2.5rem', { lineHeight: '1.15', fontWeight: '500', letterSpacing: '-0.035em' }],
        'data-xl': ['1.875rem', { lineHeight: '1.2', fontWeight: '500', letterSpacing: '-0.025em' }],
        'data-l': ['1.375rem', { lineHeight: '1.3', fontWeight: '500', letterSpacing: '-0.015em' }],
        'data-m': ['1rem', { lineHeight: '1.4', fontWeight: '400' }],
        micro: ['.8125rem', { lineHeight: '1.4', fontWeight: '400' }],
        tag: ['.75rem', { lineHeight: '1.35', fontWeight: '400' }],
      },
      maxWidth: {
        shell: '1440px',
      },
      transitionTimingFunction: {
        /* design.md §4.1 缓动 */
        paper: 'cubic-bezier(.16,1,.3,1)',
        snap: 'cubic-bezier(.22,1,.36,1)',
        'in-out-circ': 'cubic-bezier(.45,0,.15,1)',
      },
      transitionDuration: {
        instant: '90ms',
        fast: '160ms',
        /* 卡片 hover 抬升的统一时长。之前 5 处写 duration-[240ms] 任意值，
           构建报「匹配多个 utility」二义警告——收进 token 一并消除。 */
        240: '240ms',
        ui: '260ms',
        section: '560ms',
      },
      keyframes: {
        'led-pulse': {
          '0%': { boxShadow: '0 0 0 0 color-mix(in srgb, var(--ok-600) 55%, transparent)' },
          '70%': { boxShadow: '0 0 0 6px color-mix(in srgb, var(--ok-600) 0%, transparent)' },
          '100%': { boxShadow: '0 0 0 0 color-mix(in srgb, var(--ok-600) 0%, transparent)' },
        },
        'grow-bar': {
          from: { transform: 'scaleX(0)' },
          to: { transform: 'scaleX(1)' },
        },
        /* 动画元素只含第一套内容，其余副本绝对定位在它后面：每轮正好平移一套 */
        marquee: {
          from: { transform: 'translateX(0)' },
          to: { transform: 'translateX(-100%)' },
        },
        'spin-once': {
          from: { transform: 'rotate(0deg)' },
          to: { transform: 'rotate(360deg)' },
        },
      },
      animation: {
        'led-pulse': 'led-pulse 1.5s cubic-bezier(.45,0,.15,1) infinite',
        'grow-bar': 'grow-bar 700ms cubic-bezier(.16,1,.3,1) both',
        marquee: 'marquee 28s linear infinite',
        'spin-once': 'spin-once 520ms cubic-bezier(.16,1,.3,1)',
      },
    },
  },
}
