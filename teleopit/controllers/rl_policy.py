from __future__ import annotations

import importlib
import logging
import os
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Protocol, cast

import numpy as np
from numpy.typing import NDArray

from teleopit.runtime.common import cfg_get

_logger = logging.getLogger(__name__)


class _OrtValue(Protocol):
    name: str
    shape: Sequence[object]


class _OrtSession(Protocol):
    def get_inputs(self) -> Sequence[_OrtValue]: ...

    def get_outputs(self) -> Sequence[_OrtValue]: ...

    def run(self, output_names: Sequence[str], feed: dict[str, NDArray[np.float32]]) -> Sequence[object]: ...


class RLPolicyController:
    _multi_input: bool

    def __init__(self, cfg: object) -> None:
        self._session: _OrtSession
        self._input_name: str
        self._output_name: str
        self._expected_obs_dim: int | None
        self._history_buf: deque[NDArray[np.float32]]
        self._history_length: int
        self._history_obs_dim: int
        self.action_scale: NDArray[np.float32]
        self.default_dof_pos: NDArray[np.float32]
        self.clip_range: tuple[float, float]

        policy_path = Path(str(cfg_get(cfg, "policy_path", ""))).expanduser()
        if not policy_path.is_file():
            raise FileNotFoundError(f"ONNX policy file not found: {policy_path}")

        try:
            ort = importlib.import_module("onnxruntime")
        except ModuleNotFoundError as exc:
            raise ImportError("onnxruntime is required for RLPolicyController") from exc
        session_ctor = cast(object, getattr(ort, "InferenceSession"))
        providers_fn = cast(object, getattr(ort, "get_available_providers"))
        if not callable(session_ctor) or not callable(providers_fn):
            raise ImportError("onnxruntime missing required API")

        providers = self._select_providers(
            cast(Callable[[], Sequence[str]], providers_fn),
            str(cfg_get(cfg, "device", "auto")),
        )
        applied_cpus = self._apply_cpu_affinity(cfg)
        session_options = self._create_session_options(
            ort,
            cfg,
            cpu_budget=None if applied_cpus is None else len(applied_cpus),
        )
        self._session = cast(
            _OrtSession,
            session_ctor(str(policy_path), sess_options=session_options, providers=providers),
        )
        onnx_inputs = self._session.get_inputs()
        self._input_name = onnx_inputs[0].name
        self._output_name = self._session.get_outputs()[0].name
        self._expected_obs_dim = self._extract_feature_dim(onnx_inputs[0].shape)
        self._history_length = 0
        self._history_obs_dim = 0
        self._history_buf = deque()

        if len(onnx_inputs) == 1:
            self._multi_input = False
        elif len(onnx_inputs) == 2 and onnx_inputs[1].name == "obs_history":
            self._multi_input = True
            self._history_length = int(onnx_inputs[1].shape[1])
            self._history_obs_dim = int(onnx_inputs[1].shape[2])
            self._history_buf = deque(maxlen=self._history_length)
        else:
            names = [inp.name for inp in onnx_inputs]
            raise ValueError(
                "Unsupported ONNX policy input signature. Expected either a single observation input "
                "or dual inputs ('obs' and 'obs_history'). "
                f"Got inputs: {names}."
            )

        raw_scale = cfg_get(cfg, "action_scale", None)
        self.action_scale = self._normalize_action_scale(
            raw_scale if raw_scale is not None else 1.0,
            cfg_get(cfg, "robot_joint_names", cfg_get(cfg, "joint_names", None)),
        )
        self.default_dof_pos = np.asarray(
            cfg_get(cfg, "default_dof_pos", cfg_get(cfg, "default_angles", [])),
            dtype=np.float32,
        )
        self.clip_range = self._normalize_clip_range(cfg_get(cfg, "clip_range", (-10.0, 10.0)))
        self._last_obs_input: NDArray[np.float32] | None = None
        self._last_obs_history_input: NDArray[np.float32] | None = None

    def compute_action(self, observation: NDArray[np.float32]) -> NDArray[np.float32]:
        obs = np.asarray(observation, dtype=np.float32)
        if obs.ndim == 1:
            if self._expected_obs_dim is not None and obs.shape[0] != self._expected_obs_dim:
                raise ValueError(
                    f"Observation dimension mismatch: expected {self._expected_obs_dim}, got {obs.shape[0]}"
                )
            obs = obs[np.newaxis, :]
        elif obs.ndim == 2 and obs.shape[0] == 1:
            if self._expected_obs_dim is not None and obs.shape[1] != self._expected_obs_dim:
                raise ValueError(
                    f"Observation dimension mismatch: expected {self._expected_obs_dim}, got {obs.shape[1]}"
                )
        else:
            raise ValueError(f"Observation must be shape (obs_dim,) or (1, obs_dim), got {obs.shape}")

        obs_flat = obs.reshape(-1)
        self._last_obs_input = obs_flat.copy()

        if self._multi_input:
            if len(self._history_buf) == 0:
                for _ in range(self._history_length):
                    self._history_buf.append(obs_flat.copy())
            else:
                self._history_buf.append(obs_flat.copy())
            obs_history = np.stack(list(self._history_buf), axis=0)[np.newaxis]
            if obs_history.shape[2] != self._history_obs_dim:
                raise ValueError(
                    f"History observation dimension mismatch: policy expects {self._history_obs_dim}, "
                    f"builder produced {obs_history.shape[2]}"
                )
            self._last_obs_history_input = np.asarray(obs_history[0], dtype=np.float32)
            feed = {
                self._input_name: obs,
                "obs_history": obs_history.astype(np.float32),
            }
        else:
            self._last_obs_history_input = None
            feed = {self._input_name: obs}

        raw_action = np.asarray(
            self._session.run([self._output_name], feed)[0],
            dtype=np.float32,
        ).reshape(-1)
        if not np.all(np.isfinite(raw_action)):
            _logger.warning("NaN/inf in ONNX output, damping to zero action")
            raw_action = np.zeros_like(raw_action)
        return raw_action

    def get_target_dof_pos(self, raw_action: NDArray[np.float32]) -> NDArray[np.float32]:
        scaled_action = self._clip_and_scale(np.asarray(raw_action, dtype=np.float32).reshape(-1))
        if self.default_dof_pos.size == 0:
            return scaled_action
        if scaled_action.shape[0] != self.default_dof_pos.shape[0]:
            raise ValueError(
                f"Action/default_dof_pos size mismatch: {scaled_action.shape[0]} vs {self.default_dof_pos.shape[0]}"
            )
        return scaled_action + self.default_dof_pos

    def reset(self) -> None:
        self._history_buf.clear()
        self._last_obs_input = None
        self._last_obs_history_input = None

    def get_debug_inputs(self) -> dict[str, NDArray[np.float32] | None]:
        return {
            "obs": None if self._last_obs_input is None else self._last_obs_input.copy(),
            "obs_history": (
                None
                if self._last_obs_history_input is None
                else self._last_obs_history_input.copy()
            ),
        }

    def _clip_and_scale(self, raw_action: NDArray[np.float32]) -> NDArray[np.float32]:
        clipped = np.clip(raw_action, self.clip_range[0], self.clip_range[1])
        scaled = np.asarray(clipped * self.action_scale, dtype=np.float32)
        if not np.all(np.isfinite(scaled)):
            _logger.warning("NaN/inf after clip_and_scale, damping to zero")
            return np.zeros_like(scaled)
        return scaled

    @staticmethod
    def _normalize_clip_range(raw: object) -> tuple[float, float]:
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
            if len(raw) != 2:
                raise ValueError(f"clip_range sequence must contain exactly two values, got {raw}")
            low_raw = raw[0]
            high_raw = raw[1]
            if not isinstance(low_raw, (int, float)) or not isinstance(high_raw, (int, float)):
                raise ValueError(f"clip_range values must be numeric, got {raw}")
            low, high = float(low_raw), float(high_raw)
        else:
            if not isinstance(raw, (int, float)):
                raise ValueError(f"clip_range must be numeric or 2-length sequence, got {raw}")
            limit = float(raw)
            low, high = -abs(limit), abs(limit)
        if low > high:
            raise ValueError(f"clip_range lower bound must be <= upper bound, got ({low}, {high})")
        return low, high

    @staticmethod
    def _normalize_action_scale(
        raw: object,
        robot_joint_names_raw: object | None = None,
    ) -> NDArray[np.float32]:
        if isinstance(raw, Mapping):
            if robot_joint_names_raw is None:
                raise ValueError(
                    "robot_joint_names is required when controller.action_scale is provided as a joint-name mapping"
                )
            if not isinstance(robot_joint_names_raw, Sequence) or isinstance(robot_joint_names_raw, (str, bytes)):
                raise ValueError("robot_joint_names must be a sequence of joint names")
            robot_joint_names = [str(name) for name in robot_joint_names_raw]
            scale_by_name = {str(name): float(value) for name, value in raw.items()}
            missing = [name for name in robot_joint_names if name not in scale_by_name]
            if missing:
                raise ValueError(
                    "controller.action_scale mapping is missing robot joints: " + ", ".join(missing)
                )
            unknown = [name for name in scale_by_name if name not in set(robot_joint_names)]
            if unknown:
                raise ValueError(
                    "controller.action_scale mapping contains unknown joints: " + ", ".join(sorted(unknown))
                )
            return np.asarray([scale_by_name[name] for name in robot_joint_names], dtype=np.float32)
        return np.asarray(raw, dtype=np.float32)

    @staticmethod
    def _extract_feature_dim(shape: Sequence[object]) -> int | None:
        if len(shape) < 2:
            return None
        feature_dim = shape[-1]
        if isinstance(feature_dim, int):
            return feature_dim
        if isinstance(feature_dim, float):
            return int(feature_dim)
        if isinstance(feature_dim, str):
            try:
                return int(feature_dim)
            except ValueError:
                return None
        return None

    @staticmethod
    def _select_providers(get_available_providers: object, device: str) -> list[str]:
        if not callable(get_available_providers):
            return ["CPUExecutionProvider"]
        available = set(cast(Sequence[str], get_available_providers()))
        requested = device.lower()

        prefer_cuda = requested.startswith("cuda") or requested == "auto"
        providers: list[str] = []
        if prefer_cuda and "CUDAExecutionProvider" in available:
            providers.append("CUDAExecutionProvider")
        providers.append("CPUExecutionProvider")
        return providers

    @staticmethod
    def _create_session_options(
        ort: object,
        cfg: object,
        *,
        cpu_budget: int | None = None,
    ) -> object | None:
        intra_threads = RLPolicyController._parse_optional_positive_int(
            cfg_get(cfg, "intra_op_num_threads", None),
            field_name="controller.intra_op_num_threads",
        )
        inter_threads = RLPolicyController._parse_optional_positive_int(
            cfg_get(cfg, "inter_op_num_threads", None),
            field_name="controller.inter_op_num_threads",
        )
        allow_spinning = cfg_get(cfg, "intra_op_allow_spinning", None)
        if intra_threads is None and inter_threads is None and allow_spinning is None:
            return None
        if (
            intra_threads is not None
            and cpu_budget is not None
            and cpu_budget > 0
            and intra_threads > cpu_budget
        ):
            _logger.warning(
                "controller.intra_op_num_threads=%s exceeds effective CPU affinity budget %s; using %s",
                intra_threads,
                cpu_budget,
                cpu_budget,
            )
            intra_threads = cpu_budget

        session_options_ctor = getattr(ort, "SessionOptions", None)
        if not callable(session_options_ctor):
            raise ImportError("onnxruntime missing SessionOptions API")
        session_options = session_options_ctor()
        if intra_threads is not None:
            session_options.intra_op_num_threads = intra_threads
        if inter_threads is not None:
            session_options.inter_op_num_threads = inter_threads
        if allow_spinning is not None:
            if not isinstance(allow_spinning, bool):
                raise ValueError(
                    "controller.intra_op_allow_spinning must be true, false, or null"
                )
            add_entry = getattr(session_options, "add_session_config_entry", None)
            if not callable(add_entry):
                raise ImportError("onnxruntime SessionOptions missing add_session_config_entry API")
            add_entry("session.intra_op.allow_spinning", "1" if allow_spinning else "0")
        return session_options

    @staticmethod
    def _apply_cpu_affinity(cfg: object) -> tuple[int, ...] | None:
        cpus = RLPolicyController._normalize_cpu_affinity(
            cfg_get(cfg, "cpu_affinity", None),
            field_name="controller.cpu_affinity",
        )
        if cpus is None:
            return None
        if not hasattr(os, "sched_getaffinity") or not hasattr(os, "sched_setaffinity"):
            _logger.warning("controller.cpu_affinity is configured but OS CPU affinity APIs are unavailable")
            return None

        allowed = sorted(os.sched_getaffinity(0))
        target = [cpu for cpu in cpus if cpu in allowed]
        if len(target) != len(cpus):
            _logger.warning(
                "controller.cpu_affinity requested CPUs %s but current affinity mask allows %s; using %s",
                list(cpus),
                allowed,
                target,
            )
        if not target:
            _logger.warning(
                "controller.cpu_affinity resolved to no available CPUs; leaving affinity unchanged "
                "and using current CPU budget %s",
                allowed,
            )
            return tuple(allowed) if allowed else None
        if set(target) != set(allowed):
            os.sched_setaffinity(0, set(target))
            _logger.info("Bound CPU affinity to CPUs %s", target)
        else:
            _logger.debug("CPU affinity already limited to CPUs %s", target)
        return tuple(target)

    @staticmethod
    def _normalize_cpu_affinity(raw: object, *, field_name: str) -> tuple[int, ...] | None:
        if raw is None or raw is False:
            return None
        if isinstance(raw, str) and raw.strip().lower() in ("", "null", "none"):
            return None

        values: list[object]
        if isinstance(raw, str):
            values = []
            for token in raw.split(","):
                token = token.strip()
                if not token:
                    continue
                if "-" in token:
                    parts = token.split("-")
                    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
                        raise ValueError(f"{field_name} contains invalid CPU range {token!r}")
                    try:
                        start = int(parts[0])
                        end = int(parts[1])
                    except ValueError as exc:
                        raise ValueError(f"{field_name} contains invalid CPU range {token!r}") from exc
                    if end < start:
                        raise ValueError(f"{field_name} CPU range must be ascending, got {token!r}")
                    values.extend(range(start, end + 1))
                else:
                    try:
                        values.append(int(token))
                    except ValueError as exc:
                        raise ValueError(f"{field_name} contains invalid CPU id {token!r}") from exc
        elif isinstance(raw, int) and not isinstance(raw, bool):
            values = [raw]
        elif isinstance(raw, Sequence) and not isinstance(raw, (bytes, bytearray)):
            values = list(raw)
        else:
            raise ValueError(f"{field_name} must be null, an int, a list of ints, or a comma-separated string")

        cpus: list[int] = []
        seen: set[int] = set()
        for value in values:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{field_name} entries must be non-negative integers, got {value!r}")
            cpu = int(value)
            if cpu < 0 or cpu != value:
                raise ValueError(f"{field_name} entries must be non-negative integers, got {value!r}")
            if cpu not in seen:
                seen.add(cpu)
                cpus.append(cpu)
        if not cpus:
            return None
        return tuple(cpus)

    @staticmethod
    def _parse_optional_positive_int(raw: object, *, field_name: str) -> int | None:
        if raw is None:
            return None
        if isinstance(raw, str) and raw.strip().lower() in ("", "null", "none"):
            return None
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError(f"{field_name} must be a positive integer or null, got {raw!r}")
        parsed = int(raw)
        if parsed <= 0 or parsed != raw:
            raise ValueError(f"{field_name} must be a positive integer or null, got {raw!r}")
        return parsed
