/**
 * Frontend layering gate — the hexagon-lite analogue of the backend import-linter.
 *
 * P4b-0: report-only (severity "warn") for the broad view-rule, so existing
 * production violations surface on every PR as the baseline debt without
 * blocking. As each god-component is decomposed and cleaned, a scoped "error"
 * rule is added for its subtree (see bookmarklist-no-direct-api, added at the
 * end of P4b-3).
 *
 * Test/spec files are excluded — they legitimately import services/api to mock
 * or assert against it.
 */
const TEST_FILES = "\\.(test|spec)\\.[tj]sx?$";

module.exports = {
  forbidden: [
    {
      name: "no-view-imports-api",
      severity: "warn",
      comment:
        "View (components/* + App.tsx) must reach the backend via useServices().api, not a direct services/api or adapters import.",
      from: { path: "^src/(components/|App\\.tsx)", pathNot: TEST_FILES },
      to: { path: "^src/(services/api|adapters)" },
    },
    {
      name: "only-bridge-opens-socket",
      severity: "warn",
      comment:
        "useWebSocket may only be imported by the useWsRouter bridge, and useWsRouter only by main.tsx — preserves the single-connection invariant (App.singleConnection.test.tsx).",
      from: {
        pathNot: ["^src/adapters/ws/useWsRouter\\.ts$", "^src/main\\.tsx$", TEST_FILES],
      },
      to: { path: "^src/(adapters/ws/useWsRouter|hooks/useWebSocket)" },
    },
  ],
  options: {
    doNotFollow: { path: "node_modules" },
    tsConfig: { fileName: "tsconfig.json" },
    tsPreCompilationDeps: true,
  },
};
