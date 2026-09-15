#!/usr/bin/env python3
"""
Generate FL profiling CSVs from one server JSON and many client JSONs.

Inputs:
  - One or more JSON files produced by the profiler (server or client).
    The script will auto-detect role via "role" and site via "site".

Outputs (written to --outdir, default current dir):
  - <job_id>_round_breakdown_wide.csv
      Columns: "{workflow}_r{round}" for each observed pair
      Rows:
        - "workflow"
        - "round"
        - For each client site (sorted by name):
            * f"server_to_{site}_transfer_time_sec"        # client downstream RTT
            * f"{site}_compute_time_sec"                   # client compute window
            * f"{site}_to_server_transfer_time_sec"        # client upstream RTT
        - "server_time_sec"                                # server compute window
        - "server_to_client_transfer_payload_MB"           # total payload out (server->clients) per round (MB, 10^6)
        - "client_to_server_transfer_payload_MB"           # total payload in (clients->server) per round (MB, 10^6)

  - <job_id>_system_metrics_wide.csv
      Rows (metrics):
        job_id, site, role, wall_time_sec, cpu_util_pct, cpu_user_pct, cpu_system_pct,
        cpu_iowait_pct, cpu_steal_pct, net_tx_bytes_total, net_rx_bytes_total,
        net_tx_mb_s, net_rx_mb_s, rss_max_kb
      Columns: one per site (server and each client), named by the file's "site" field.

Usage:
  python generate_csv_results.py server.json client1.json [client2.json ...] --outdir results/

IMPORTANT: Replace all "-1" rounds to "0" in client profile_summary jsons before using this script,
"""

import argparse
import json
import sys
from pathlib import Path
from collections import defaultdict, OrderedDict

try:
    import pandas as pd  # type: ignore
except Exception as e:
    print("This script requires pandas. Please install with `pip install pandas`.", file=sys.stderr)
    raise


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def detect_role_site(obj: dict) -> tuple[str, str]:
    role = (obj.get("role") or "").lower()
    site = obj.get("site") or ""
    # Heuristic fallback if role missing
    if not role:
        if site in ("server", "simulator_server"):
            role = "server"
        else:
            role = "client"
    return role, site or ("server" if role == "server" else "client")


def flatten_server(obj: dict) -> list[dict]:
    rows = []
    for wf, rounds in (obj.get("workflows") or {}).items():
        for r_str, vals in (rounds or {}).items():
            try:
                r = int(r_str)
            except Exception:
                continue
            rows.append({
                "workflow": wf,
                "round": r,
                "server_time_sec": float(vals.get("server_compute_time_sec", 0.0)),
                "payload_in_bytes": int(vals.get("payload_in_bytes", 0)),    # clients -> server (sum)
                "payload_out_bytes": int(vals.get("payload_out_bytes", 0)),  # server -> clients (sum)
            })
    return rows


def flatten_client(obj: dict, site: str) -> list[dict]:
    rows = []
    for wf, rounds in (obj.get("workflows") or {}).items():
        for r_str, vals in (rounds or {}).items():
            try:
                r = int(r_str)
            except Exception:
                continue
            rows.append({
                "site": site,
                "workflow": wf,
                "round": r,
                "downstream_rtt_sec": float(vals.get("downstream_rtt_sec", 0.0)),         # server -> site
                "client_compute_time_sec": float(vals.get("client_compute_time_sec", 0.0)),
                "upstream_rtt_sec": float(vals.get("upstream_rtt_sec", 0.0)),             # site -> server
            })
    return rows


def to_mb(x: float | int) -> float:
    try:
        return round(float(x) / 1_000_000.0, 6)  # MB (10^6)
    except Exception:
        return 0.0


