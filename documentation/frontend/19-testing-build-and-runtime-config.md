# Testing, Build, and Runtime Configuration

## Files Covered

| File | Role |
| --- | --- |
| `package.json` | NPM scripts, dependencies, dev dependencies, browser support, and React build/test commands. |
| `package-lock.json` | Locked dependency versions. |
| `tsconfig.json` | TypeScript compiler configuration. |
| `.env.production.local` | Production-local environment values used by the React build/runtime. |
| `src/App.test.tsx` | Existing app test file. |
| `src/setupTests.ts` | Jest/testing-library setup file. |
| `src/react-app-env.d.ts` | Create React App TypeScript environment declarations. |
| `public/index.html` | HTML entrypoint used by the React build. |

## Build System

The frontend is a Create React App-style React/TypeScript application built with `react-scripts`.

The package is named:

```json
"name": "share_smart_fhir_ui"
```

The package version is:

```json
"version": "0.1.0"
```

The package is marked private:

```json
"private": true
```

The build system is controlled by `react-scripts` rather than a custom Vite, Next.js, Webpack, or Rollup configuration.

## NPM Scripts

`package.json` defines the following scripts:

| Script | Command | Purpose |
| --- | --- | --- |
| `start` | `react-scripts start` | Starts the local development server. |
| `build` | `react-scripts build` | Creates a production build in the `build/` directory. |
| `test` | `react-scripts test` | Runs the Jest test runner through Create React App. |
| `eject` | `react-scripts eject` | Ejects Create React App configuration. This is one-way and should be avoided unless the project intentionally leaves CRA-managed config. |

## Dependency Table

### Runtime and Application Dependencies

| Dependency | Version | Role in this frontend |
| --- | --- | --- |
| `@tanstack/react-table` | `^8.21.3` | Table rendering utilities used by data-heavy UI screens. |
| `@testing-library/dom` | `^10.4.0` | DOM testing utilities used by React Testing Library. |
| `@testing-library/jest-dom` | `^6.6.3` | Jest DOM matchers imported by `setupTests.ts`. |
| `@testing-library/react` | `^16.3.0` | React component testing utilities. |
| `@testing-library/user-event` | `^13.5.0` | User-event test helpers. |
| `@types/jest` | `^27.5.2` | Jest TypeScript definitions. |
| `@types/node` | `^16.18.126` | Node TypeScript definitions. |
| `chart.js` | `^4.5.0` | Chart rendering dependency used by graph/result components. |
| `docx` | `^9.6.1` | Word/DOCX export generation. |
| `html-to-image` | `^1.11.13` | DOM-to-image export support. |
| `html2canvas` | `^1.4.1` | DOM capture support for export flows. |
| `jspdf` | `^4.0.0` | PDF generation. |
| `jspdf-autotable` | `^5.0.7` | PDF table rendering. |
| `react` | `^19.2.1` | React UI library. |
| `react-bootstrap-icons` | `^1.11.6` | Icon components. |
| `react-chartjs-2` | `^5.3.0` | React bindings for Chart.js. |
| `react-dom` | `^19.2.1` | React DOM rendering. |
| `react-router-dom` | `^7.6.3` | Router package dependency. The top-level app currently uses in-memory screen state rather than URL-based routing for the documented screen flow. |
| `react-scripts` | `^5.0.1` | CRA build/start/test tooling. |
| `typescript` | `^4.9.5` | TypeScript compiler used by CRA. |
| `web-vitals` | `^2.1.4` | Web vitals reporting support through `reportWebVitals.ts`. |

### Development Dependencies

| Dependency | Version | Role |
| --- | --- | --- |
| `@types/react` | `^19.2.7` | React TypeScript definitions. |
| `@types/react-dom` | `^19.2.3` | React DOM TypeScript definitions. |

### Package Overrides

`package.json` defines one dependency override:

```json
"overrides": {
  "nth-check": "2.1.1"
}
```

This pins the transitive `nth-check` package to `2.1.1`.

## Lock File

`package-lock.json` is present and uses lockfile version `3`.

Developers should use `npm install` or `npm ci` from the same package root so installed versions remain aligned with `package-lock.json`.

For repeatable CI/local rebuilds, prefer:

