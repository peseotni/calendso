"""Tiny stand-in ONNX models with the same inputs/outputs as the real voices.

They let the Kokoro and Piper integrations run end-to-end in tests without
downloading hundreds of megabytes of model weights.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np


def _tone(rate: int, samples: int, freq: float) -> np.ndarray:
    return (0.3 * np.sin(2 * np.pi * freq * np.arange(samples) / rate)).astype(np.float32)


def _save(graph, path: Path) -> None:
    import onnx
    from onnx import helper

    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 9
    onnx.checker.check_model(model)
    path.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, str(path))


def _repeat_nodes(token_input: str, base: np.ndarray, output: str):
    from onnx import helper, numpy_helper

    return [
        helper.make_node("Shape", [token_input], ["shape"]),
        helper.make_node("Constant", [], ["one"], value=numpy_helper.from_array(np.array(1, dtype=np.int64))),
        helper.make_node("Gather", ["shape", "one"], ["count"]),
        helper.make_node("Constant", [], ["axes"], value=numpy_helper.from_array(np.array([0], dtype=np.int64))),
        helper.make_node("Unsqueeze", ["count", "axes"], ["repeats"]),
        helper.make_node("Constant", [], ["base"], value=numpy_helper.from_array(base)),
        helper.make_node("Tile", ["base", "repeats"], [output]),
    ]


def make_kokoro(folder: Path, voices: tuple[str, ...] = ("af_heart", "af_bella", "bf_emma")) -> None:
    """kokoro-v1.0.onnx (tokens, style, speed -> audio) + voices-v1.0.bin (npz)."""
    from onnx import TensorProto, helper

    graph = helper.make_graph(
        _repeat_nodes("tokens", _tone(24000, 480, 220.0), "audio"),
        "fake-kokoro",
        [
            helper.make_tensor_value_info("tokens", TensorProto.INT64, [1, None]),
            helper.make_tensor_value_info("style", TensorProto.FLOAT, [1, 256]),
            helper.make_tensor_value_info("speed", TensorProto.FLOAT, [1]),
        ],
        [helper.make_tensor_value_info("audio", TensorProto.FLOAT, [None])],
    )
    _save(graph, folder / "kokoro-v1.0.onnx")
    rng = np.random.default_rng(0)
    arrays = {name: rng.standard_normal((510, 1, 256)).astype(np.float32) for name in voices}
    buffer = io.BytesIO()
    np.savez(buffer, **arrays)
    (folder / "voices-v1.0.bin").write_bytes(buffer.getvalue())


def make_piper(folder: Path, key: str = "en_US-test-medium", speakers: dict[str, int] | None = None) -> None:
    """<key>.onnx (input, input_lengths, scales[, sid] -> output) + <key>.onnx.json."""
    from onnx import TensorProto, helper
    from piper.phoneme_ids import DEFAULT_PHONEME_ID_MAP

    nodes = _repeat_nodes("input", _tone(22050, 256, 330.0), "flat")
    from onnx import numpy_helper

    nodes += [
        helper.make_node("Constant", [], ["out_shape"], value=numpy_helper.from_array(np.array([1, 1, -1], dtype=np.int64))),
        helper.make_node("Reshape", ["flat", "out_shape"], ["output"]),
    ]
    inputs = [
        helper.make_tensor_value_info("input", TensorProto.INT64, [1, None]),
        helper.make_tensor_value_info("input_lengths", TensorProto.INT64, [1]),
        helper.make_tensor_value_info("scales", TensorProto.FLOAT, [3]),
    ]
    if speakers:
        inputs.append(helper.make_tensor_value_info("sid", TensorProto.INT64, [1]))
    graph = helper.make_graph(nodes, "fake-piper", inputs, [helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 1, None])])
    _save(graph, folder / f"{key}.onnx")
    config = {
        "audio": {"sample_rate": 22050, "quality": "medium"},
        "espeak": {"voice": "en-us"},
        "language": {"code": "en_US", "family": "en", "region": "US", "name_native": "English",
                     "name_english": "English", "country_english": "United States"},
        "inference": {"noise_scale": 0.667, "length_scale": 1, "noise_w": 0.8},
        "phoneme_type": "espeak",
        "phoneme_id_map": DEFAULT_PHONEME_ID_MAP,
        "num_symbols": 256,
        "num_speakers": len(speakers) if speakers else 1,
        "speaker_id_map": speakers or {},
        "piper_version": "1.0.0",
    }
    (folder / f"{key}.onnx.json").write_text(json.dumps(config), encoding="utf-8")
