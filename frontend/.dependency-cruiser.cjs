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
    {
      // P4b-3 exit: the BookmarkList tree is fully decomposed and reaches the
      // backend only via useServices().api, so its rule is tightened to ERROR
      // (a regression here fails CI). App/MapView stay "warn" until their rounds.
      name: "bookmarklist-no-direct-api",
      severity: "error",
      comment:
        "The BookmarkList subtree must reach the backend via useServices().api / injected hooks — never a direct services/api or adapters import.",
      from: {
        path: "^src/components/(BookmarkList|BookmarkRow|CategorySection|BookmarkContextMenu|CategoryManagerPanel|AddBookmarkDialog|CustomBookmarkDialog|EditBookmarkDialog|EditCategoryModal)",
        pathNot: TEST_FILES,
      },
      to: { path: "^src/(services/api|adapters)" },
    },
    {
      // P4b-1 exit: App.tsx is fully decomposed and reaches the backend only via
      // useServices().api / injected hooks, so it + its extracted presentational
      // components flip to ERROR. MapView stays "warn" until P4b-2.
      name: "app-no-direct-api",
      severity: "error",
      comment:
        "App.tsx + its extracted components must reach the backend via useServices().api / injected hooks — never a direct services/api or adapters import.",
      from: {
        path: "^src/(App\\.tsx|components/(WaypointEditor|AppAddBookmarkDialog|BulkPasteDialog|WaypointFlyDialog|RouteLoadDialog|RoutePasteDialog))",
        pathNot: TEST_FILES,
      },
      to: { path: "^src/(services/api|adapters)" },
    },
  ],
  options: {
    doNotFollow: { path: "node_modules" },
    tsConfig: { fileName: "tsconfig.json" },
    tsPreCompilationDeps: true,
  },
};
