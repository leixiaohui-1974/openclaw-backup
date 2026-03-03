"""PID parameter optimization routines with multi-objective support."""

from __future__ import annotations

import random
from dataclasses import dataclass

from .simulation import (
    DisturbanceConfig,
    DualTankConfig,
    MeasurementNoiseConfig,
    PIDGains,
    ParameterUncertaintyConfig,
    SimulationConfig,
    simulate_dual_tank_pid,
)


@dataclass
class MultiObjectiveWeights:
    iae: float = 1.0
    overshoot: float = 60.0
    final_error: float = 0.3
    control_variation: float = 0.15
    control_energy: float = 0.02


def _score(metrics: dict, weights: MultiObjectiveWeights | None = None) -> float:
    w = weights or MultiObjectiveWeights()
    return (
        w.iae * metrics.get("iae", 0.0)
        + w.overshoot * metrics.get("overshoot_m", 0.0)
        + w.final_error * abs(metrics.get("final_error_m", 0.0))
        + w.control_variation * metrics.get("control_variation", 0.0)
        + w.control_energy * metrics.get("control_energy", 0.0)
    )


def _evaluate_candidate(
    trial_id: int,
    kp: float,
    ki: float,
    kd: float,
    tank: DualTankConfig,
    sim: SimulationConfig,
    disturbance: DisturbanceConfig,
    measurement_noise: MeasurementNoiseConfig | None,
    parameter_uncertainty: ParameterUncertaintyConfig | None,
    weights: MultiObjectiveWeights | None,
) -> dict:
    gains = PIDGains(kp=kp, ki=ki, kd=kd)
    sim_out = simulate_dual_tank_pid(
        tank=tank,
        sim=sim,
        gains=gains,
        disturbance=disturbance,
        measurement_noise=measurement_noise,
        parameter_uncertainty=parameter_uncertainty,
    )
    metrics = sim_out["metrics"]
    return {
        "trial": trial_id,
        "kp": kp,
        "ki": ki,
        "kd": kd,
        "score": _score(metrics, weights=weights),
        "metrics": metrics,
    }


def _dominates(a: dict, b: dict) -> bool:
    ma = a.get("metrics", {})
    mb = b.get("metrics", {})
    objectives = ("iae", "overshoot_m", "control_energy")
    better_or_equal = all(ma.get(k, 0.0) <= mb.get(k, 0.0) for k in objectives)
    strictly_better = any(ma.get(k, 0.0) < mb.get(k, 0.0) for k in objectives)
    return better_or_equal and strictly_better


def _pareto_front(trials: list[dict]) -> list[dict]:
    front: list[dict] = []
    for cand in trials:
        dominated = False
        for other in trials:
            if other is cand:
                continue
            if _dominates(other, cand):
                dominated = True
                break
        if not dominated:
            front.append(cand)
    front.sort(key=lambda x: x.get("metrics", {}).get("iae", 0.0))
    return front


def optimize_pid_grid(
    tank: DualTankConfig,
    sim: SimulationConfig,
    disturbance: DisturbanceConfig,
    seed_gains: PIDGains,
    top_k: int = 5,
    measurement_noise: MeasurementNoiseConfig | None = None,
    parameter_uncertainty: ParameterUncertaintyConfig | None = None,
    objective_weights: MultiObjectiveWeights | None = None,
) -> dict:
    kp_grid = sorted({max(0.05, seed_gains.kp * s) for s in (0.5, 0.8, 1.0, 1.2, 1.6)})
    ki_grid = sorted({max(0.0, seed_gains.ki * s) for s in (0.5, 0.8, 1.0, 1.4, 2.0)})
    kd_grid = sorted({max(0.0, seed_gains.kd * s) for s in (0.3, 0.6, 1.0, 1.4, 2.0)})

    trials: list[dict] = []
    idx = 0
    for kp in kp_grid:
        for ki in ki_grid:
            for kd in kd_grid:
                idx += 1
                trials.append(
                    _evaluate_candidate(
                        trial_id=idx,
                        kp=kp,
                        ki=ki,
                        kd=kd,
                        tank=tank,
                        sim=sim,
                        disturbance=disturbance,
                        measurement_noise=measurement_noise,
                        parameter_uncertainty=parameter_uncertainty,
                        weights=objective_weights,
                    )
                )

    trials.sort(key=lambda x: x["score"])
    pareto = _pareto_front(trials)
    return {
        "method": "grid",
        "best": trials[0],
        "top": trials[: max(1, top_k)],
        "pareto_front": pareto,
        "trials": trials,
        "grid_size": len(kp_grid) * len(ki_grid) * len(kd_grid),
    }