```bash
npm ci
```

For normal local development when dependencies may need to be updated, use:

```bash
npm install
```

## Browser Support

`package.json` defines separate browser targets for production and development builds.

Production browser targets:

```json
[
  ">0.2%",
  "not dead",
  "not op_mini all"
]
```

Development browser targets:

```json
[
  "last 1 chrome version",
  "last 1 firefox version",
  "last 1 safari version"
]
```

## ESLint Configuration

`package.json` uses the standard CRA ESLint presets:

```json
"eslintConfig": {
  "extends": [
    "react-app",
    "react-app/jest"
  ]
}
```

This means linting expectations come from the CRA React and Jest presets unless the project later adds explicit ESLint configuration files.

## TypeScript Configuration

`tsconfig.json` contains the frontend TypeScript compiler options.

| Setting | Value | Effect |
| --- | --- | --- |
| `target` | `es2022` | Emits/validates against modern JavaScript language behavior. |
| `lib` | `dom`, `esnext` | Includes browser DOM APIs and modern JavaScript APIs. |
| `module` | `esnext` | Uses modern ES module semantics. |
| `moduleResolution` | `bundler` | Resolves modules using bundler-oriented TypeScript behavior. |
| `jsx` | `react-jsx` | Uses the React JSX transform. |
| `strict` | `true` | Enables strict TypeScript checking. |
| `resolveJsonModule` | `true` | Allows JSON files to be imported as modules. |
| `isolatedModules` | `true` | Ensures each file can be transpiled independently. |
| `noEmit` | `true` | TypeScript does not emit files directly; CRA handles build output. |
| `allowJs` | `true` | JavaScript files are allowed in the source tree. |
| `skipLibCheck` | `true` | Skips type checking of declaration files. |
| `esModuleInterop` | `true` | Enables compatibility for CommonJS-style default imports. |
| `allowSyntheticDefaultImports` | `true` | Allows synthetic default imports where supported by tooling. |
| `forceConsistentCasingInFileNames` | `true` | Prevents import casing mismatches across platforms. |
| `noFallthroughCasesInSwitch` | `true` | Prevents unintentional switch-case fallthrough. |

The configured include list is:

```json
"include": ["src"]
```

Only files under `src/` are included in the TypeScript program by this `tsconfig.json`.

## TypeScript Build Implications

Because `strict` is enabled, new code should avoid introducing loosely typed values unless the surrounding code already requires it.

Because `noEmit` is enabled, running TypeScript checking does not directly write JavaScript output. The production output is generated by `react-scripts build`.

Because `resolveJsonModule` is enabled, source-side JSON files such as `src/constants/global_schema.json` can be imported by TypeScript. Public JSON files under `public/` are normally fetched by URL at runtime rather than imported through TypeScript.

Because `allowJs` is enabled, JavaScript files can exist in the source tree, but the current reviewed source is primarily TypeScript/TSX.

## Environment Configuration

The reviewed frontend package includes one environment file:

```text
.env.production.local
```

Its contents are:

```env
REACT_APP_API_BASE=http://localhost:8000
REACT_APP_BUILD_FLAVOR=local
```

Create React App only exposes custom browser environment variables when they are prefixed with `REACT_APP_`.

## Environment Variable Table

| Variable | Defined in reviewed package | Read by code | Purpose |
| --- | --- | --- | --- |
| `NODE_ENV` | Set by `react-scripts` | Yes, in `src/constants/Constants.tsx` | Chooses local API base in development and environment/fallback API base outside development. |
| `REACT_APP_API_BASE` | Yes, in `.env.production.local` | Yes, in `src/constants/Constants.tsx` | Production/non-development API base override. In the reviewed env file, it points to `http://localhost:8000`. |
| `REACT_APP_BUILD_FLAVOR` | Yes, in `.env.production.local` | Yes, in `src/constants/Constants.tsx` | Build-flavor marker. `IS_STANDALONE_APP` is true when the value is `local`, which is how the self-hosted standalone bundle is distinguished from the hosted production build. |
| `REACT_APP_MYSQL_SECRET_PW` | No | Yes, in `JobSubmissionPage.tsx` | Optional value included as `$pw` in polling requests to `POST /jobs/status`. This is referenced by code but not defined in the reviewed env file. |
| `PUBLIC_URL` | CRA-managed/template value | Used in `public/index.html` placeholders | Resolves favicon, manifest, and apple-touch-icon paths. |

