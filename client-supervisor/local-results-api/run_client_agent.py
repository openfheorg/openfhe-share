import argparse
import os
import subprocess
import sys


def main():
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["build_deploy", "start", "stop", "status"])
    p.add_argument("--workspace", required=False, default="")
    p.add_argument("--installdocker", action="store_true")
    p.add_argument("--ui_origins", default="")
    args, unknown = p.parse_known_args()

    here = os.path.dirname(os.path.abspath(__file__))
    script = os.path.join(here, "agent_manage.py")

    cmd = [sys.executable, script, args.cmd]
    if args.workspace:
        cmd += ["--workspace", args.workspace]
    if args.installdocker:
        cmd += ["--installdocker"]
    if args.ui_origins:
        cmd += ["--ui_origins", args.ui_origins]
    cmd += unknown

    subprocess.check_call(cmd)


if __name__ == "__main__":
    main()
