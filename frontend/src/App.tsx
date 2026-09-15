import React, { useEffect, useMemo, useRef, useState } from "react";
import HeaderBar from "./components/HeaderBar";
import LoginPage from "./pages/LoginPage";
import SHARELandingPage from "./pages/SHARELandingPage";
import UserManagerMain from "./features/user_manager/UserManagerMain";
import { Project } from "./types/Project";
import { UserProjectDatasource, UserRoleContext, UserSession } from "./context/UserRoleContext";
import "./App.css";
import FooterBar from "./components/FooterBar";
import {
  decodeShareLaunchPayload,
  ShareLaunchPayload,
  shouldAutoLoginFromLaunch,
} from "./utils/LaunchPayload";

export type AppScreen =
  | "login"
  | "home"
  | "job_history"
  | "job_runner"
  | "nvflare_manager"
  | "users_manager"
  | "user_settings"
  | "project_settings"
  | "filters_manager"
  | "participation_manager"
  | "job_results";

const APP_HISTORY_STATE_KEY = "__shareApp";
const APP_ROUTE_PARAM = "s";
const NVFLARE_JOB_ID_PARAM = "nvflare_job_id";
const USERNAME_PARAM = "username";
const LAUNCH_PARAM = "launch";

interface AppHistoryState {
  [APP_HISTORY_STATE_KEY]?: boolean;
  screen?: AppScreen;
  nvflareJobId?: string;
  projectId?: number;
  resultsEntrySource?: "app" | "direct";
  jobRunnerStep?: string;
  jobRunnerTrail?: string[];
  jobRunnerProjectId?: number;
  jobRunnerDepth?: number;
}

interface PendingRunnerExit {
  nextScreen: AppScreen;
  nextProject: Project | null | undefined;
  nextProjectId: number | null;
}

interface ParsedLaunchState {
  payload: ShareLaunchPayload | null;
  error: string | null;
}

function getRunnerHistoryDepth(state: AppHistoryState | null | undefined): number {
  if (!state) return 0;
  if (typeof state.jobRunnerDepth === "number" && Number.isFinite(state.jobRunnerDepth)) {
    return Math.max(0, Math.floor(state.jobRunnerDepth));
  }
  return Math.max(0, (state.jobRunnerTrail?.length ?? 1) - 1);
}

function stripRunnerHistory(state: AppHistoryState): AppHistoryState {
  const nextState = { ...state };
  delete nextState.jobRunnerStep;
  delete nextState.jobRunnerTrail;
  delete nextState.jobRunnerProjectId;
  delete nextState.jobRunnerDepth;
  return nextState;
}

const SCREEN_ROUTE_VALUES: Record<AppScreen, string> = {
  login: "0",
  home: "1",
  job_history: "3",
  job_runner: "4",
  nvflare_manager: "5",
  users_manager: "6",
  user_settings: "7",
  project_settings: "11",
  filters_manager: "8",
  participation_manager: "9",
  job_results: "10",
};

function isAppScreen(value: unknown): value is AppScreen {
  return typeof value === "string" && value in SCREEN_ROUTE_VALUES;
}

function readUrlParameter(name: string): string | null {
  if (typeof window === "undefined") {
    return null;
  }

  const normalized = new URL(window.location.href).searchParams.get(name)?.trim();
  return normalized || null;
}

function readLaunchState(): ParsedLaunchState {
  const launchParameter = readUrlParameter(LAUNCH_PARAM);
  if (!launchParameter) {
    return { payload: null, error: null };
  }

  try {
    return {
      payload: decodeShareLaunchPayload(launchParameter),
      error: null,
    };
  } catch (error) {
    return {
      payload: null,
      error: error instanceof Error ? error.message : "Launch link is invalid",
    };
  }
}

function buildScreenUrl(nextScreen: AppScreen): string {
  if (typeof window === "undefined") {
    return "";
  }

  const url = new URL(window.location.href);
  url.searchParams.delete("screen");
  url.searchParams.set(APP_ROUTE_PARAM, SCREEN_ROUTE_VALUES[nextScreen]);
  url.hash = "";
  return `${url.pathname}${url.search}${url.hash}`;
}