## API Base Runtime Behavior

`src/constants/Constants.tsx` defines these base values:

```ts
const LOCAL_API_BASE = "http://localhost:8000";
export const CLIENT_API_BASE_PORT = 8088;
export const CLIENT_API_BASE = `http://127.0.0.1:${CLIENT_API_BASE_PORT}`;
export const IS_LOCAL_APP = process.env.NODE_ENV === "development";
export const IS_STANDALONE_APP = process.env.REACT_APP_BUILD_FLAVOR === "local";
const PROD_FALLBACK_API_BASE = "https://api.example.org";
export const ALB_API_BASE = "http://api.example.org"
export const PROD_FALLBACK_API_WS_BASE = "wss://ws.example.org/prod"
```

`API_BASE` is selected as follows:

```ts
export const API_BASE =
  process.env.NODE_ENV === "development"
    ? LOCAL_API_BASE
    : process.env.REACT_APP_API_BASE ?? PROD_FALLBACK_API_BASE;
```

Runtime effect:

| Build mode | API base behavior |
| --- | --- |
| `npm start` / development | Always uses `http://localhost:8000`. |
| production build with `REACT_APP_API_BASE` | Uses the value of `REACT_APP_API_BASE`. |
| production build without `REACT_APP_API_BASE` | Falls back to the API Gateway URL constant. |

## Websocket Base Runtime Behavior

`Constants.tsx` defines `WS_API_BASE` as:

```ts
export const WS_API_BASE =
  process.env.NODE_ENV === "development"
    ? LOCAL_API_BASE
    : process.env.REACT_APP_API_BASE ?? PROD_FALLBACK_API_WS_BASE;
```

The websocket URL builders in `JobSubmissionPage.tsx` and `JobHistoryTable.tsx` convert local `http://` and `https://` API bases to `ws://` or `wss://` when building `/jobs/status/ws/local/{job_id}` URLs.

For non-local mode, those URL builders return:

```text
{WS_API_BASE}?job_id={job_id}
```

Important implementation detail: `WS_API_BASE` uses `REACT_APP_API_BASE` in non-development builds when that variable is present. If `REACT_APP_API_BASE` is an HTTP API endpoint, websocket streaming will use that value unless the code or environment is adjusted to provide a websocket-specific base. The existing code does not define a separate `REACT_APP_WS_API_BASE` variable.

## Backend Endpoint Constants

`Constants.tsx` centralizes API path constants used throughout the frontend.

| Constant | Value |
| --- | --- |
| `API_SUBMIT_JOB` | `/nvflare/jobs/submit` |
| `API_JOB_HISTORY` | `/nvflare/jobs/history` |
| `API_JOB_STATUS` | `/jobs/status` |
| `API_JOB_STATUS_WEBSOCKET` | `/jobs/status/ws` |
| `API_JOB_RESULTS` | `/jobs/results` |
| `API_JOB_RESULTS_MAPPING` | `/jobs/results/mapping` |
| `API_JOB_RESULTS_FUNCTION_CONFIG` | `${API_BASE}/jobs/function/config` |
| `API_FILTERS_FETCH_SINGLE` | `/filters/fetch_single_filter` |
| `API_FILTERS_FETCH` | `/filters/fetch_filters` |
| `API_FUNCTIONS_SUPPORTED` | `/functions/supported_functions` |
| `API_CLIENTS_PARTICIPATION_STATUS` | `/clients/participation/status` |
| `API_CLIENTS_CONNECTION_STATUS` | `/clients/connection/status` |
| `API_LANDING_HOME` | `/landing/home` |
| `API_LANDING_PROJECT` | `/landing/project` |
| `API_PROJECTS_LIST` | `/projects/list` |
| `API_PROJECTS_FHIR_SOURCE` | `/projects/fhir/source` |

Most constants are path-only and are joined with `API_BASE` by callers. `API_JOB_RESULTS_FUNCTION_CONFIG` is already a full URL because it includes `API_BASE` directly in the constant.

