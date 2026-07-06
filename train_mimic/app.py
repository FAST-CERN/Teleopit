"""Shared application helpers for train/eval/export entry points."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from train_mimic.tasks.tracking.config.constants import (
    DEFAULT_TRAIN_MOTION_FILE,
    GENERAL_TRACKING_TASK,
    SUPPORTED_TASKS,
)
from train_mimic.data.dataset_lib import find_precomputed_motion_shards, validate_precomputed_motion_dataset

DEFAULT_TASK = GENERAL_TRACKING_TASK
HISTORY_ENCODER_TEMPORAL_CNN = "temporal_cnn"
HISTORY_ENCODER_NONE = "none"
HISTORY_ENCODER_CHOICES = (HISTORY_ENCODER_TEMPORAL_CNN, HISTORY_ENCODER_NONE)
_MLP_MODEL_CLASS = "rsl_rl.models.mlp_model:MLPModel"


def validate_motion_file(motion_file: str) -> None:
    try:
        find_precomputed_motion_shards(Path(motion_file))
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"Motion dataset not found: {motion_file}. Provide --motion_file pointing "
            "to a precomputed training dataset root produced by "
            "train_mimic/scripts/data/precompute_dataset.py. Example: "
            f"{DEFAULT_TRAIN_MOTION_FILE}"
        ) from exc
    validate_precomputed_motion_dataset(Path(motion_file))


def validate_checkpoint_path(checkpoint_path: str) -> None:
    if Path(checkpoint_path).is_file():
        return
    raise FileNotFoundError(f"Checkpoint not found: {checkpoint_path}")


def import_training_stack() -> tuple[Any, ...]:
    import torch

    import mjlab.tasks  # noqa: F401 -- populates mjlab built-in tasks
    import train_mimic.tasks  # noqa: F401 -- registers our custom tasks
    from mjlab.envs import ManagerBasedRlEnv
    from mjlab.rl import MjlabOnPolicyRunner, RslRlVecEnvWrapper
    from mjlab.tasks.registry import load_env_cfg, load_rl_cfg, load_runner_cls
    from mjlab.utils.torch import configure_torch_backends

    return (
        torch,
        ManagerBasedRlEnv,
        RslRlVecEnvWrapper,
        MjlabOnPolicyRunner,
        load_env_cfg,
        load_rl_cfg,
        load_runner_cls,
        configure_torch_backends,
    )


def load_task_components(
    task_name: str = DEFAULT_TASK,
    *,
    play: bool = False,
    load_env_cfg: Any | None = None,
    load_rl_cfg: Any | None = None,
    load_runner_cls: Any | None = None,
) -> tuple[str, Any, Any, Any]:
    if load_env_cfg is None or load_rl_cfg is None or load_runner_cls is None:
        (
            _torch,
            _ManagerBasedRlEnv,
            _RslRlVecEnvWrapper,
            _MjlabOnPolicyRunner,
            load_env_cfg,
            load_rl_cfg,
            load_runner_cls,
            _configure_torch_backends,
        ) = import_training_stack()
    if task_name not in SUPPORTED_TASKS:
        raise ValueError(
            f"Unsupported task '{task_name}'. Supported tasks: {', '.join(SUPPORTED_TASKS)}."
        )
    env_cfg = load_env_cfg(task_name, play=play)
    agent_cfg = load_rl_cfg(task_name)
    runner_cls = load_runner_cls(task_name)
    return task_name, env_cfg, agent_cfg, runner_cls


def build_runner_cfg_dict(agent_cfg: Any, *, force_tensorboard: bool = False) -> dict[str, Any]:
    agent_dict = asdict(agent_cfg)
    if force_tensorboard:
        agent_dict["logger"] = "tensorboard"
    return agent_dict


def apply_history_encoder_config(
    env_cfg: Any,
    agent_cfg: Any,
    history_encoder: str,
) -> None:
    """Apply the training/eval observation-model variant for history ablations."""
    if history_encoder not in HISTORY_ENCODER_CHOICES:
        raise ValueError(
            f"Unsupported history_encoder={history_encoder!r}. "
            f"Supported values are: {', '.join(HISTORY_ENCODER_CHOICES)}."
        )

    agent_cfg.history_encoder = history_encoder
    if history_encoder == HISTORY_ENCODER_TEMPORAL_CNN:
        return

    observations = getattr(env_cfg, "observations", None)
    if observations is not None:
        observations.pop("actor_history", None)
        observations.pop("critic_history", None)

    agent_cfg.obs_groups = {
        "actor": ("actor",),
        "critic": ("critic",),
    }
    agent_cfg.actor.class_name = _MLP_MODEL_CLASS
    agent_cfg.actor.cnn_cfg = None
    agent_cfg.critic.class_name = _MLP_MODEL_CLASS
    agent_cfg.critic.cnn_cfg = None


def resolve_device(requested_device: str | None, torch_module: Any) -> str:
    if requested_device is not None:
        return requested_device
    return "cuda:0" if torch_module.cuda.is_available() else "cpu"
