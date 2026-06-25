/**
 * Frontend layering gate — the hexagon-lite analogue of the backend import-linter.
 *
 * All five previously-warning components (StatusBar, ExportPopover, DeviceStatus,
 * CloudSyncSection, AddressSearch) now reach the backend exclusively via
 * useServices().api. The broad view-rule is ENFORCED (severity "error") so no
 * new direct services/api import can regress undetected. Per-subtree error rules
 * added in P4b-1 through P4b-3 remain as narrower guards.
 *
 * Test/spec files are excluded — they legitimately import services/api to mock
 * or assert against it.
 */
const TEST_FILES = "\\.(test|spec)\\.[tj]sx?$";

module.exports = {
  forbidden: [
    {
      name: "no-view-imports-api",
      severity: "error",
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
    {
      // P4b-2a exit: MapView (+ the LeafletBarButton primitive) reaches the
      // backend only via useServices().api / injected hooks, so it flips to
      // ERROR. (Its per-layer hooks/popovers land in P4b-2b.)
      name: "mapview-no-direct-api",
      severity: "error",
      comment:
        "MapView + LeafletBarButton must reach the backend via useServices().api / injected hooks — never a direct services/api or adapters import.",
      from: {
        path: "^src/components/(MapView|LeafletBarButton)",
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