## Runtime HTML Entrypoint

`public/index.html` is the browser HTML entrypoint.

Key values:

| Item | Value |
| --- | --- |
| Document language | `en` |
| Charset | `utf-8` |
| Viewport | `width=device-width, initial-scale=1` |
| Theme color | `#000000` |
| Description | `Web site created using create-react-app` |
| Title | `SHARE` |
| Root element | `<div id="root"></div>` |
| Favicon | `%PUBLIC_URL%/favicon.ico` |
| Apple touch icon | `%PUBLIC_URL%/logo192.png` |
| Manifest | `%PUBLIC_URL%/manifest.json` |

The React app mounts into the `root` element through `src/index.tsx`.

The HTML file uses `%PUBLIC_URL%` placeholders, which CRA resolves during build/start.

## Testing Setup

The test stack is CRA Jest plus React Testing Library.

`src/setupTests.ts` imports:

```ts
import '@testing-library/jest-dom';
```

That import adds custom Jest DOM matchers such as `toBeInTheDocument()`.

`src/react-app-env.d.ts` contains:

```ts
/// <reference types="react-scripts" />
```

This provides CRA-specific TypeScript declarations.

## Existing Test Coverage

The reviewed package contains one test file:

```text
src/App.test.tsx
```

The test is the default CRA-style placeholder:

```ts
test('renders learn react link', () => {
  render(<App />);
  const linkElement = screen.getByText(/learn react/i);
  expect(linkElement).toBeInTheDocument();
});
```

This test does not reflect the current SHARE app behavior documented in the frontend source. The app starts at the SHARE login flow and enters global Home after authentication rather than rendering a default `learn react` link. As written, this test should be treated as stale placeholder coverage and should be replaced with app-specific tests.

## Running Tests

Run tests with:

```bash
npm test
```

Because this uses `react-scripts test`, it starts the Jest runner in CRA's test mode.

For CI-style single-pass execution, use:

```bash
CI=true npm test -- --watchAll=false
```

Current expected issue: the existing placeholder `App.test.tsx` is likely to fail until it is updated to assert the actual login screen or other real app behavior.

## Recommended Test Coverage Areas

The current test file should be replaced or expanded with coverage for the actual application behavior.

Recommended coverage areas:

| Area | Recommended coverage |
| --- | --- |
| App entry flow | Renders login screen first; successful login transitions to project selection. |
| User role context | Provider exposes role, username, user ID, selected project, project access, and datasource metadata. |
| Project selection | Project list rendering, selected project callback, datasource lookup behavior, and error states. |
| Navigation selector | Button/card actions call the correct top-level screen callbacks. |
| Job runner | Filter selection, workflow group at-least-one behavior, function selection, submit payload assembly, disabled submit conditions. |
| NVFlare snapshot | Server/client rows, online/offline status labels, participation/contributing/analyzing display rules. |
| Job history | History request payload, date filtering, row action behavior, status display, websocket fallback behavior. |
| Results page | Result loading, workflow ID selection, missing result handling, report section visibility. |
| Export system | Section defaults, Job Summary unchecked by default, Filters Overview ordering, per-workflow selection, PDF/DOCX/HTML/PNG action routing. |
| Static config | Missing or malformed `public/filters` and `public/analysis_config` JSON handling. |

## Build Outputs

`npm run build` produces a static production build through CRA.

Expected output directory:

```text
build/
```

The build output contains bundled JavaScript/CSS plus copied public assets.

Public assets under `public/` are served by path and copied into the production build. Source files under `src/` are bundled by CRA.

## Local Development Instructions

From the frontend package root:

```bash
npm install
npm start
```

For lockfile-strict install:

```bash
npm ci
npm start
```

Expected local frontend server:

```text
http://localhost:3000
```

Expected local backend base used by `npm start`:

```text
http://localhost:8000
```

This backend base is hardcoded by `Constants.tsx` when `NODE_ENV === "development"`.

## Local Backend Targeting

For normal `npm start` development, changing `.env.production.local` does not change `API_BASE`, because development mode uses `LOCAL_API_BASE` directly.