def build_round_breakdown_wide(server_rows: list[dict], clients_rows: list[dict]) -> "pd.DataFrame":
    # Index server rows by (wf, round)
    srv_map: dict[tuple[str, int], dict] = {}
    for r in server_rows:
        srv_map[(r["workflow"], r["round"])] = r

    # Collect unique sites and all (wf, round) pairs
    sites = sorted({r["site"] for r in clients_rows})
    keys = set(srv_map.keys())
    for r in clients_rows:
        keys.add((r["workflow"], r["round"]))
    # Sort keys by workflow then round
    keys = sorted(keys, key=lambda x: (x[0], x[1]))

    # Build columns = {workflow}_r{round}
    cols = OrderedDict()
    for wf, rnd in keys:
        col_label = f"{wf}_r{rnd}"
        cols[col_label] = {
            "workflow": wf,
            "round": rnd,
        }
        # Per-site metrics from clients
        for site in sites:
            # Find matching row for this site/wf/rnd
            match = next((r for r in clients_rows if r["site"] == site and r["workflow"] == wf and r["round"] == rnd), None)
            cols[col_label][f"server_to_{site}_transfer_time_sec"] = float(match.get("downstream_rtt_sec", 0.0)) if match else 0.0
            cols[col_label][f"{site}_compute_time_sec"] = float(match.get("client_compute_time_sec", 0.0)) if match else 0.0
            cols[col_label][f"{site}_to_server_transfer_time_sec"] = float(match.get("upstream_rtt_sec", 0.0)) if match else 0.0

        # Server-side fields
        srv = srv_map.get((wf, rnd), {})
        cols[col_label]["server_time_sec"] = float(srv.get("server_time_sec", 0.0))
        cols[col_label]["server_to_client_transfer_payload_MB"] = to_mb(srv.get("payload_out_bytes", 0))
        cols[col_label]["client_to_server_transfer_payload_MB"] = to_mb(srv.get("payload_in_bytes", 0))

    # Assemble DataFrame with rows (metrics) and columns as {workflow}_r{round}
    # Row order: workflow, round, then per-site triples, then server_time, payload totals
    row_names = ["workflow", "round"]
    for site in sites:
        row_names.extend([
            f"server_to_{site}_transfer_time_sec",
            f"{site}_compute_time_sec",
            f"{site}_to_server_transfer_time_sec",
        ])
    row_names.extend([
        "server_time_sec",
        "server_to_client_transfer_payload_MB",
        "client_to_server_transfer_payload_MB",
    ])

    import pandas as pd
    df = pd.DataFrame.from_dict(cols, orient="columns")
    # Ensure all row_names present; add missing with zeros where needed
    for rn in row_names:
        if rn not in df.index and rn not in df:
            df.loc[rn] = 0.0
    # Reindex rows in the requested order
    df = df.reindex(row_names)
    df.insert(0, "metric", df.index)
    df.reset_index(drop=True, inplace=True)
    return df


def build_system_metrics_wide(objs: list[dict]) -> "pd.DataFrame":
    # Columns by site name
    # Rows are fixed metric names in this order
    metric_rows = [
        "job_id",
        "site",
        "role",
        "wall_time_sec",
        "cpu_util_pct",
        "cpu_user_pct",
        "cpu_system_pct",
        "cpu_iowait_pct",
        "cpu_steal_pct",
        "net_tx_bytes_total",
        "net_rx_bytes_total",
        "net_tx_mb_s",
        "net_rx_mb_s",
        "rss_max_kb",
    ]

    cols: dict[str, list] = {"metric": metric_rows}
    for obj in objs:
        role, site = detect_role_site(obj)
        sm = obj.get("system_metrics", {}) or {}
        col_vals = [
            obj.get("job_id", ""),
            obj.get("site", site),
            obj.get("role", role),
            sm.get("wall_time_sec", 0.0),
            sm.get("cpu_util_pct", 0.0),
            sm.get("cpu_user_pct", 0.0),
            sm.get("cpu_system_pct", 0.0),
            sm.get("cpu_iowait_pct", 0.0),
            sm.get("cpu_steal_pct", 0.0),
            sm.get("net_tx_bytes_total", 0),
            sm.get("net_rx_bytes_total", 0),
            sm.get("net_tx_mb_s", 0.0),
            sm.get("net_rx_mb_s", 0.0),
            sm.get("rss_max_kb", 0),
        ]
        cols[site or role] = col_vals

    import pandas as pd
    df = pd.DataFrame(cols)
    return df


def main():
    ap = argparse.ArgumentParser(description="Generate round & system CSVs from FL profiler JSONs.")
    ap.add_argument("json_files", nargs="+", help="One server JSON and one or more client JSONs.")
    ap.add_argument("--outdir", default=".", help="Output directory for CSV files.")
    args = ap.parse_args()

    paths = [Path(p) for p in args.json_files]
    objs = [load_json(p) for p in paths]

    # Partition server vs clients
    servers = []
    clients = []
    for obj in objs:
        role, site = detect_role_site(obj)
        if role == "server":
            servers.append(obj)
        else:
            clients.append(obj)

    if not servers:
        print("WARNING: No server JSON provided. Server compute/payload fields will be zeros.", file=sys.stderr)

    # Choose first server if multiple
    server = servers[0] if servers else {"workflows": {}}

    # Flatten
    server_rows = flatten_server(server)
    client_rows_all = []
    for c in clients:
        _, site = detect_role_site(c)
        client_rows_all.extend(flatten_client(c, site))

    # Build dataframes
    df_round = build_round_breakdown_wide(server_rows, client_rows_all)
    df_sys   = build_system_metrics_wide([server] + clients)

    # Output filenames (based on server job_id if available)
    job_id = server.get("job_id") or (clients[0].get("job_id") if clients else "job")
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    rounds_csv = outdir / f"{job_id}_round_breakdown_wide.csv"
    sys_csv    = outdir / f"{job_id}_system_metrics_wide.csv"

    df_round.to_csv(rounds_csv, index=False)
    df_sys.to_csv(sys_csv, index=False)

    # print(f"Wrote:\n  {rounds_csv}\n  {sys_csv}")


if __name__ == "__main__":
    main()
