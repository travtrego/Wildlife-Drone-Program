from pathlib import Path

import pytest

from coyote.model.endurance import (
    PROFILES,
    Battery,
    Component,
    apply_changes,
    evaluate,
    interpolate_power,
    load_batteries,
    load_bom,
    load_curve,
    main,
)

ROOT = Path(__file__).resolve().parents[1]
BOM = ROOT / "coyote" / "bom.csv"
MODEL = ROOT / "coyote" / "model"
DECISIONS = MODEL / "decisions_2026-10-18.csv"


def _results(profile: str, changes: Path | None = None):
    bom = load_bom(BOM)
    if changes is not None:
        bom = apply_changes(bom, changes)
    return evaluate(
        bom,
        load_batteries(MODEL / "batteries.csv"),
        load_curve(MODEL / "x8_original_46v.csv"),
        PROFILES[profile],
    )


def test_ledger_totals_match_feasibility_study() -> None:
    bom = load_bom(BOM)
    catalogue = sum(
        c.mass_kg for c in bom if c.mass_evidence == "catalogue_claim" and c.id != "battery"
    )
    assumed = sum(c.mass_kg for c in bom if c.mass_evidence == "assumed")
    assert catalogue == pytest.approx(16.609, abs=1e-6)
    assert assumed == pytest.approx(3.750, abs=1e-6)


@pytest.mark.parametrize(
    ("battery_id", "auw_kg", "kw", "minutes"),
    [
        ("tattu_22ah_semisolid", 23.780, 2.351, 19.9),
        ("tattu_neo_26ah", 24.539, 2.447, 22.6),
        ("tattu_neo_33ah", 25.507, 2.570, 27.4),
        ("tattu_neo_36ah", 25.860, 2.615, 29.3),
        ("tattu_22ah_smart", 26.359, 2.678, 17.5),
    ],
)
def test_screening_profile_reproduces_feasibility_table(battery_id, auw_kg, kw, minutes) -> None:
    result = next(r for r in _results("screening") if r.battery.id == battery_id)
    assert result.takeoff_kg == pytest.approx(auw_kg, abs=0.001)
    assert result.total_w / 1000 == pytest.approx(kw, abs=0.001)
    assert result.minutes == pytest.approx(minutes, abs=0.05)


def test_55_lb_flags_match_feasibility_table() -> None:
    flags = {r.battery.id: r.under_55_lb for r in _results("screening")}
    assert flags == {
        "tattu_22ah_semisolid": True,
        "tattu_neo_26ah": True,
        "tattu_neo_33ah": False,
        "tattu_neo_36ah": False,
        "tattu_22ah_smart": False,
    }


def test_22ah_semisolid_fails_current_rule() -> None:
    result = next(r for r in _results("screening") if r.battery.id == "tattu_22ah_semisolid")
    assert result.hover_current_a == pytest.approx(53, abs=0.5)
    assert result.meets_current_rule is False


def test_unknown_continuous_rating_is_unknown_not_pass() -> None:
    result = next(r for r in _results("screening") if r.battery.id == "tattu_neo_33ah")
    assert result.meets_current_rule is None


def test_decision_scenario_changes_mass_as_expected() -> None:
    before = {c.id: c for c in load_bom(BOM)}
    after = {c.id: c for c in apply_changes(load_bom(BOM), DECISIONS)}
    for removed in ("lens", "gimbal", "camera_ancillary", "thermal"):
        assert removed not in after
    assert {"stills_package", "zoom_thermal_gimbal"} <= after.keys()
    assert after["propulsion"].mass_each_kg == pytest.approx(1.095)
    saved = sum(c.mass_kg for c in before.values()) - sum(c.mass_kg for c in after.values())
    # P1 ~1.32 kg + Boson+ 0.15 kg + X8 G2 6 x 0.055 kg
    assert saved == pytest.approx(1.323 + 0.150 + 0.330, abs=0.001)


def test_out_of_table_thrust_is_not_extrapolated() -> None:
    curve = [(3.535, 317.5), (4.467, 435.7)]
    with pytest.raises(ValueError, match="refusing to extrapolate"):
        interpolate_power(curve, 4.5)
    result = evaluate(
        [Component("frame", "heavy", 1, 30.0, "assumed")],
        [Battery("b", "b", 1.0, 1000.0, 200.0)],
        curve,
        PROFILES["screening"],
    )[0]
    assert result.minutes is None
    assert result.meets_current_rule is None


@pytest.mark.parametrize(
    "rows",
    [
        "action,id,component,quantity,mass_each_kg,mass_evidence,notes\nremove,nope,,,,,\n",
        "action,id,component,quantity,mass_each_kg,mass_evidence,notes\n"
        "add,frame,x,1,1.0,assumed,\n",
        "action,id,component,quantity,mass_each_kg,mass_evidence,notes\nswap,frame,,,,,\n",
    ],
)
def test_invalid_changes_are_rejected(tmp_path, rows) -> None:
    path = tmp_path / "changes.csv"
    path.write_text(rows, encoding="utf-8")
    with pytest.raises(ValueError):
        apply_changes(load_bom(BOM), path)


def test_cli_prints_table(capsys) -> None:
    assert main(["--profile", "conservative", "--changes", str(DECISIONS)]) == 0
    out = capsys.readouterr().out
    assert "SCREENING ESTIMATE ONLY" in out
    assert "| Tattu Neo 33Ah 12S |" in out
