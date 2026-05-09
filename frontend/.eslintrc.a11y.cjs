// Separate ESLint config for the a11y pass — task #127.
//
// WHY a sibling file: the main .eslintrc.cjs has --max-warnings 0 on
// the day-to-day lint script, and any new rule that surfaces a real
// violation would block CI. This config layers jsx-a11y on top of
// the same parser/plugins so an operator can run `npm run lint:a11y`
// independently. The CI job marks the step continue-on-error so the
// signal is visible without gating the build until we triage.
module.exports = {
  root: true,
  env: { browser: true, es2022: true },
  parser: "@typescript-eslint/parser",
  parserOptions: {
    ecmaVersion: "latest",
    sourceType: "module",
    ecmaFeatures: { jsx: true },
  },
  // WHY @typescript-eslint listed but not extended: with --no-eslintrc
  // we lose access to the main config's plugin registry. Source files
  // contain `// eslint-disable-next-line @typescript-eslint/no-explicit-any`
  // comments that ESLint treats as "rule not found" if the plugin isn't
  // loaded. Listing it here makes the rule names resolvable; we just
  // don't enable any of its rules (no extends), so behaviour-wise it's
  // a no-op for the a11y pass.
  plugins: ["jsx-a11y", "@typescript-eslint"],
  extends: [
    "plugin:jsx-a11y/recommended",
  ],
  rules: {
    // WHY off: the canonical React modal pattern is a div with
    // role="dialog" + tabIndex={-1} + onClick + onKeyDown. The rule
    // wants a native interactive element instead, but <dialog> isn't
    // a drop-in for focus-trap semantics across our locales'
    // browsers. The other a11y invariants (role, aria-modal,
    // aria-labelledby, keyboard handler co-located) stay enforced.
    "jsx-a11y/no-noninteractive-element-interactions": "off",
  },
  ignorePatterns: ["dist", ".eslintrc.cjs", ".eslintrc.a11y.cjs", "vite.config.ts"],
};
