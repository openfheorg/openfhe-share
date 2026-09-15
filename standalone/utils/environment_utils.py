# purpose: load environment variables from a .env.local style file
# reads simple KEY=VALUE lines and ignores blanks and comments
# does not overwrite existing environment variables
# raises FileNotFoundError if the file does not exist
from pathlib import Path
import os

def load_env_file(path: str | Path = ".env.local") -> None:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"env file not found: {p}")
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())
