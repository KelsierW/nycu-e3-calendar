"""Local private storage and errors safe for unattended logs."""
import os
from pathlib import Path


class SetupError(RuntimeError):
    pass


def runtime_dir(root, cfg):
    if cfg.get("runtime_dir"):
        return Path(os.path.expandvars(cfg["runtime_dir"])).expanduser().resolve()
    if os.name == "nt":
        return Path(os.environ["LOCALAPPDATA"]) / "NYCU-e3-calendar"
    return root


def safe_error(exc):
    # Google errors may embed tokens, email bodies or request URLs. Never log str(exc).
    if isinstance(exc, SetupError):
        return str(exc)
    status = getattr(getattr(exc, "resp", None), "status", None)
    return f"{type(exc).__name__}" + (f" (HTTP {status})" if status else "") + "；請檢查網路、設定與 OAuth 授權。"
