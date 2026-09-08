"""Configuration: read Hy3 credentials from env / local .env only.

Safety: the API key is never written anywhere except the user's local
``.env`` (project root), is never transmitted by the app to anyone but the
configured Hy3 endpoint, and is never logged.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DEFAULT_BASE_URL = "https://tokenhub.tencentmaas.com/v1"  # Hy3 cloud (TokenHub)
DEFAULT_MODEL = "hy3"
DEFAULT_REASONING = "low"


@dataclass
class Config:
    hy3_api_key: str = ""
    hy3_base_url: str = DEFAULT_BASE_URL
    hy3_model: str = DEFAULT_MODEL
    hy3_reasoning_effort: str = DEFAULT_REASONING
    # Evaluation runtime knobs
    data_dir: Path = field(default_factory=lambda: Path.cwd() / "data")
    outputs_dir: Path = field(default_factory=lambda: Path.cwd() / "data" / "outputs")
    # HF 数据集缓存必须落在项目内（data/cache/hf），中间数据不写系统盘
    hf_cache_dir: Path = field(default_factory=lambda: Path.cwd() / "data" / "cache" / "hf")
    random_seed: int = 42
    # Per-call budget (see DESIGN.md): eval = solve 1 + verify 双视角 2 + arbitrate 1（总仲裁）
    max_retries: int = 3
    timeout: float = 180.0
    temperature: float = 0.9
    # 指标口径开关：minor 瑕疵是否计入"过程错误"（false=主口径 fatal-only；
    # true=副口径 minor 也算错）。env REX_MINOR_AS_ERROR=1/true 一键切换，
    # 供报告/面板统一读取，无需改代码。
    minor_as_error: bool = False

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)
        self.outputs_dir = Path(self.outputs_dir)
        self.hf_cache_dir = Path(self.hf_cache_dir)

    @classmethod
    def from_env(cls, project_root: str | os.PathLike | None = None) -> "Config":
        root = Path(project_root) if project_root else Path.cwd()
        # Defensive env parsing: a malformed env value (e.g. REX_SEED=abc) must
        # not crash the whole app at import/config time — fall back to default.
        def _int(name: str, default: int) -> int:
            try:
                return int(os.getenv(name, str(default)))
            except (TypeError, ValueError):
                return default

        def _float(name: str, default: float) -> float:
            try:
                return float(os.getenv(name, str(default)))
            except (TypeError, ValueError):
                return default

        def _bool(name: str, default: bool) -> bool:
            v = os.getenv(name)
            if v is None:
                return default
            return v.strip().lower() in ("1", "true", "yes", "on")

        return cls(
            hy3_api_key=os.getenv("HY3_API_KEY", ""),
            hy3_base_url=os.getenv("HY3_BASE_URL", DEFAULT_BASE_URL),
            hy3_model=os.getenv("HY3_MODEL", DEFAULT_MODEL),
            hy3_reasoning_effort=os.getenv("HY3_REASONING_EFFORT", DEFAULT_REASONING),
            data_dir=root / "data",
            outputs_dir=root / "data" / "outputs",
            hf_cache_dir=root / "data" / "cache" / "hf",
            random_seed=_int("REX_SEED", 42),
            max_retries=_int("REX_MAX_RETRIES", 3),
            timeout=_float("REX_TIMEOUT", 180.0),
            temperature=_float("REX_TEMPERATURE", 0.9),
            minor_as_error=_bool("REX_MINOR_AS_ERROR", False),
        )

    @property
    def has_credentials(self) -> bool:
        return bool(self.hy3_api_key and self.hy3_base_url)