def optimize_pid_random_refine(
    tank: DualTankConfig,
    sim: SimulationConfig,
    disturbance: DisturbanceConfig,
    seed_gains: PIDGains,
    top_k: int = 5,
    random_trials: int = 48,
    refine_trials: int = 36,
    seed: int = 17,
    measurement_noise: MeasurementNoiseConfig | None = None,
    parameter_uncertainty: ParameterUncertaintyConfig | None = None,
    objective_weights: MultiObjectiveWeights | None = None,
) -> dict:
    rng = random.Random(seed)
    trials: list[dict] = []
    idx = 0

    kp_bounds = (max(0.05, seed_gains.kp * 0.3), max(0.06, seed_gains.kp * 2.2))
    ki_bounds = (0.0, max(0.01, seed_gains.ki * 3.0))
    kd_bounds = (0.0, max(0.01, seed_gains.kd * 3.0))

    for _ in range(max(1, random_trials)):
        idx += 1
        kp = rng.uniform(*kp_bounds)
        ki = rng.uniform(*ki_bounds)
        kd = rng.uniform(*kd_bounds)
        trials.append(
            _evaluate_candidate(
                trial_id=idx,
                kp=kp,
                ki=ki,
                kd=kd,
                tank=tank,
                sim=sim,
                disturbance=disturbance,
                measurement_noise=measurement_noise,
                parameter_uncertainty=parameter_uncertainty,
                weights=objective_weights,
            )
        )

    # Local refinement around current elites.
    elite_count = max(2, min(6, top_k))
    for _ in range(max(1, refine_trials)):
        elites = sorted(trials, key=lambda x: x["score"])[:elite_count]
        anchor = rng.choice(elites)
        idx += 1
        kp = max(kp_bounds[0], min(kp_bounds[1], anchor["kp"] * (1.0 + rng.gauss(0.0, 0.12))))
        ki = max(ki_bounds[0], min(ki_bounds[1], anchor["ki"] * (1.0 + rng.gauss(0.0, 0.18))))
        kd = max(kd_bounds[0], min(kd_bounds[1], anchor["kd"] * (1.0 + rng.gauss(0.0, 0.18))))
        trials.append(
            _evaluate_candidate(
                trial_id=idx,
                kp=kp,
                ki=ki,
                kd=kd,
                tank=tank,
                sim=sim,
                disturbance=disturbance,
                measurement_noise=measurement_noise,
                parameter_uncertainty=parameter_uncertainty,
                weights=objective_weights,
            )
        )

    trials.sort(key=lambda x: x["score"])
    pareto = _pareto_front(trials)
    return {
        "method": "random_refine",
        "best": trials[0],
        "top": trials[: max(1, top_k)],
        "pareto_front": pareto,
        "trials": trials,
        "search_size": len(trials),
        "random_trials": max(1, random_trials),
        "refine_trials": max(1, refine_trials),
    }


def optimize_pid_multiobjective(
    tank: DualTankConfig,
    sim: SimulationConfig,
    disturbance: DisturbanceConfig,
    seed_gains: PIDGains,
    top_k: int = 5,
    method: str = "grid",
    measurement_noise: MeasurementNoiseConfig | None = None,
    parameter_uncertainty: ParameterUncertaintyConfig | None = None,
    objective_weights: MultiObjectiveWeights | None = None,
) -> dict:
    method_norm = (method or "grid").strip().lower()
    if method_norm in {"grid", "grid_search"}:
        return optimize_pid_grid(
            tank=tank,
            sim=sim,
            disturbance=disturbance,
            seed_gains=seed_gains,
            top_k=top_k,
            measurement_noise=measurement_noise,
            parameter_uncertainty=parameter_uncertainty,
            objective_weights=objective_weights,
        )
    if method_norm in {"random", "random_refine", "hybrid"}:
        return optimize_pid_random_refine(
            tank=tank,
            sim=sim,
            disturbance=disturbance,
            seed_gains=seed_gains,
            top_k=top_k,
            measurement_noise=measurement_noise,
            parameter_uncertainty=parameter_uncertainty,
            objective_weights=objective_weights,
        )
    raise ValueError(f"Unsupported optimizer method: {method}")
