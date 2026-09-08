import argparse
import json
import subprocess
import tempfile
import struct
from pathlib import Path
import torch
from client import Engine, atomic_json
from train import Net, batch, features


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", type=Path, required=True)
    ap.add_argument("--data", type=Path, required=True)
    args = ap.parse_args()
    integer = args.model_dir / (
        "model-int512.nnue"
        if (args.model_dir / "model-int512.nnue").exists()
        else "model-int.nnue"
    )
    saved = torch.load(
        args.model_dir / "checkpoint.pt", map_location="cpu", weights_only=False
    )
    net = Net(saved["config"].get("architecture", [6954, 256])[1])
    relative = saved["config"].get("feature_mode") == "relative"
    residual = saved["config"].get("residual", False)
    net.load_state_dict(saved.get("best_model", saved["model"]))
    net.eval()
    torch.set_num_threads(2)
    states = []
    for file in sorted(args.data.glob("pair-*.json"))[:6]:
        for game in json.loads(file.read_text()).get("games", []):
            states.extend(s["position"] for s in game["samples"][::7])
    max_float = max_integer = max_incremental = 0
    with (
        Engine(args=["--model", str(args.model_dir / "model-float.nnue")]) as f,
        Engine(args=["--model", str(integer)]) as q,
        Engine() as baseline,
    ):
        for p in states:
            ix, ofs, _ = batch([(features(p, relative), 0)], "cpu")
            with torch.no_grad():
                truth = float(net(ix, ofs).item() * 600)
            f.call("position", position=p)
            q.call("position", position=p)
            assert f.call("features") == features(p, relative)
            rf = f.call("network")
            rq = q.call("network")
            max_float = max(max_float, abs(rf["full"] - truth))
            max_integer = max(max_integer, abs(rq["full"] - truth))
            max_incremental = max(max_incremental, abs(rf["incremental"] - rf["full"]))
            assert rq["incremental"] == rq["full"]
            if residual:
                baseline.call("position", position=p)
                base = baseline.call("status")["eval"]
                expected = max(-20000, min(20000, base + truth))
                assert abs(f.call("status")["eval"] - expected) <= 0.501
                expected = max(-20000, min(20000, base + rq["full"]))
                assert abs(q.call("status")["eval"] - expected) <= 0.501
    result = dict(
        positions=len(states),
        max_float_error=max_float,
        max_quantized_error=max_integer,
        max_incremental_error=max_incremental,
    )
    atomic_json(args.model_dir / "parity-result.json", result)
    print(json.dumps(result, indent=2))
    assert states and max_float < 0.05 and max_incremental < 0.05 and max_integer < 30
    with tempfile.TemporaryDirectory() as tmp:
        broken = Path(tmp) / "broken.nnue"
        broken.write_bytes(integer.read_bytes() + b"corrupt")
        process = subprocess.run(
            [
                str(Path(__file__).resolve().parents[1] / "build/kokoriko"),
                "--model",
                str(broken),
            ],
            capture_output=True,
            text=True,
        )
        assert process.returncode == 2 and "checksum" in process.stderr
        payload = bytearray(integer.read_bytes())
        inputs, hidden = struct.unpack_from("<II", payload, 8)
        struct.pack_into("<i", payload, 32 + inputs * hidden * 2, 2147483647)
        checksum = 1469598103934665603
        for value in payload[32:]:
            checksum = ((checksum ^ value) * 1099511628211) & ((1 << 64) - 1)
        struct.pack_into("<Q", payload, 24, checksum)
        broken.write_bytes(payload)
        process = subprocess.run(
            [
                str(Path(__file__).resolve().parents[1] / "build/kokoriko"),
                "--model",
                str(broken),
            ],
            capture_output=True,
            text=True,
        )
        assert process.returncode == 2 and "invalid model value" in process.stderr


if __name__ == "__main__":
    main()
