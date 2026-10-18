"""Regenerate Coyote mass and hover-endurance screening tables from CSV inputs.

SCREENING MODEL ONLY. Results are idealized hover estimates built from
catalogue claims, review claims and assembly placeholders. They are not
weighed-aircraft data, flight-endurance predictions or procurement approval.
Requirements (R5, R9, R10) live in coyote/DECISIONS.md.

Method (ENGINEERING_FEASIBILITY.md section 3 and the Oct 15 review's P4):

* takeoff mass = ledger mass without its example battery + profile extra mass
  + candidate battery mass
* per-motor thrust = takeoff mass / 6, power per motor linearly interpolated
  from a bench thrust/power table (no extrapolation)
* total power = (6 x motor power + non-propulsion load) x wind/maneuver margin
* minutes = battery Wh x usable fraction / total power x 60

Run from the repository root::

    python -m coyote.model.endurance
"""

from __future__ import annotations

import argparse
import csv
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

ROTORS = 6
NOMINAL_PACK_V = 44.4  # 12S nominal
PART_107_LIMIT_KG = 55 * 0.45359237  # 24.948 kg (R9)
R5_MIN_MINUTES = 20.0
R10_CURRENT_FACTOR = 2.0  # continuous rating >= 2x hover current

MODEL_DIR = Path(__file__).resolve().parent
COYOTE_DIR = MODEL_DIR.parent


@dataclass(frozen=True)
class Component:
    id: str
    component: str
    quantity: int
    mass_each_kg: float
    mass_evidence: str

    @property
    def mass_kg(self) -> float:
        return self.quantity * self.mass_each_kg


@dataclass(frozen=True)
class Battery:
    id: str
    name: str
    mass_kg: float
    energy_wh: float
    continuous_a: float | None


@dataclass(frozen=True)
class Profile:
    name: str
    non_propulsion_w: float
    usable_fraction: float
    margin: float
    extra_mass_kg: float


PROFILES = {
    # October 15 feasibility study assumptions (reproduces its section 3 table).
    "screening": Profile("screening", 120.0, 0.80, 1.00, 0.0),
    # Oct 15 review P4 assumptions adopted with R5 on 2026-10-18: 150 W load,
    # 70% usable energy (~25% landing reserve), +10% wind/maneuver margin,
    # +0.4 kg mounts and +0.25 kg harness over the original placeholders.
    "conservative": Profile("conservative", 150.0, 0.70, 1.10, 0.65),
}


@dataclass(frozen=True)
class Result:
    battery: Battery
    takeoff_kg: float
    # None when the per-motor thrust falls outside the bench table.
    total_w: float | None
    minutes: float | None

    @property
    def hover_current_a(self) -> float | None:
        return None if self.total_w is None else self.total_w / NOMINAL_PACK_V

    @property
    def under_55_lb(self) -> bool:
        return self.takeoff_kg < PART_107_LIMIT_KG

    @property
    def meets_current_rule(self) -> bool | None:
        if self.battery.continuous_a is None or self.hover_current_a is None:
            return None
        return self.battery.continuous_a >= R10_CURRENT_FACTOR * self.hover_current_a


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_bom(path: Path) -> list[Component]:
    return [
        Component(
            id=row["id"],
            component=row["component"],
            quantity=int(row["quantity"]),
            mass_each_kg=float(row["mass_each_kg"]),
            mass_evidence=row["mass_evidence"],
        )
        for row in _rows(path)
    ]


def load_batteries(path: Path) -> list[Battery]:
    return [
        Battery(
            id=row["id"],
            name=row["battery"],
            mass_kg=float(row["mass_kg"]),
            energy_wh=float(row["energy_wh"]),
            continuous_a=float(row["continuous_a"]) if row["continuous_a"] else None,
        )
        for row in _rows(path)
    ]


def load_curve(path: Path) -> list[tuple[float, float]]:
    points = sorted((float(r["thrust_kg"]), float(r["power_w"])) for r in _rows(path))
    if len(points) < 2:
        raise ValueError(f"{path} needs at least two thrust/power points")
    return points


