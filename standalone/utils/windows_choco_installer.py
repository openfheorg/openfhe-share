# purpose: helper to install Chocolatey on Windows when needed
# provides a small elevate helper using ShellExecute runas
# verifies install by running choco -v and explains next steps when PATH is not refreshed
# intended to be imported and called by the orchestrator rather than run directly

import sys, shutil, subprocess, platform

# return true when running on Windows
def is_windows():
    return platform.system() == "Windows"

# return true when the choco executable is available on PATH
def choco_installed():
    return shutil.which("choco") is not None

# run a command either normally or with elevation on Windows
# when elevate is true use ShellExecute to trigger a UAC prompt and run the command as admin
def run(cmd, elevate=False):
    if elevate:
        import ctypes
        params = f'/c {cmd}'
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", "C:\\Windows\\System32\\cmd.exe", params, None, 1
        )
        if rc <= 32:
            raise RuntimeError("User declined elevation or elevation failed.")
        return 0
    else:
        return subprocess.run(cmd, shell=True, check=True).returncode

# install Chocolatey on Windows
# returns true on success and false when user declines or PATH needs a new terminal
def install_chocolatey() -> bool:
    if not is_windows():
        print("Not Windows; skipping Chocolatey.")
        return False
    if choco_installed():
        print("Chocolatey already installed.")
        return True

    # official install command from Chocolatey docs executed under elevated PowerShell
    ps = (
        r'Set-ExecutionPolicy Bypass -Scope Process -Force; '
        r'[System.Net.ServicePointManager]::SecurityProtocol = '
        r'[System.Net.SecurityProtocolType]::Tls12; '
        r'iex ((New-Object System.Net.WebClient).DownloadString('
        r'\'https://community.chocolatey.org/install.ps1\'))'
    )
    try:
        print("Requesting elevation to install Chocolatey (UAC prompt)…")
        run(f'powershell -NoProfile -ExecutionPolicy Bypass -Command "{ps}"', elevate=True)
    except Exception as e:
        print(f"Chocolatey install aborted/failed: {e}")
        return False

    # verify installation and provide guidance if PATH is not yet refreshed
    try:
        subprocess.run("choco -v", shell=True, check=True)
        print("Chocolatey installed.")
        return True
    except subprocess.CalledProcessError:
        print("Chocolatey install likely succeeded but PATH not refreshed. Open a new terminal and run `choco -v`.")
        return False

# prevent direct execution and guide users toward the orchestrator entry point
if __name__ == "__main__":
    print("This module is meant to be used via the orchestrator, not run directly.\n"
          "Use: python main.py mysql  (which may call Chocolatey install if needed)")
    sys.exit(1)
