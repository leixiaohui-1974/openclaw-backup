"""Dual-tank PID simulation, optimization and report helpers."""

from .optimization import optimize_pid_grid, optimize_pid_multiobjective, optimize_pid_random_refine
from .simulation import (
    DisturbanceConfig,
    DualTankConfig,
    LinearizedDualTankModel,
    LQRWeights,
    MPCConfig,
    MeasurementNoiseConfig,
    PIDGains,
    ParameterUncertaintyConfig,
    SimulationConfig,
    linearize_dual_tank,
    simulate_dual_tank_lqr,
    simulate_dual_tank_mpc,
    simulate_dual_tank_pid,
    solve_discrete_lqr,
)

_report_import_error = None
try:
    from .report import build_pid_report_markdown, generate_pid_report_artifacts
except Exception as exc:  # pragma: no cover - optional plotting dependency
    _report_import_error = exc

    def generate_pid_report_artifacts(*args, **kwargs):  # type: ignore[no-redef]
        raise RuntimeError(f"tank_pid.report unavailable: {_report_import_error}")

    def build_pid_report_markdown(*args, **kwargs):  # type: ignore[no-redef]
        raise RuntimeError(f"tank_pid.report unavailable: {_report_import_error}")

__all__ = [
    "DisturbanceConfig",
    "DualTankConfig",
    "LinearizedDualTankModel",
    "LQRWeights",
    "MPCConfig",
    "MeasurementNoiseConfig",
    "PIDGains",
    "ParameterUncertaintyConfig",
    "SimulationConfig",
    "linearize_dual_tank",
    "solve_discrete_lqr",
    "simulate_dual_tank_lqr",
    "simulate_dual_tank_mpc",
    "simulate_dual_tank_pid",
    "optimize_pid_grid",
    "optimize_pid_random_refine",
    "optimize_pid_multiobjective",
    "generate_pid_report_artifacts",
    "build_pid_report_markdown",
]
