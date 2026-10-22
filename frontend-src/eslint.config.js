// Flat ESLint config (ESLint 9+/10). Restores `npm run lint`, which previously
// exited before evaluating any rule because no flat config existed.
import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import reactHooks from 'eslint-plugin-react-hooks';

export default tseslint.config(
  {
    ignores: ['dist/**', 'node_modules/**', '*.config.js', '*.config.ts'],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['tests/**/*.mjs', 'src/**/*.test.mjs', 'visual-tests/**/*.mjs', 'playwright.config.mjs'],
    languageOptions: {
      // These suites run in Node, including its built-in Web APIs.
      globals: {
        console: 'readonly',
        process: 'readonly',
        URL: 'readonly',
        structuredClone: 'readonly',
      },
    },
  },
  {
    files: ['visual-tests/**/*.mjs'],
    languageOptions: { globals: {
        window: 'readonly', document: 'readonly', Node: 'readonly', HTMLElement: 'readonly',
        DOMMatrix: 'readonly', CSSTransition: 'readonly', CSSAnimation: 'readonly',
        PointerEvent: 'readonly', Event: 'readonly', MutationObserver: 'readonly',
        requestAnimationFrame: 'readonly', localStorage: 'readonly',
        matchMedia: 'readonly', getComputedStyle: 'readonly', scrollY: 'readonly',
    } },
  },
  {
    files: ['src/**/*.{ts,tsx}', 'visual-tests/**/*.{ts,tsx}'],
    languageOptions: { globals: { window: 'readonly', document: 'readonly' } },
    plugins: { 'react-hooks': reactHooks },
    rules: {
      // Classic hook rules only. The plugin's newest "recommended" set bundles
      // React-Compiler lints (e.g. set-state-in-effect) that flag many pre-existing
      // patterns; enabling those wholesale would just make lint unusable again.
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      // The codebase intentionally uses a few pragmatic patterns; keep these as
      // warnings so `eslint .` surfaces them without failing on pre-existing debt.
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
    },
  },
);
