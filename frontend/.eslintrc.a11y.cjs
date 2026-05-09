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
  plugins: ["jsx-a11y"],
  extends: [
    "plugin:jsx-a11y/recommended",
  ],
  ignorePatterns: ["dist", ".eslintrc.cjs", ".eslintrc.a11y.cjs", "vite.config.ts"],
};
