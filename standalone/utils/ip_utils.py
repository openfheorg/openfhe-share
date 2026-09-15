import re
import socket
import subprocess

_IPV4_RE = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")

def _is_valid_ipv4(s: str) -> bool:
    if not _IPV4_RE.match(s):
        return False
    parts = s.split(".")
    try:
        ok = all(0 <= int(p) <= 255 for p in parts)
    except ValueError:
        return False
    # reject loopback and unspecified
    return ok and s not in ("0.0.0.0", "127.0.0.1")

def get_ip() -> str:
    # 1) Most reliable: use a UDP "connect" to infer the outbound IP
    for target in ("8.8.8.8", "1.1.1.1"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((target, 80))
                ip = s.getsockname()[0]
            if _is_valid_ipv4(ip):
                return ip
        except Exception:
            pass

    # 2) Linux: parse routing decision for a known remote
    try:
        out = subprocess.check_output(
            ["sh", "-lc", "ip route get 8.8.8.8 | awk '/src/ {for(i=1;i<=NF;i++) if($i==\"src\") {print $(i+1); exit}}'"],
            text=True
        ).strip()
        if _is_valid_ipv4(out):
            return out
    except Exception:
        pass

    # 3) macOS: ask common interfaces
    for iface in ("en0", "en1"):
        try:
            out = subprocess.check_output(["ipconfig", "getifaddr", iface], text=True).strip()
            if _is_valid_ipv4(out):
                return out
        except Exception:
            pass

    # 4) Generic fallback
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if _is_valid_ipv4(ip):
            return ip
    except Exception:
        pass

    # Last resort
    return "127.0.0.1"
