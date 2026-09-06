import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  { ignores: ['dist', 'node_modules', '_design-reference'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],

      // ── 보안 규칙: XSS / 코드 인젝션 벡터를 소스 레벨에서 차단 ──────────────
      'no-eval': 'error',
      'no-implied-eval': 'error',
      'no-new-func': 'error',
      'no-script-url': 'error',
      'no-restricted-globals': [
        'error',
        { name: 'eval', message: '코드 인젝션 위험으로 사용 금지' },
      ],
      'no-restricted-properties': [
        'error',
        { object: 'document', property: 'write', message: 'XSS 위험으로 사용 금지' },
        { object: 'window', property: 'eval', message: '코드 인젝션 위험으로 사용 금지' },
      ],
      'no-restricted-syntax': [
        'error',
        {
          selector: 'JSXAttribute[name.name="dangerouslySetInnerHTML"]',
          message: 'dangerouslySetInnerHTML 은 XSS 위험으로 금지한다.',
        },
        {
          selector: "AssignmentExpression > MemberExpression[property.name='innerHTML']",
          message: 'innerHTML 직접 대입은 XSS 위험으로 금지한다.',
        },
        {
          selector: "CallExpression[callee.object.name='localStorage'][callee.property.name='setItem'] > Literal:first-child[value=/token|password|secret|key|jwt|auth/i]",
          message: '인증정보를 localStorage 에 저장하지 않는다.',
        },
      ],
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      '@typescript-eslint/consistent-type-imports': 'warn',
    },
  },
)
