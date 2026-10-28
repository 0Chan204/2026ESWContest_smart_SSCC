"""Fixed team connection settings shared with the C agent."""
import os
from pathlib import Path
import re

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9._~-]{1,255}\Z")


def validate_token(token):
    if not isinstance(token, str) or not TOKEN_PATTERN.fullmatch(token):
        raise ValueError("CSI_TOKEN must contain 1–255 letters, digits or . _ ~ -")
    return token


def load_token(env_file=None, environ=None):
    """Exported environment overrides .env; never generate a token on startup."""
    environ = os.environ if environ is None else environ
    if "CSI_TOKEN" in environ:
        return validate_token(environ["CSI_TOKEN"])
    path = Path(env_file or environ.get("CSI_ENV_FILE") or PROJECT_ROOT / ".env")
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[7:].lstrip()
            key, separator, value = line.partition("=")
            if separator and key.strip() == "CSI_TOKEN":
                value = value.strip()
                if value.startswith(("'", '"')):
                    quote = value[0]
                    closing = value.find(quote, 1)
                    if closing < 0 or (value[closing + 1:].strip() and not value[closing + 1:].lstrip().startswith("#")):
                        raise ValueError(f"Invalid CSI_TOKEN quoting in {path}")
                    value = value[1:closing]
                else:
                    value = value.split("#", 1)[0].rstrip()
                return validate_token(value)
    except FileNotFoundError:
        pass
    raise ValueError(f"Set CSI_TOKEN in {path} (copy .env.example once), or export CSI_TOKEN")
