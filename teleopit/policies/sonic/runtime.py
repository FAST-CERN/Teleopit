"""onnxruntime wrapper for the SONIC low_latency encoder/decoder (sonic-wbc t02).

Mirrors the C++ deploy stack's load-time dimension validation: the ONNX IO
contract (``obs_dict`` in, ``encoded_tokens``/``action`` out) is checked when
the sessions load, so a mismatched checkpoint/config pairing fails loudly
instead of producing garbage actions (model_card.md:151-152 warns every ONNX
must ship with its own observation_config.yaml).
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

import numpy as np
import onnxruntime as ort

_ENCODER_INPUT = "obs_dict"
_ENCODER_OUTPUT = "encoded_tokens"
_DECODER_INPUT = "obs_dict"
_DECODER_OUTPUT = "action"

SONIC_CKPT_DIR = Path(__file__).resolve().parents[3] / "assets" / "policies" / "sonic" / "low_latency"

_MISSING_HINT = (
    "SONIC low_latency checkpoints not found under {dir}. Download from "
    "nvidia/GEAR-SONIC via hf-mirror:\n"
    "  export HF_ENDPOINT=https://hf-mirror.com\n"
    "  for f in model_encoder.onnx model_decoder.onnx observation_config.yaml "
    "config.yaml model_config.yaml; do\n"
    "    curl -L -o assets/policies/sonic/low_latency/$f \\\n"
    "      https://hf-mirror.com/nvidia/GEAR-SONIC/resolve/main/low_latency/$f\n"
    "  done"
)


class SonicOnnxPolicy:
    """Encoder/decoder pair with load-time IO validation and f32 casting."""

    def __init__(self, ckpt_dir: Path | str | None = None, providers: Sequence[str] | None = None) -> None:
        self._ckpt_dir = Path(ckpt_dir) if ckpt_dir is not None else SONIC_CKPT_DIR
        encoder_path = self._ckpt_dir / "model_encoder.onnx"
        decoder_path = self._ckpt_dir / "model_decoder.onnx"
        for path in (encoder_path, decoder_path):
            if not path.exists():
                raise FileNotFoundError(_MISSING_HINT.format(dir=self._ckpt_dir))

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1  # latency-stable for 50 Hz stepping
        providers = list(providers) if providers else ["CPUExecutionProvider"]
        self._encoder = ort.InferenceSession(
            str(encoder_path), sess_options=opts, providers=providers
        )
        self._decoder = ort.InferenceSession(
            str(decoder_path), sess_options=opts, providers=providers
        )

        enc_in = self._encoder.get_inputs()
        dec_in = self._decoder.get_inputs()
        self.encoder_input_dim = self._io_dim(enc_in, _ENCODER_INPUT, encoder_path)
        self.decoder_input_dim = self._io_dim(dec_in, _DECODER_INPUT, decoder_path)
        self.token_dim = self._io_dim(self._encoder.get_outputs(), _ENCODER_OUTPUT, encoder_path)
        self.action_dim = self._io_dim(self._decoder.get_outputs(), _DECODER_OUTPUT, decoder_path)

    @staticmethod
    def _io_dim(tensors: Sequence[ort.NodeArg], name: str, path: Path) -> int:
        match = next((t for t in tensors if t.name == name), None)
        if match is None:
            names = [t.name for t in tensors]
            raise ValueError(f"{path.name}: expected IO tensor {name!r}, found {names}")
        shape = match.shape
        dim = shape[-1] if isinstance(shape, list) and len(shape) >= 2 else None
        if not isinstance(dim, int) or dim <= 0:
            raise ValueError(f"{path.name}: cannot read static dim from {name} shape {shape}")
        return int(dim)

    def encode(self, encoder_obs: np.ndarray) -> np.ndarray:
        x = np.asarray(encoder_obs, dtype=np.float32).reshape(-1)
        if x.shape[0] != self.encoder_input_dim:
            raise ValueError(
                f"encoder obs has {x.shape[0]} entries, expected {self.encoder_input_dim}"
            )
        out = self._encoder.run([_ENCODER_OUTPUT], {_ENCODER_INPUT: x[None, :]})[0]
        return np.asarray(out, dtype=np.float32).reshape(-1)

    def decode(self, decoder_obs: np.ndarray) -> np.ndarray:
        x = np.asarray(decoder_obs, dtype=np.float32).reshape(-1)
        if x.shape[0] != self.decoder_input_dim:
            raise ValueError(
                f"decoder obs has {x.shape[0]} entries, expected {self.decoder_input_dim}"
            )
        out = self._decoder.run([_DECODER_OUTPUT], {_DECODER_INPUT: x[None, :]})[0]
        return np.asarray(out, dtype=np.float32).reshape(-1)