const App: React.FC = () => {
  const [screen, setScreenState] = useState<AppScreen>("login");
  const [screenReloadKeys, setScreenReloadKeys] = useState<Partial<Record<AppScreen, number>>>({});
  const [projectsNavOpen, setProjectsNavOpen] = useState(true);
  const initialScreenRef = useRef<AppScreen>("login");
  const [showScrollToTopButton, setShowScrollToTopButton] = useState(false);
  const [animate, setAnimate] = useState(true);
  const launchState = useMemo(readLaunchState, []);
  const initialUsername = useMemo(
    () => launchState.payload?.username || readUrlParameter(USERNAME_PARAM),
    [launchState.payload]
  );
  const [directNVFlareJobId, setDirectNVFlareJobId] = useState<string | null>(() =>
    launchState.payload?.nvflare_job_id || readUrlParameter(NVFLARE_JOB_ID_PARAM)
  );
  const [resultsEntrySource, setResultsEntrySource] = useState<"app" | "direct" | null>(() =>
    launchState.payload?.nvflare_job_id || readUrlParameter(NVFLARE_JOB_ID_PARAM) ? "direct" : null
  );
  const shouldAutoLogin = Boolean(
    initialUsername &&
      directNVFlareJobId &&
      (!launchState.payload || shouldAutoLoginFromLaunch(launchState.payload))
  );

  const [sessionBase, setSessionBase] = useState<Omit<UserSession, "fhir_source" | "selected_project_id" | "selected_project_datasources"> | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null);
  const pendingRunnerExitRef = useRef<PendingRunnerExit | null>(null);

  function clearDirectResultsState() {
    const url = new URL(window.location.href);
    url.searchParams.delete(NVFLARE_JOB_ID_PARAM);

    const historyState = { ...(window.history.state as AppHistoryState | null) };
    delete historyState.nvflareJobId;

    window.history.replaceState(
      historyState,
      "",
      `${url.pathname}${url.search}${url.hash}`
    );
    setDirectNVFlareJobId(null);
  }

  function leaveDirectResults() {
    if (resultsEntrySource === "app") {
      window.history.back();
      return;
    }

    clearDirectResultsState();
    setResultsEntrySource(null);
    setScreen("home", project ?? undefined, "replace");
  }

  function openProjectJobResults(selectedProject: Project, nvflareJobId: string) {
    const normalizedJobId = String(nvflareJobId || "").trim();
    if (!normalizedJobId) return;

    const nextHistoryState: AppHistoryState = {
      ...((window.history.state as AppHistoryState | null) || {}),
      [APP_HISTORY_STATE_KEY]: true,
      screen: "job_results",
      projectId: selectedProject.id,
      nvflareJobId: normalizedJobId,
      resultsEntrySource: "app",
    };

    window.history.pushState(
      nextHistoryState,
      "",
      buildScreenUrl("job_results")
    );

    setProject(selectedProject);
    setSelectedProjectId(selectedProject.id);
    setDirectNVFlareJobId(normalizedJobId);
    setResultsEntrySource("app");
    setScreenState("job_results");
  }

  function setScreen(
    nextScreen: AppScreen,
    nextProject: Project | null | undefined = undefined,
    historyMode: "push" | "replace" = "push"
  ) {
    const nextProjectId = nextProject === undefined
      ? selectedProjectId
      : nextProject?.id ?? null;

    const leavingCurrentRunner =
      screen === "job_runner" &&
      (nextScreen !== "job_runner" || nextProjectId !== selectedProjectId);

    if (historyMode === "push" && leavingCurrentRunner) {
      const currentHistoryState = (window.history.state || {}) as AppHistoryState;
      const runnerDepth = getRunnerHistoryDepth(currentHistoryState);

      if (runnerDepth > 0) {
        pendingRunnerExitRef.current = { nextScreen, nextProject, nextProjectId };
        window.history.go(-runnerDepth);
        return;
      }
    }

    const sameLocation = screen === nextScreen && selectedProjectId === nextProjectId;
    if (sameLocation && historyMode === "push") {
      setScreenReloadKeys((prev) => ({
        ...prev,
        [nextScreen]: (prev[nextScreen] ?? 0) + 1,
      }));
      return;
    }

    const nextHistoryState: AppHistoryState = {
      ...((window.history.state as AppHistoryState | null) || {}),
      [APP_HISTORY_STATE_KEY]: true,
      screen: nextScreen,
    };

    if (nextProjectId != null) {
      nextHistoryState.projectId = nextProjectId;
    } else {
      delete nextHistoryState.projectId;
    }

    if (nextScreen === "job_results" && directNVFlareJobId) {
      nextHistoryState.nvflareJobId = directNVFlareJobId;
      nextHistoryState.resultsEntrySource = resultsEntrySource || "direct";
    } else {
      delete nextHistoryState.nvflareJobId;
      delete nextHistoryState.resultsEntrySource;
    }

    // A fresh navigation into Analysis Runner should always start a new wizard flow.
    // Browser back/forward restores runner step state through popstate instead of setScreen().
    if (nextScreen !== "job_runner" || screen !== "job_runner" || nextProjectId !== selectedProjectId) {
      delete nextHistoryState.jobRunnerStep;
      delete nextHistoryState.jobRunnerTrail;
      delete nextHistoryState.jobRunnerProjectId;
      delete nextHistoryState.jobRunnerDepth;
    }

    const historyMethod = historyMode === "replace" ? "replaceState" : "pushState";
    window.history[historyMethod](nextHistoryState, "", buildScreenUrl(nextScreen));

    if (nextProject !== undefined) {
      setProject(nextProject);
    } else if (nextProjectId == null) {
      setProject(null);
    }
    setSelectedProjectId(nextProjectId);
    setScreenState(nextScreen);
  }

  useEffect(() => {
    const url = new URL(window.location.href);
    let changed = false;

    for (const parameter of [LAUNCH_PARAM, USERNAME_PARAM, NVFLARE_JOB_ID_PARAM]) {
      if (url.searchParams.has(parameter)) {
        url.searchParams.delete(parameter);
        changed = true;
      }
    }

    if (changed) {
      window.history.replaceState(
        window.history.state,
        "",
        `${url.pathname}${url.search}${url.hash}`
      );
    }
  }, []);

  useEffect(() => {
    const initialHistoryState: AppHistoryState = {
      ...((window.history.state as AppHistoryState | null) || {}),
      [APP_HISTORY_STATE_KEY]: true,
      screen: initialScreenRef.current,
    };

    window.history.replaceState(
      initialHistoryState,
      "",
      buildScreenUrl(initialScreenRef.current)
    );

    const onPopState = (event: PopStateEvent) => {
      const historyState = (event.state || {}) as AppHistoryState;
      const pendingRunnerExit = pendingRunnerExitRef.current;

      if (
        pendingRunnerExit &&
        historyState[APP_HISTORY_STATE_KEY] &&
        historyState.screen === "job_runner" &&
        getRunnerHistoryDepth(historyState) === 0
      ) {
        pendingRunnerExitRef.current = null;

        const destinationState = stripRunnerHistory({
          ...historyState,
          [APP_HISTORY_STATE_KEY]: true,
          screen: pendingRunnerExit.nextScreen,
        });

        if (pendingRunnerExit.nextProjectId != null) {
          destinationState.projectId = pendingRunnerExit.nextProjectId;
        } else {
          delete destinationState.projectId;
        }
        delete destinationState.nvflareJobId;
        delete destinationState.resultsEntrySource;

        window.history.pushState(
          destinationState,
          "",
          buildScreenUrl(pendingRunnerExit.nextScreen)
        );

        if (pendingRunnerExit.nextProject !== undefined) {
          setProject(pendingRunnerExit.nextProject);
        } else if (pendingRunnerExit.nextProjectId == null) {
          setProject(null);
        }
        setSelectedProjectId(pendingRunnerExit.nextProjectId);
        setDirectNVFlareJobId(null);
        setResultsEntrySource(null);
        setScreenState(pendingRunnerExit.nextScreen);
        return;
      }

      const nextScreen = historyState.screen;
      const nextProjectId = historyState.projectId ?? null;
      setDirectNVFlareJobId(
        historyState.nvflareJobId || readUrlParameter(NVFLARE_JOB_ID_PARAM)
      );
      setResultsEntrySource(historyState.resultsEntrySource || null);

      if (historyState[APP_HISTORY_STATE_KEY] && isAppScreen(nextScreen)) {
        setSelectedProjectId(nextProjectId);
        setProject((currentProject) =>
          currentProject?.id === nextProjectId ? currentProject : null
        );
        setScreenState(nextScreen);
      }
    };

    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  useEffect(() => {
    const checkScrollTop = () => {
      setShowScrollToTopButton(window.scrollY > 300);
    };
    window.addEventListener("scroll", checkScrollTop);
    return () => window.removeEventListener("scroll", checkScrollTop);
  }, []);

  useEffect(() => {
    setAnimate(false);
    const t = setTimeout(() => setAnimate(true), 20);
    return () => clearTimeout(t);
  }, [screen]);

  const selectedProjectDatasources = useMemo<UserProjectDatasource[]>(() => {
    if (!sessionBase || selectedProjectId == null) {
      return [];
    }

    const projectEntry = sessionBase.projects.find((entry) => entry.project_id === selectedProjectId);
    return projectEntry?.datasources || [];
  }, [sessionBase, selectedProjectId]);

  const shouldHideFHIRServer = screen === "login" || screen === "home" || screen === "nvflare_manager" || screen === "project_settings";

  const fhirServer = useMemo<string | null>(() => {
    if (shouldHideFHIRServer) {
      return null;
    }

    if (!selectedProjectDatasources.length) {
      return null;
    }

    const defaultDatasource = selectedProjectDatasources.find((entry) => entry.is_default_group);
    return defaultDatasource?.source || selectedProjectDatasources[0]?.source || null;
  }, [selectedProjectDatasources, shouldHideFHIRServer]);

  const validateFHIRServer = (server: string | null): string | null => {
    if (!server) {
      return null;
    }

    if (server.toLowerCase().endsWith(".json")) {
      return null;
    }

    try {
      const url = new URL(server);
      if (!url.pathname.toLowerCase().endsWith("/fhir")) {
        return "The FHIR server appears invalid. Please check the data source provided. NOTE: Should be the FHIR Base URL (ending in /fhir)";
      }
    } catch {
      return "Invalid FHIR server URL format.";
    }
    return null;
  };

  const errorMessage = validateFHIRServer(fhirServer);

  const userSession: UserSession | null = useMemo(() => {
    if (!sessionBase) {
      return null;
    }

    return {
      ...sessionBase,
      selected_project_id: shouldHideFHIRServer ? null : selectedProjectId,
      selected_project_datasources: shouldHideFHIRServer ? [] : selectedProjectDatasources,
      fhir_source: errorMessage ? null : fhirServer,
    };
  }, [sessionBase, selectedProjectId, selectedProjectDatasources, shouldHideFHIRServer, errorMessage, fhirServer]);

  return (
    <UserRoleContext.Provider value={userSession}>
      <HeaderBar
        fhirServer={errorMessage ? null : fhirServer}
        userSession={userSession}
        onUserSettingsClick={userSession ? () => setScreen("user_settings") : undefined}
        onLogoClick={userSession ? () => {
          if (screen === "job_results") {
            leaveDirectResults();
            return;
          }
          setScreen("home");
        } : undefined}
      />

      <div
        className={[
          `app-container ${animate ? "animate-in" : ""}`,
          showScrollToTopButton ? "app-container-scroll-to-top-visible" : "",
          "app-block-01",
        ]
          .filter(Boolean)
          .join(" ")}
      >
        <>
          {screen === "login" && (
            <LoginPage
              key={`login:${screenReloadKeys.login ?? 0}`}
              initialUsername={initialUsername}
              autoLogin={shouldAutoLogin}
              launchError={launchState.error}
              onLogin={(returnedSession: Omit<UserSession, "fhir_source" | "selected_project_id" | "selected_project_datasources">) => {
                setSessionBase(returnedSession);
                setProject(null);
                setSelectedProjectId(null);
                if (directNVFlareJobId) {
                  setResultsEntrySource("direct");
                }
                setScreen(directNVFlareJobId ? "job_results" : "home", null, "replace");
              }}
            />
          )}

          {["home", "job_history", "job_runner", "nvflare_manager", "user_settings", "project_settings", "job_results"].includes(screen) && (
            <SHARELandingPage
              activeScreen={screen}
              jobHistoryReloadKey={screenReloadKeys.job_history ?? 0}
              userSettingsReloadKey={screenReloadKeys.user_settings ?? 0}
              initialProjectId={selectedProjectId}
              resultsJobId={screen === "job_results" ? directNVFlareJobId : null}
              projectsNavOpen={projectsNavOpen}
              onProjectsNavOpenChange={setProjectsNavOpen}
              onOpenHome={() => {
                setScreen("home", null);
              }}
              onOpenProject={(selectedProject) => {
                setScreen("home", selectedProject);
              }}
              onRunAnalysis={(selectedProject) => {
                setScreen("job_runner", selectedProject);
              }}
              onViewJobHistory={(selectedProject) => {
                setScreen("job_history", selectedProject);
              }}
              onOpenProjectSettings={(selectedProject) => {
                setScreen("project_settings", selectedProject);
              }}
              onViewJobResults={(selectedProject, nvflareJobId) => {
                openProjectJobResults(selectedProject, nvflareJobId);
              }}
              onResultsContextLoaded={(resolvedProject) => {
                setProject(resolvedProject);
                setSelectedProjectId(resolvedProject.id);
                const currentHistoryState: AppHistoryState = {
                  ...((window.history.state as AppHistoryState | null) || {}),
                  [APP_HISTORY_STATE_KEY]: true,
                  screen: "job_results",
                  projectId: resolvedProject.id,
                };
                window.history.replaceState(
                  currentHistoryState,
                  "",
                  buildScreenUrl("job_results")
                );
              }}
              onLeaveResults={leaveDirectResults}
              onOpenNVFlareManager={() => {
                setScreen("nvflare_manager");
              }}
              onOpenUserSettings={() => {
                setScreen("user_settings");
              }}
            />
          )}


          {screen === "users_manager" && project && (
            <UserManagerMain
              key={`users_manager:${screenReloadKeys.users_manager ?? 0}`}
              project={project}
              setMainScreen={setScreen}
              fhirServer={errorMessage ? null : fhirServer}
            />
          )}
        </>
      </div>

      <FooterBar />

      <nav>
        <button
          onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
          aria-label="Scroll to the top button."
          className="app-scroll-to-the-top-button" style={{ display: showScrollToTopButton ? "flex" : "none" }}
        >
          ↑
        </button>
      </nav>
    </UserRoleContext.Provider>
  );
};

export default App;
