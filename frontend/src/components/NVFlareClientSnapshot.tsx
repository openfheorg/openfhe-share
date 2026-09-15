import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  API_BASE,
  API_CLIENTS_CONNECTION_STATUS,
  API_CLIENTS_PARTICIPATION_STATUS,
} from "../constants/Constants";
import { FunctionConfigs, ThresholdConfig } from "../types/FunctionConfigs";
import CompactBanner from "./CompactBanner";
import RefreshablePanel from "./RefreshablePanel";
import { HelpPanel, HelpToggle } from "./HelpToggle";
import { useUserSession, UserRole } from "../context/UserRoleContext";

export interface ClientStatus {
  id: string;
  name: string;
  connected: boolean;
  participation?: "ACCEPT" | "REJECT" | "PENDING" | null;
  lastConnect: string;
  isInitiator?: boolean;
  isSubmittedUser?: boolean;
  isServer?: boolean;
  registered?: boolean;
  contributingParty?: boolean;
  analyzingParty?: boolean;
}

export interface ClientParticipationSelection {
  non_contributing_clients: string[];
  exclude_analyzing_clients: string[];
}

interface ClientSnapshotProps {
  projectId?: number;
  filtersPayload?: any;
  functionsMap?: FunctionConfigs;
  thresholdConfig?: ThresholdConfig;
  header?: string;
  heartbeatWindowMs?: number;
  onState?: (state: { loading: boolean; clients: ClientStatus[] }) => void;
  onParticipationSelectionChange?: (
    selection: ClientParticipationSelection,
  ) => void;
  onError?: (message: string) => void;
  compact?: boolean;
  canSubmit?: boolean;
  embedded?: boolean;
  showBorder?: boolean;
}

function isParticipationSelectable(client: ClientStatus): boolean {
  if (client.isServer) {
    return false;
  }
  const participation = client.isSubmittedUser
    ? "ACCEPT"
    : client.participation || "PENDING";
  return (
    participation === "ACCEPT" ||
    participation === "PENDING" ||
    participation === "REJECT"
  );
}

function isAnalyzingLocked(client: ClientStatus): boolean {
  return !!client.isInitiator || !!client.isServer;
}

function normalizeParticipation(value?: string | null): string {
  switch ((value || "").toUpperCase()) {
    case "ACCEPT":
      return "Accepted";
    case "REJECT":
      return "Rejected";
    case "PENDING":
      return "Pending";
    default:
      return "Accepted";
  }
}

function formatUtcCheckInTimestamp(date: Date): string {
  const weekdays = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const months = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
  ];
  const pad = (value: number) => value.toString().padStart(2, "0");

  return `${weekdays[date.getUTCDay()]} ${months[date.getUTCMonth()]} ${pad(date.getUTCDate())} ${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}:${pad(date.getUTCSeconds())} ${date.getUTCFullYear()} (UTC)`;
}

function formatClientCheckInTimestamp(value: string): string {
  const raw = String(value || "").trim();
  if (!raw || raw === "-" || raw === "0") {
    return "-";
  }
  return raw.endsWith("(UTC)") ? raw : `${raw} (UTC)`;
}

function getPartyStatusLines(
  participationLabel: string,
  isContributing: boolean,
  isAnalyzing: boolean,
): { label: string; value: string }[] {
  return [
    { label: "Participation", value: participationLabel },
    { label: "Analyzing", value: isAnalyzing ? "Yes" : "No" },
    { label: "Contributing", value: isContributing ? "Yes" : "No" },
  ];
}

function getPartyStatusValueColor(value: string): string | undefined {
  if (value === "Yes") {
    return "green";
  }
  if (value === "No") {
    return "red";
  }
  return undefined;
}

// The landing-page NVFlare Manager is frequently left and revisited. Retain
// its last successful connection snapshot so the table stays visible while a
// fresh request runs instead of flashing a temporary Loading message.
let cachedManagerClients: ClientStatus[] = [];