To target a different backend during `npm start`, update `LOCAL_API_BASE` in `src/constants/Constants.tsx` or add a development-specific environment strategy and adjust `API_BASE` selection logic.

For production builds, set:

```env
REACT_APP_API_BASE=<backend-base-url>
```

Then run:

```bash
npm run build
```

## Production Build Instructions

From the frontend package root:

```bash
npm ci
npm run build
```

The build artifacts will be written to:

```text
build/
```

The resulting `build/` directory can be served by a static host.

For a production build targeting a specific backend, ensure `REACT_APP_API_BASE` is available before running the build. CRA injects these values at build time into the generated frontend bundle.

## Production-Local Environment File

The included `.env.production.local` sets:

```env
REACT_APP_API_BASE=http://localhost:8000
REACT_APP_BUILD_FLAVOR=local
```

Because `.env.production.local` is production-mode local configuration, it applies to production builds on that machine, not to normal `npm start` development mode.

This file currently makes a production build target the local backend unless overridden by a higher-priority environment value.

## Source Maps

No explicit source-map setting is defined in the reviewed package.

CRA defaults apply. If source maps need to be disabled for production distribution, add the appropriate CRA environment setting in the build environment rather than changing runtime code.

## Public Asset Path Behavior

`public/index.html` uses `%PUBLIC_URL%` for favicon, logo, and manifest paths.

Components and runtime fetches that load public assets should use root-relative public paths such as:

```text
/filters/default/patient/patient_query.json
/analysis_config/analysis_query.json
/icons/...
/status-images/...
```

Public files are not imported through TypeScript unless moved under `src/`.

## Common Runtime Issues

### Backend API URL points to the wrong host

For `npm start`, verify `LOCAL_API_BASE` in `src/constants/Constants.tsx`.

For production builds, verify the `REACT_APP_API_BASE` value present at build time.

### CORS failures

If the frontend can reach the backend URL but browser calls fail, the backend must allow the frontend origin. Local development commonly needs the backend to allow:

```text
http://localhost:3000
```

### Websocket connection failures

Local websocket URLs are built by converting the local HTTP backend base to a websocket URL and appending:

```text
/jobs/status/ws/local/{job_id}
```

Production websocket URLs are built from `WS_API_BASE` with a `job_id` query parameter. Because `WS_API_BASE` currently uses `REACT_APP_API_BASE` when present, production websocket configuration should be verified carefully if the HTTP API base and websocket base are different.

### Missing public JSON files

Filter and analysis configuration files are loaded from `public/` paths at runtime. A missing file will fail as a browser fetch failure or JSON parse failure in the loading component.

Confirm the file exists in both the source `public/` directory and the deployed static build.

### Missing static icons/images

Static images under `public/icons`, `public/logos`, and `public/status-images` are served by path. A bad path will usually show as a broken image in the UI and a 404 in browser developer tools.

### TypeScript build failures

Because `strict` is enabled, new or modified TypeScript code must satisfy strict type checking. Check local props/interfaces first when build errors originate in TSX components.

### Dependency install issues

Use the committed `package-lock.json` and run:

```bash
npm ci
```

If dependency resolution changes unexpectedly, verify the `overrides.nth-check` pin is still present.

### Stale browser cache or stale public config

Because static JSON and images are loaded from public paths, browser caching can make config appear stale. Hard refresh the browser or use cache-busting in fetch paths when testing frequently changing public JSON/test assets.

### Large static/test data load failures

The reviewed `public/test-data/` directory exists but large test data files were not included in the package. If large test data is restored, confirm that the static host can serve the file sizes and that the frontend loading code handles progress, caching, and missing-file states.

## Developer Conventions to Preserve

- Keep endpoint constants centralized in `src/constants/Constants.tsx` instead of scattering literal backend URLs.
- Keep CRA `REACT_APP_` prefix requirements in mind for browser-visible environment variables.
- Treat `.env.production.local` as production-build local override behavior, not as the main local development configuration.
- Keep TypeScript strictness enabled unless the team intentionally relaxes project-wide compiler behavior.
- Replace the stale CRA test with real app tests before using test pass/fail as a quality signal.
- Avoid relying on URL routing for the top-level app flow unless the app routing model is intentionally redesigned.
