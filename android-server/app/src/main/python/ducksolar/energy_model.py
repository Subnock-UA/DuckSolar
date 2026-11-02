from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FlowInput:
    pv_w: float
    load_w: float
    battery_v: float
    battery_charge_a: float
    grid_available: bool


@dataclass
class FlowResult:
    pv_corrected_w: float
    battery_charge_w: float
    pv_to_battery_w: float
    grid_to_battery_w: float
    pv_to_house_w: float
    grid_to_house_w: float
    grid_import_w: float
    export_w: float
    inverter_self_w: float


def calculate_flows(
    x: FlowInput,
    pv_factor: float = 1.0,
    inverter_self_w: float = 0.0,
) -> FlowResult:
    """
    Approved Alpha0.1 model:
      1) corrected PV = PV total × factor;
      2) measured battery charging demand = V × charge current;
      3) PV first covers that battery charging demand;
      4) if PV is insufficient and grid exists, the charging deficit is from grid;
      5) remaining PV covers house + inverter self-consumption;
      6) remaining house deficit is from grid;
      7) only remaining PV may be exported;
      8) if grid is absent, export is physically impossible and is forced to 0.

    BatteryDischargeCurrent is displayed/recorded but intentionally not used
    as a separate balance source in this approved model.
    """
    pv = max(0.0, float(x.pv_w)) * max(0.0, float(pv_factor))
    charge = max(0.0, float(x.battery_v) * float(x.battery_charge_a))
    self_w = max(0.0, float(inverter_self_w))

    pv_to_battery = min(pv, charge)
    charge_deficit = max(0.0, charge - pv_to_battery)
    grid_to_battery = charge_deficit if x.grid_available else 0.0

    pv_after_battery = max(0.0, pv - pv_to_battery)
    house_side = max(0.0, float(x.load_w)) + self_w

    pv_to_house = min(pv_after_battery, house_side)
    house_deficit = max(0.0, house_side - pv_to_house)
    grid_to_house = house_deficit if x.grid_available else 0.0

    grid_import = grid_to_battery + grid_to_house if x.grid_available else 0.0
    export = max(0.0, pv_after_battery - house_side) if x.grid_available else 0.0

    return FlowResult(
        pv_corrected_w=pv,
        battery_charge_w=charge,
        pv_to_battery_w=pv_to_battery,
        grid_to_battery_w=grid_to_battery,
        pv_to_house_w=pv_to_house,
        grid_to_house_w=grid_to_house,
        grid_import_w=grid_import,
        export_w=export,
        inverter_self_w=self_w,
    )