const NVFlareClientSnapshot: React.FC<ClientSnapshotProps> = ({
  projectId,
  filtersPayload,
  functionsMap,
  thresholdConfig,
  header = "Participants Status",
  heartbeatWindowMs = 60000,
  onState,
  onParticipationSelectionChange,
  onError,
  compact = false,
  canSubmit = false,
  embedded = false,
  showBorder = true,
}) => {
  const { role, username } = useUserSession();
  const isLandingManagerSnapshot = embedded && projectId == null && !functionsMap;
  const [loading, setLoading] = useState(false);
  const [loadingConnectionState, setLoadingConnectionState] = useState(false);
  const [clients, setClients] = useState<ClientStatus[]>(() =>
    isLandingManagerSnapshot ? cachedManagerClients : []
  );
  const [contributingByClient, setContributingByClient] = useState<
    Record<string, boolean>
  >({});
  const [analyzingByClient, setAnalyzingByClient] = useState<
    Record<string, boolean>
  >({});
  const [contributingHelpOpen, setContributingHelpOpen] = useState(false);
  const [analyzingHelpOpen, setAnalyzingHelpOpen] = useState(false);
  const onStateRef = useRef(onState);
  const onParticipationSelectionChangeRef = useRef(
    onParticipationSelectionChange,
  );
  const onErrorRef = useRef(onError);
  const inFlightRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  const clientsRef = useRef<ClientStatus[]>([]);
  const contributingByClientRef = useRef<Record<string, boolean>>({});
  const analyzingByClientRef = useRef<Record<string, boolean>>({});
  const hasLoadedConnectionStateRef = useRef(false);
  const lastParticipationSelectionHashRef = useRef<string | null>(null);

  useEffect(() => {
    onStateRef.current = onState;
  }, [onState]);

  useEffect(() => {
    onParticipationSelectionChangeRef.current = onParticipationSelectionChange;
  }, [onParticipationSelectionChange]);

  useEffect(() => {
    onErrorRef.current = onError;
  }, [onError]);

  useEffect(() => {
    clientsRef.current = clients;
  }, [clients]);

  useEffect(() => {
    contributingByClientRef.current = contributingByClient;
  }, [contributingByClient]);

  useEffect(() => {
    analyzingByClientRef.current = analyzingByClient;
  }, [analyzingByClient]);

  const includeParticipation = useMemo(() => {
    return (
      !!functionsMap &&
      Object.keys(functionsMap).length > 0 &&
      typeof filtersPayload !== "undefined"
    );
  }, [functionsMap, filtersPayload]);

  const includeThreshold = useMemo(() => {
    return (
      !!thresholdConfig &&
      !!thresholdConfig.enabled &&
      !!thresholdConfig.thresholdMethod &&
      thresholdConfig.threshold != null
    );
  }, [thresholdConfig]);

  const buildParticipationSelection = useCallback(
    (
      clientRows: ClientStatus[] = clientsRef.current,
      contributingMap: Record<string, boolean> = contributingByClientRef.current,
      analyzingMap: Record<string, boolean> = analyzingByClientRef.current,
    ): ClientParticipationSelection => {
      if (!includeParticipation) {
        return {
          non_contributing_clients: [],
          exclude_analyzing_clients: [],
        };
      }

      const selectableClients = clientRows.filter(isParticipationSelectable);
      const nonContributingClients = selectableClients
        .filter((client) => contributingMap[client.name] === false)
        .map((client) => client.name);
      const excludeAnalyzingClients = selectableClients
        .filter(
          (client) =>
            !isAnalyzingLocked(client) && analyzingMap[client.name] === false,
        )
        .map((client) => client.name);

      return {
        non_contributing_clients: nonContributingClients,
        exclude_analyzing_clients: excludeAnalyzingClients,
      };
    },
    [includeParticipation],
  );

  const participationSelectionHash = useMemo(() => {
    return JSON.stringify(
      buildParticipationSelection(
        clients,
        contributingByClient,
        analyzingByClient,
      ),
    );
  }, [
    buildParticipationSelection,
    clients,
    contributingByClient,
    analyzingByClient,
  ]);

  const fetchClients = useCallback(
    async (options?: { includeConnectionState?: boolean }) => {
      if (inFlightRef.current) {
        abortRef.current?.abort();
      }
      inFlightRef.current = true;
      const includeConnectionState = options?.includeConnectionState ?? true;
      setLoading(true);
      setLoadingConnectionState(includeConnectionState);
      const controller = new AbortController();
      abortRef.current = controller;

      try {
        let body: any = {};

        if (role === UserRole.INITIATOR && username) {
          body.username = username;
        }

        if (includeParticipation) {
          const participationSelection = buildParticipationSelection();
          const participation: any = {
            filters: filtersPayload,
            project_id: projectId,
            functions: functionsMap,
            non_contributing_clients:
              participationSelection.non_contributing_clients,
            exclude_analyzing_clients:
              participationSelection.exclude_analyzing_clients,
          };

          if (includeThreshold && thresholdConfig) {
            participation.threshold_config = {
              method: thresholdConfig.thresholdMethod,
              threshold: thresholdConfig.threshold,
            };
          }

          body.include_connection_state = includeConnectionState;
          body.participation_status = participation;
        }

        const res = await fetch(
          `${API_BASE}${
            includeParticipation
              ? API_CLIENTS_PARTICIPATION_STATUS
              : API_CLIENTS_CONNECTION_STATUS
          }`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
            signal: controller.signal,
          },
        );
        if (!res.ok) throw new Error(`Clients API ${res.status}`);
        const data = await res.json();
        const rows = Array.isArray(data?.clients) ? data.clients : [];

        if (includeParticipation && !includeConnectionState) {
          const participationByClient: Record<string, any> = {};
          rows.forEach((row: any) => {
            const name = String(row?.client_name ?? "").trim();
            if (name) {
              participationByClient[name] = row;
            }
          });

          const merged = clientsRef.current.map((client) => {
            const participation = participationByClient[client.name];
            return {
              ...client,
              participation: participation
                ? (participation.participation ?? "PENDING")
                : "PENDING",
              contributingParty: participation
                ? participation.contributing_party !== false
                : true,
              analyzingParty: participation
                ? participation.analyzing_party !== false
                : true,
            } as ClientStatus;
          });

          setClients(merged);
          setLoading(false);
          setLoadingConnectionState(false);
          onStateRef.current?.({ loading: false, clients: merged });
          return;
        }

        const mapped: ClientStatus[] = rows
          .map((c: any, idx: number) => {
            const raw = String(c.last_connect_time ?? "");
            const isOfflineSentinel = raw === "0";
            const parsed = !isOfflineSentinel
              ? Date.parse(/Z$|[A-Z]{2,}$/.test(raw) ? raw : `${raw} UTC`)
              : NaN;
            const now = Date.now();
            const heartbeatConnected =
              !isNaN(parsed) && now - parsed <= heartbeatWindowMs;
            const isServer =
              String(c.client_name ?? "").trim().toLowerCase() === "server" ||
              !!c.is_server;
            const connected = isServer
              ? c.server_online !== false
              : isOfflineSentinel
                ? false
                : heartbeatConnected;
            const lastConnect = isServer
              ? connected
                ? formatUtcCheckInTimestamp(new Date(now))
                : "-"
              : isOfflineSentinel
                ? "-"
                : formatClientCheckInTimestamp(raw);
            return {
              id: (idx + 1).toString(),
              name: c.client_name,
              connected,
              participation: includeParticipation
                ? (c.participation ?? "PENDING")
                : undefined,
              lastConnect,
              isInitiator: !!c.is_initiator,
              isSubmittedUser: !!c.is_submitted_user,
              isServer,
              registered: isServer ? true : c.registered !== false,
              contributingParty: c.contributing_party,
              analyzingParty: c.analyzing_party,
            } as ClientStatus;
          })
          .sort((a: ClientStatus, b: ClientStatus) => {
            if (a.isSubmittedUser && !b.isSubmittedUser) return -1;
            if (!a.isSubmittedUser && b.isSubmittedUser) return 1;
            return a.name.localeCompare(b.name);
          });

        const nextContributingByClient: Record<string, boolean> = {};
        const nextAnalyzingByClient: Record<string, boolean> = {};
        mapped.forEach((client) => {
          if (isParticipationSelectable(client)) {
            nextContributingByClient[client.name] =
              contributingByClientRef.current[client.name] ?? true;
            nextAnalyzingByClient[client.name] = isAnalyzingLocked(client)
              ? true
              : (analyzingByClientRef.current[client.name] ?? true);
          }
        });

        if (includeConnectionState) {
          hasLoadedConnectionStateRef.current = true;
          lastParticipationSelectionHashRef.current = JSON.stringify(
            buildParticipationSelection(
              mapped,
              nextContributingByClient,
              nextAnalyzingByClient,
            ),
          );
        }

        if (isLandingManagerSnapshot) {
          cachedManagerClients = mapped;
        }
        setClients(mapped);
        setContributingByClient(nextContributingByClient);
        setAnalyzingByClient(nextAnalyzingByClient);
        setLoading(false);
        setLoadingConnectionState(false);
        onStateRef.current?.({ loading: false, clients: mapped });
      } catch (e) {
        if ((e as any)?.name === "AbortError") {
          setLoadingConnectionState(false);
          inFlightRef.current = false;
          return;
        }
        setLoading(false);
        setLoadingConnectionState(false);
        onErrorRef.current?.("Failed to refresh clients list.");
      } finally {
        inFlightRef.current = false;
      }
    },
    [
      heartbeatWindowMs,
      buildParticipationSelection,
      includeParticipation,
      includeThreshold,
      filtersPayload,
      functionsMap,
      projectId,
      thresholdConfig,
      role,
      username,
      isLandingManagerSnapshot,
    ],
  );

  useEffect(() => {
    let idleId: number | null = null as any;
    let timeoutId: number | null = null;

    const start = () => {
      const ric: any = (window as any).requestIdleCallback;
      if (compact && typeof ric === "function") {
        idleId = ric(() => fetchClients({ includeConnectionState: true }));
      } else {
        timeoutId = window.setTimeout(
          () => fetchClients({ includeConnectionState: true }),
          0,
        );
      }
    };

    start();

    return () => {
      if (idleId != null && (window as any).cancelIdleCallback) {
        (window as any).cancelIdleCallback(idleId);
      }
      if (timeoutId != null) window.clearTimeout(timeoutId);
      abortRef.current?.abort();
    };
  }, [fetchClients, compact]);

  useEffect(() => {
    if (!includeParticipation) {
      lastParticipationSelectionHashRef.current = null;
      return;
    }

    if (!hasLoadedConnectionStateRef.current) {
      lastParticipationSelectionHashRef.current = participationSelectionHash;
      return;
    }

    if (lastParticipationSelectionHashRef.current === null) {
      lastParticipationSelectionHashRef.current = participationSelectionHash;
      return;
    }

    if (lastParticipationSelectionHashRef.current !== participationSelectionHash) {
      lastParticipationSelectionHashRef.current = participationSelectionHash;
      fetchClients({ includeConnectionState: false });
    }
  }, [includeParticipation, participationSelectionHash, fetchClients]);

  useEffect(() => {
    if (!includeParticipation) {
      onParticipationSelectionChangeRef.current?.({
        non_contributing_clients: [],
        exclude_analyzing_clients: [],
      });
      return;
    }

    onParticipationSelectionChangeRef.current?.(buildParticipationSelection());
  }, [includeParticipation, buildParticipationSelection, participationSelectionHash]);

  const setClientContributing = (clientName: string, checked: boolean) => {
    setContributingByClient((prev) => ({
      ...prev,
      [clientName]: checked,
    }));
  };

  const setClientAnalyzing = (clientName: string, checked: boolean) => {
    const client = clients.find((c) => c.name === clientName);
    if (client && isAnalyzingLocked(client)) {
      return;
    }

    setAnalyzingByClient((prev) => ({
      ...prev,
      [clientName]: checked,
    }));
  };

  const note = (
    <>
      <strong>NOTE:</strong> A client is considered <em>connected</em> if its
      last check-in was within the last {heartbeatWindowMs / 1000} seconds.
    </>
  );

  if (compact) {
    const server = clients.find((client) => client.isServer);
    const remoteClients = clients.filter((client) => !client.isServer);
    const totalRegistered = remoteClients.length;
    const connectedCount = remoteClients.filter((c) => c.connected).length;
    const disconnectedCount = totalRegistered - connectedCount;

    if (loading && totalRegistered === 0) {
      return (
        <div className="nvflare-client-snapshot-block-01">Retrieving Server Status...</div>
      );
    }

    if (!loading && totalRegistered === 0) {
      return (
        <CompactBanner>
          No registered clients are currently configured.
        </CompactBanner>
      );
    }

    return (
      <CompactBanner>
        <span className="duality-font-semibold">Clients:</span>
        <hr className="duality-m-0-0-0p4rem-0" />

        {server && (
          <div
            className="duality-d-flex-justify-space-between-mb-0p15rem"
          >
            <span>Server: </span>
            <span
              className="nvflare-client-snapshot-block-02" style={{ color: server.connected ? "green" : "#a0150eff" }}
            >
              {server.connected ? "Online" : "Offline"}
            </span>
          </div>
        )}

        <div
          className="duality-d-flex-justify-space-between-mb-0p15rem"
        >
          <span>Total Registered: </span>
          <span className="duality-text-right">{totalRegistered}</span>
        </div>

        <div className="duality-flex-between">
          <span>Connected: </span>
          <span
            className="duality-weight-600-text-3f5fff-text-right"
          >
            {connectedCount || "UNKNOWN"}
          </span>
        </div>

        {disconnectedCount > 0 && (
          <div className="duality-flex-between">
            <span>Not Connected</span>
            <span
              className="nvflare-client-snapshot-block-03"
            >
              {disconnectedCount}
            </span>
          </div>
        )}
      </CompactBanner>
    );
  }

  const server = clients.find((client) => client.isServer);
  const serverLastCheckIn = server?.lastConnect ?? "-";
  const hasClientRows = clients.length > 0;
  const isInitialLoading = loading && !hasClientRows;
  const isRefreshingConnectionState = loadingConnectionState && hasClientRows;
  const isGatheringManagerStatus = isLandingManagerSnapshot && loadingConnectionState;

  return (
    <div
      className={`page-container ${embedded ? "nvflare-client-snapshot-embedded" : ""} ${!showBorder ? "nvflare-client-snapshot-no-border" : ""}`}
    >
      <RefreshablePanel
        accordion={true}
        accordionDefaultExpanded={true}
        header={header}
        loading={isInitialLoading && !isLandingManagerSnapshot}
        onRefresh={() => fetchClients({ includeConnectionState: true })}
        refreshAriaLabel="Refresh clients"
        refreshTitle="Refresh"
        note={note}
        right={
          isGatheringManagerStatus || isRefreshingConnectionState ? (
            <span
              className="nvflare-client-snapshot-block-04"
            >
              {isGatheringManagerStatus
                ? "Gathering Server and Party Status..."
                : "Refreshing Party Connection and Participation Status"}
            </span>
          ) : undefined
        }
      >
        <table className="duality-table-full">
          <thead>
            <tr>
              <th className="nvflare-client-snapshot-shared-01">
                Party
              </th>
              <th className="nvflare-client-snapshot-shared-01">
                State
              </th>
              {includeParticipation && (
                <th
                  className="nvflare-client-snapshot-shared-02"
                >
                  <div
                    className="nvflare-client-snapshot-shared-03"
                  >
                    <span>Contributing Party</span>
                    <HelpToggle
                      open={contributingHelpOpen}
                      onToggle={() => setContributingHelpOpen((prev) => !prev)}
                      ariaLabel="Info about contributing parties"
                      title="Info about contributing parties"
                    />
                  </div>
                  <HelpPanel
                    open={contributingHelpOpen}
                    text="Parties that contribute data to the analysis."
                  />
                </th>
              )}
              <th className="nvflare-client-snapshot-shared-01">
                Last Check-in
              </th>
              {includeParticipation && (
                <th
                  className="nvflare-client-snapshot-shared-02"
                >
                  <div
                    className="nvflare-client-snapshot-shared-03"
                  >
                    <span>Analyzing Party</span>
                    <HelpToggle
                      open={analyzingHelpOpen}
                      onToggle={() => setAnalyzingHelpOpen((prev) => !prev)}
                      ariaLabel="Info about analyzing parties"
                      title="Info about analyzing parties"
                    />
                  </div>
                  <HelpPanel
                    open={analyzingHelpOpen}
                    text="Parties that will receive the analysis results."
                  />
                </th>
              )}
              {includeParticipation && (
                <th
                  className="nvflare-client-snapshot-shared-01"
                >
                  Party Status
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {clients.filter((client) => !client.isServer).map((c) => {
              const selectable = isParticipationSelectable(c);
              const participationLabel = c.isSubmittedUser
                ? "Accepted"
                : normalizeParticipation(c.participation);
              const analyzingLocked = isAnalyzingLocked(c);
              const isContributing = contributingByClient[c.name] ?? true;
              const isAnalyzing = analyzingLocked
                ? true
                : (analyzingByClient[c.name] ?? true);
              const partyStatusLines = getPartyStatusLines(
                participationLabel,
                isContributing,
                isAnalyzing,
              );

              return (
                <tr key={c.id}>
                  <td className="nvflare-client-snapshot-shared-04">
                    {c.name}
                    {c.isInitiator ? " - INITIATOR" : ""}
                    {c.isSubmittedUser ? " (You)" : ""}
                    {c.registered === false && !c.isServer ? " (Unregistered)" : ""}
                  </td>
                  <td className="nvflare-client-snapshot-shared-04">
                    {c.connected ? "Connected" : "Offline"}
                  </td>
                  {includeParticipation && (
                    <td className="nvflare-client-snapshot-shared-05">
                      {selectable && (
                        <input
                          type="checkbox"
                          checked={isContributing}
                          disabled={!canSubmit}
                          onChange={(event) =>
                            setClientContributing(c.name, event.target.checked)
                          }
                          aria-label={`${c.name} contributing party`}
                          title={!canSubmit ? "Modification requires job to be in a submittable state" : "Parties that contribute data to the analysis."}
                          className="nvflare-client-snapshot-shared-06" style={{ cursor: canSubmit ? "pointer" : "not-allowed" }}
                        />
                      )}
                    </td>
                  )}
                  <td className="nvflare-client-snapshot-shared-04">{c.lastConnect}</td>
                  {includeParticipation && (
                    <td className="nvflare-client-snapshot-shared-05">
                      {selectable && (
                        <input
                          type="checkbox"
                          checked={isAnalyzing}
                          disabled={analyzingLocked || !canSubmit}
                          onChange={(event) =>
                            setClientAnalyzing(c.name, event.target.checked)
                          }
                          aria-label={`${c.name} analyzing party`}
                          title={
                            analyzingLocked
                              ? "This option cannot be modified"
                              : !canSubmit
                                ? "Modification requires job to be in a submittable state"
                                : "Parties that will receive the analysis results."
                          }
                          className="nvflare-client-snapshot-shared-06" style={{ cursor:
                              analyzingLocked || !canSubmit
                                ? "not-allowed"
                                : "pointer" }}
                        />
                      )}
                    </td>
                  )}
                  {includeParticipation && (
                    <td className="nvflare-client-snapshot-shared-04">
                      {partyStatusLines.map((line) => (
                        <div key={line.label}>
                          {line.label}:{" "}
                          <span
                            className="nvflare-client-snapshot-shared-07" style={{ color: getPartyStatusValueColor(line.value) }}
                          >
                            {line.value}
                          </span>
                        </div>
                      ))}
                    </td>
                  )}
                </tr>
              );
            })}
            {includeParticipation && server && (
              <tr>
                <td
                  className="nvflare-client-snapshot-block-05"
                >
                  Server
                </td>
                <td
                  className="nvflare-client-snapshot-shared-08"
                >
                  {server.connected ? "Online" : "Offline"}
                </td>
                <td
                  className="nvflare-client-snapshot-shared-09"
                >
                  <input
                    type="checkbox"
                    checked={false}
                    disabled
                    aria-label="Server is not contributing"
                    title="This option cannot be modified"
                    className="nvflare-client-snapshot-shared-10"
                  />
                </td>
                <td
                  className="nvflare-client-snapshot-shared-08"
                >
                  {serverLastCheckIn}
                </td>
                <td
                  className="nvflare-client-snapshot-shared-09"
                >
                  <input
                    type="checkbox"
                    checked={false}
                    disabled
                    aria-label="Server is not an analyzing party"
                    title="This option cannot be modified"
                    className="nvflare-client-snapshot-shared-10"
                  />
                </td>
                <td
                  className="nvflare-client-snapshot-shared-08"
                >
                  {getPartyStatusLines("Always Active", false, false).map((line) => (
                    <div key={line.label}>
                      {line.label}:{" "}
                      <span
                        className="nvflare-client-snapshot-shared-07" style={{ color: getPartyStatusValueColor(line.value) }}
                      >
                        {line.value}
                      </span>
                    </div>
                  ))}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </RefreshablePanel>
    </div>
  );
};

export default NVFlareClientSnapshot;