def apply_changes(bom: Sequence[Component], changes_path: Path) -> list[Component]:
    """Apply remove/add/set_mass rows (e.g. an owner-decision scenario) to a ledger."""

    result = list(bom)
    for row in _rows(changes_path):
        action, cid = row["action"], row["id"]
        ids = [c.id for c in result]
        if action == "remove":
            if cid not in ids:
                raise ValueError(f"cannot remove unknown component {cid!r}")
            result = [c for c in result if c.id != cid]
        elif action == "add":
            if cid in ids:
                raise ValueError(f"component {cid!r} already present")
            result.append(
                Component(
                    cid,
                    row["component"],
                    int(row["quantity"]),
                    float(row["mass_each_kg"]),
                    row["mass_evidence"],
                )
            )
        elif action == "set_mass":
            if cid not in ids:
                raise ValueError(f"cannot change unknown component {cid!r}")
            result = [
                replace(
                    c,
                    mass_each_kg=float(row["mass_each_kg"]),
                    mass_evidence=row["mass_evidence"],
                )
                if c.id == cid
                else c
                for c in result
            ]
        else:
            raise ValueError(f"unknown action {action!r}")
    return result


def interpolate_power(curve: Sequence[tuple[float, float]], thrust_kg: float) -> float:
    lo_kg, hi_kg = curve[0][0], curve[-1][0]
    if not lo_kg <= thrust_kg <= hi_kg:
        raise ValueError(
            f"per-motor thrust {thrust_kg:.3f} kg outside table range "
            f"[{lo_kg:.3f}, {hi_kg:.3f}] kg; refusing to extrapolate"
        )
    for (t0, p0), (t1, p1) in zip(curve, curve[1:], strict=False):
        if t0 <= thrust_kg <= t1:
            return p0 + (thrust_kg - t0) / (t1 - t0) * (p1 - p0)
    raise AssertionError("unreachable")  # pragma: no cover


def evaluate(
    bom: Sequence[Component],
    batteries: Iterable[Battery],
    curve: Sequence[tuple[float, float]],
    profile: Profile,
) -> list[Result]:
    dry_kg = sum(c.mass_kg for c in bom if c.id != "battery") + profile.extra_mass_kg
    results = []
    for battery in batteries:
        takeoff_kg = dry_kg + battery.mass_kg
        try:
            motor_w = interpolate_power(curve, takeoff_kg / ROTORS)
        except ValueError:
            results.append(Result(battery, takeoff_kg, None, None))
            continue
        total_w = (ROTORS * motor_w + profile.non_propulsion_w) * profile.margin
        minutes = battery.energy_wh * profile.usable_fraction / total_w * 60.0
        results.append(Result(battery, takeoff_kg, total_w, minutes))
    return results


def _mark(value: bool | None) -> str:
    return "unknown" if value is None else ("yes" if value else "NO")


def format_table(results: Sequence[Result], profile: Profile) -> str:
    lines = [
        "| Battery | Takeoff mass | Under 55 lb (R9) | Hover power | Hover current "
        "| Current rule (R10) | Minutes | R5 >= 20 min |",
        "|---|---:|---|---:|---:|---|---:|---|",
    ]
    for r in results:
        mass = f"{r.takeoff_kg:.3f} kg ({r.takeoff_kg / 0.45359237:.1f} lb)"
        if r.total_w is None or r.minutes is None or r.hover_current_a is None:
            lines.append(
                f"| {r.battery.name} | {mass} | {_mark(r.under_55_lb)} "
                "| outside bench table | - | - | - | - |"
            )
            continue
        r5 = "n/a" if profile.name != "conservative" else _mark(r.minutes >= R5_MIN_MINUTES)
        lines.append(
            f"| {r.battery.name} | {mass} "
            f"| {_mark(r.under_55_lb)} | {r.total_w / 1000:.3f} kW | {r.hover_current_a:.0f} A "
            f"| {_mark(r.meets_current_rule)} | {r.minutes:.1f} | {r5} |"
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bom", type=Path, default=COYOTE_DIR / "bom.csv")
    parser.add_argument(
        "--changes",
        type=Path,
        default=None,
        help="remove/add/set_mass scenario CSV, e.g. coyote/model/decisions_2026-10-18.csv",
    )
    parser.add_argument("--batteries", type=Path, default=MODEL_DIR / "batteries.csv")
    parser.add_argument("--curve", type=Path, default=MODEL_DIR / "x8_original_46v.csv")
    parser.add_argument("--profile", choices=sorted(PROFILES), default="screening")
    args = parser.parse_args(argv)

    bom = load_bom(args.bom)
    if args.changes is not None:
        bom = apply_changes(bom, args.changes)
    profile = PROFILES[args.profile]
    results = evaluate(bom, load_batteries(args.batteries), load_curve(args.curve), profile)

    print(f"Profile: {profile}")
    print(f"Ledger: {args.bom}" + (f" + {args.changes}" if args.changes else ""))
    print(f"Power curve: {args.curve}")
    print("SCREENING ESTIMATE ONLY - not weighed mass or flight endurance.\n")
    print(format_table(results, profile))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
