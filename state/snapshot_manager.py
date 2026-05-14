"""参数快照管理器 — 读写 params_snapshot.json。"""

import json
from dataclasses import dataclass, field
from typing import Dict, Optional
from pathlib import Path


@dataclass
class PinSnapshot:
    name: str
    x: float
    y: float


@dataclass
class DeviceSnapshot:
    ref: str
    pcell_type: str
    params: Dict[str, float]
    pins: Dict[str, PinSnapshot]


@dataclass
class ParamsSnapshot:
    gds_path: str = ""
    timestamp: str = ""
    devices: Dict[str, DeviceSnapshot] = field(default_factory=dict)

    def get_pin_positions(self) -> Dict[str, Dict[str, tuple]]:
        """提取所有器件的引脚位置，供 StretchRouter 和 LVS 使用。

        Returns:
            {ref: {pin_name: (x, y)}}
        """
        result = {}
        for ref, dev in self.devices.items():
            result[ref] = {p.name: (p.x, p.y) for p in dev.pins.values()}
        return result


class SnapshotManager:
    """参数快照管理器 — 读写 params_snapshot.json。"""

    def __init__(self, state_dir: str = "state"):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def load_params_state(self, path: Optional[str] = None) -> Optional[ParamsSnapshot]:
        filepath = Path(path) if path else self.state_dir / "params_snapshot.json"
        if not filepath.exists():
            return None
        with open(filepath, "r") as f:
            data = json.load(f)
        devices = {}
        for ref, dev_data in data.get("devices", {}).items():
            pins = {}
            for pin_name, pin_data in dev_data.get("pins", {}).items():
                pins[pin_name] = PinSnapshot(
                    name=pin_data["name"],
                    x=pin_data["x"],
                    y=pin_data["y"],
                )
            devices[ref] = DeviceSnapshot(
                ref=ref,
                pcell_type=dev_data["pcell_type"],
                params=dev_data.get("params", {}),
                pins=pins,
            )
        return ParamsSnapshot(
            gds_path=data.get("gds_path", ""),
            timestamp=data.get("timestamp", ""),
            devices=devices,
        )

    def save_params_state(
        self, path: Optional[str], snapshot: ParamsSnapshot
    ):
        filepath = Path(path) if path else self.state_dir / "params_snapshot.json"
        filepath.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "gds_path": snapshot.gds_path,
            "timestamp": snapshot.timestamp,
            "devices": {},
        }
        for ref, dev in snapshot.devices.items():
            data["devices"][ref] = {
                "pcell_type": dev.pcell_type,
                "params": dev.params,
                "pins": {
                    pin_name: {"name": p.name, "x": p.x, "y": p.y}
                    for pin_name, p in dev.pins.items()
                },
            }
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
