"""Dual-tank closed-loop simulation with disturbance, noise and uncertainty options."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .pid import PIDController


@dataclass
class DualTankConfig:
    area1: float = 1.0
    area2: float = 1.0
    c12: float = 0.07
    c2: float = 0.06
    h_min: float = 0.0
    h_max: float = 2.0


@dataclass
class PIDGains:
    kp: float = 2.0
    ki: float = 0.1
    kd: float = 0.5


@dataclass
class DisturbanceConfig:
    kind: str = "outflow"  # inflow|outflow
    start_s: float = 120.0
    end_s: float | None = None
    magnitude: float = 0.002


@dataclass
class SimulationConfig:
    duration_s: float = 300.0
    dt_s: float = 1.0
    initial_h1: float = 0.6
    initial_h2: float = 0.5
    setpoint: float = 1.0
    base_inflow: float = 0.01
    inflow_min: float = 0.0
    inflow_max: float = 0.05


@dataclass
class MeasurementNoiseConfig:
    enabled: bool = False
    std_h1: float = 0.0
    std_h2: float = 0.003
    bias_h1: float = 0.0
    bias_h2: float = 0.0
    seed: int = 42


@dataclass
class ParameterUncertaintyConfig:
    enabled: bool = False
    rel_area1: float = 0.0
    rel_area2: float = 0.0
    rel_c12: float = 0.0
    rel_c2: float = 0.0
    seed: int = 123


@dataclass
class LQRWeights:
    q_h1: float = 2.0
    q_h2: float = 25.0
    r_u: float = 0.2


@dataclass
class MPCConfig:
    horizon_steps: int = 12
    q_h1: float = 2.0
    q_h2: float = 28.0
    r_du: float = 0.35
    optimizer_iters: int = 18
    step_size: float = 0.12
    grad_eps: float = 1e-4
    tol: float = 1e-5


@dataclass
class LinearizedDualTankModel:
    ad11: float
    ad12: float
    ad21: float
    ad22: float
    bd1: float
    bd2: float
    h1_eq: float
    h2_eq: float
    u_eq: float


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _disturbance_value(t: float, disturbance: DisturbanceConfig) -> float:
    if t < disturbance.start_s:
        return 0.0
    if disturbance.end_s is not None and t > disturbance.end_s:
        return 0.0
    return disturbance.magnitude


def _settling_time(time_s: list[float], values: list[float], setpoint: float, tol: float = 0.02) -> float | None:
    if not values:
        return None
    band = tol * max(setpoint, 1e-6)
    for i in range(len(values)):
        ok = True
        for j in range(i, len(values)):
            if abs(values[j] - setpoint) > band:
                ok = False
                break
        if ok:
            return time_s[i]
    return None


def _steady_state_from_h2(h2_eq: float, c12: float, c2: float) -> tuple[float, float]:
    h2_eq = max(h2_eq, 1e-6)
    c12_safe = max(c12, 1e-6)
    delta_h = ((c2 / c12_safe) ** 2) * h2_eq
    h1_eq = h2_eq + delta_h
    u_eq = c2 * math.sqrt(h2_eq)
    return h1_eq, u_eq


def linearize_dual_tank(
    tank: DualTankConfig,
    dt_s: float,
    h2_eq: float,
) -> LinearizedDualTankModel:
    area1 = max(tank.area1, 1e-6)
    area2 = max(tank.area2, 1e-6)
    c12 = max(tank.c12, 1e-6)
    c2 = max(tank.c2, 1e-6)

    h1_eq, u_eq = _steady_state_from_h2(h2_eq=h2_eq, c12=c12, c2=c2)
    delta_eq = max(h1_eq - h2_eq, 1e-6)
    g12 = c12 / (2.0 * math.sqrt(delta_eq))
    g2 = c2 / (2.0 * math.sqrt(max(h2_eq, 1e-6)))

    a11 = -g12 / area1
    a12 = g12 / area1
    a21 = g12 / area2
    a22 = (-g12 - g2) / area2
    b1 = 1.0 / area1
    b2 = 0.0

    dt = max(dt_s, 1e-6)
    ad11 = 1.0 + dt * a11
    ad12 = dt * a12
    ad21 = dt * a21
    ad22 = 1.0 + dt * a22
    bd1 = dt * b1
    bd2 = dt * b2
    return LinearizedDualTankModel(
        ad11=ad11,
        ad12=ad12,
        ad21=ad21,
        ad22=ad22,
        bd1=bd1,
        bd2=bd2,
        h1_eq=h1_eq,
        h2_eq=h2_eq,
        u_eq=u_eq,
    )


def solve_discrete_lqr(
    model: LinearizedDualTankModel,
    weights: LQRWeights,
    max_iterations: int = 200,
    tol: float = 1e-10,
) -> tuple[float, float]:
    q11 = max(weights.q_h1, 1e-12)
    q22 = max(weights.q_h2, 1e-12)
    r = max(weights.r_u, 1e-12)
    p11, p12, p22 = q11, 0.0, q22

    a11, a12 = model.ad11, model.ad12
    a21, a22 = model.ad21, model.ad22
    b1, b2 = model.bd1, model.bd2

    for _ in range(max(1, max_iterations)):
        bt_p_b = b1 * (p11 * b1 + p12 * b2) + b2 * (p12 * b1 + p22 * b2)
        s = r + bt_p_b
        if s <= 1e-14:
            s = 1e-14

        bt_p_a1 = b1 * (p11 * a11 + p12 * a21) + b2 * (p12 * a11 + p22 * a21)
        bt_p_a2 = b1 * (p11 * a12 + p12 * a22) + b2 * (p12 * a12 + p22 * a22)
        k1 = bt_p_a1 / s
        k2 = bt_p_a2 / s

        pa11 = p11 * a11 + p12 * a21
        pa12 = p11 * a12 + p12 * a22
        pa21 = p12 * a11 + p22 * a21
        pa22 = p12 * a12 + p22 * a22

        ata11 = a11 * pa11 + a21 * pa21
        ata12 = a11 * pa12 + a21 * pa22
        ata22 = a12 * pa12 + a22 * pa22

        atpb11 = a11 * (p11 * b1 + p12 * b2) + a21 * (p12 * b1 + p22 * b2)
        atpb21 = a12 * (p11 * b1 + p12 * b2) + a22 * (p12 * b1 + p22 * b2)

        p_next11 = q11 + ata11 - (atpb11 * atpb11) / s
        p_next12 = ata12 - (atpb11 * atpb21) / s
        p_next22 = q22 + ata22 - (atpb21 * atpb21) / s

        diff = max(abs(p_next11 - p11), abs(p_next12 - p12), abs(p_next22 - p22))
        p11, p12, p22 = p_next11, p_next12, p_next22
        if diff < tol:
            break

    bt_p_b = b1 * (p11 * b1 + p12 * b2) + b2 * (p12 * b1 + p22 * b2)
    s = max(r + bt_p_b, 1e-14)
    bt_p_a1 = b1 * (p11 * a11 + p12 * a21) + b2 * (p12 * a11 + p22 * a21)
    bt_p_a2 = b1 * (p11 * a12 + p12 * a22) + b2 * (p12 * a12 + p22 * a22)
    return bt_p_a1 / s, bt_p_a2 / s


def simulate_dual_tank_pid(
    tank: DualTankConfig,
    sim: SimulationConfig,
    gains: PIDGains,
    disturbance: DisturbanceConfig,
    measurement_noise: MeasurementNoiseConfig | None = None,
    parameter_uncertainty: ParameterUncertaintyConfig | None = None,
) -> dict:
    measurement_noise = measurement_noise or MeasurementNoiseConfig()
    parameter_uncertainty = parameter_uncertainty or ParameterUncertaintyConfig()

    rng_meas = random.Random(measurement_noise.seed)
    rng_unc = random.Random(parameter_uncertainty.seed)

    area1 = tank.area1
    area2 = tank.area2
    c12 = tank.c12
    c2 = tank.c2
    if parameter_uncertainty.enabled:
        area1 *= 1.0 + rng_unc.uniform(-parameter_uncertainty.rel_area1, parameter_uncertainty.rel_area1)
        area2 *= 1.0 + rng_unc.uniform(-parameter_uncertainty.rel_area2, parameter_uncertainty.rel_area2)
        c12 *= 1.0 + rng_unc.uniform(-parameter_uncertainty.rel_c12, parameter_uncertainty.rel_c12)
        c2 *= 1.0 + rng_unc.uniform(-parameter_uncertainty.rel_c2, parameter_uncertainty.rel_c2)

    steps = max(1, int(sim.duration_s / sim.dt_s))
    pid = PIDController(
        kp=gains.kp,
        ki=gains.ki,
        kd=gains.kd,
        dt=sim.dt_s,
        u_min=sim.inflow_min,
        u_max=sim.inflow_max,
    )

    t_arr: list[float] = [0.0]
    h1_arr: list[float] = [sim.initial_h1]
    h2_arr: list[float] = [sim.initial_h2]
    h2_measured_arr: list[float] = [sim.initial_h2]
    u_arr: list[float] = []
    disturbance_arr: list[float] = []

    h1 = sim.initial_h1
    h2 = sim.initial_h2
    abs_error_integral = 0.0
    sq_error_integral = 0.0
    control_variation = 0.0
    control_energy = 0.0
    last_u = sim.base_inflow

    for k in range(steps):
        t = k * sim.dt_s
        h2_measured = h2
        if measurement_noise.enabled:
            h2_measured += measurement_noise.bias_h2 + rng_meas.gauss(0.0, measurement_noise.std_h2)
        error = sim.setpoint - h2_measured
        u = pid.step(error=error, base_inflow=sim.base_inflow)
        d = _disturbance_value(t, disturbance)

        q12 = c12 * math.sqrt(max(h1 - h2, 0.0))
        q2_base = c2 * math.sqrt(max(h2, 0.0))
        qin = u + d if disturbance.kind == "inflow" else u
        q2 = q2_base + d if disturbance.kind == "outflow" else q2_base

        dh1 = (qin - q12) / max(area1, 1e-6)
        dh2 = (q12 - q2) / max(area2, 1e-6)
        h1 = _clamp(h1 + sim.dt_s * dh1, tank.h_min, tank.h_max)
        h2 = _clamp(h2 + sim.dt_s * dh2, tank.h_min, tank.h_max)

        t_arr.append((k + 1) * sim.dt_s)
        h1_arr.append(h1)
        h2_arr.append(h2)
        h2_measured_arr.append(h2_measured)
        u_arr.append(u)
        disturbance_arr.append(d)

        abs_error_integral += abs(error) * sim.dt_s
        sq_error_integral += (error * error) * sim.dt_s
        control_variation += abs(u - last_u)
        control_energy += (u * u) * sim.dt_s
        last_u = u

    overshoot = max(0.0, max(h2_arr) - sim.setpoint)
    settle_s = _settling_time(t_arr, h2_arr, sim.setpoint)

    return {
        "time_s": t_arr,
        "h1_m": h1_arr,
        "h2_m": h2_arr,
        "h2_measured_m": h2_measured_arr,
        "setpoint_m": [sim.setpoint] * len(t_arr),
        "control_u_m3s": [u_arr[0] if u_arr else sim.base_inflow] + u_arr,
        "disturbance_m3s": [0.0] + disturbance_arr,
        "disturbance_kind": disturbance.kind,
        "metrics": {
            "iae": abs_error_integral,
            "ise": sq_error_integral,
            "overshoot_m": overshoot,
            "settling_time_s": settle_s,
            "final_error_m": sim.setpoint - h2_arr[-1],
            "control_variation": control_variation,
            "control_energy": control_energy,
        },
        "config": {
            "tank": tank.__dict__,
            "sim": sim.__dict__,
            "gains": gains.__dict__,
            "disturbance": disturbance.__dict__,
            "measurement_noise": measurement_noise.__dict__,
            "parameter_uncertainty": parameter_uncertainty.__dict__,
            "realized_plant": {"area1": area1, "area2": area2, "c12": c12, "c2": c2},
        },
    }


def simulate_dual_tank_lqr(
    tank: DualTankConfig,
    sim: SimulationConfig,
    disturbance: DisturbanceConfig,
    lqr_weights: LQRWeights | None = None,
    measurement_noise: MeasurementNoiseConfig | None = None,
    parameter_uncertainty: ParameterUncertaintyConfig | None = None,
) -> dict:
    measurement_noise = measurement_noise or MeasurementNoiseConfig()
    parameter_uncertainty = parameter_uncertainty or ParameterUncertaintyConfig()
    lqr_weights = lqr_weights or LQRWeights()

    rng_meas = random.Random(measurement_noise.seed)
    rng_unc = random.Random(parameter_uncertainty.seed)

    area1 = tank.area1
    area2 = tank.area2
    c12 = tank.c12
    c2 = tank.c2
    if parameter_uncertainty.enabled:
        area1 *= 1.0 + rng_unc.uniform(-parameter_uncertainty.rel_area1, parameter_uncertainty.rel_area1)
        area2 *= 1.0 + rng_unc.uniform(-parameter_uncertainty.rel_area2, parameter_uncertainty.rel_area2)
        c12 *= 1.0 + rng_unc.uniform(-parameter_uncertainty.rel_c12, parameter_uncertainty.rel_c12)
        c2 *= 1.0 + rng_unc.uniform(-parameter_uncertainty.rel_c2, parameter_uncertainty.rel_c2)

    h2_eq = _clamp(sim.setpoint, max(1e-4, tank.h_min + 1e-6), tank.h_max)
    lin_model = linearize_dual_tank(tank=tank, dt_s=sim.dt_s, h2_eq=h2_eq)
    k1, k2 = solve_discrete_lqr(model=lin_model, weights=lqr_weights)

    steps = max(1, int(sim.duration_s / sim.dt_s))
    t_arr: list[float] = [0.0]
    h1_arr: list[float] = [sim.initial_h1]
    h2_arr: list[float] = [sim.initial_h2]
    h1_measured_arr: list[float] = [sim.initial_h1]
    h2_measured_arr: list[float] = [sim.initial_h2]
    u_arr: list[float] = []
    disturbance_arr: list[float] = []

    h1 = sim.initial_h1
    h2 = sim.initial_h2
    abs_error_integral = 0.0
    sq_error_integral = 0.0
    control_variation = 0.0
    control_energy = 0.0
    last_u = lin_model.u_eq

    for k in range(steps):
        t = k * sim.dt_s
        h1_measured = h1
        h2_measured = h2
        if measurement_noise.enabled:
            h1_measured += measurement_noise.bias_h1 + rng_meas.gauss(0.0, measurement_noise.std_h1)
            h2_measured += measurement_noise.bias_h2 + rng_meas.gauss(0.0, measurement_noise.std_h2)

        du = -(k1 * (h1_measured - lin_model.h1_eq) + k2 * (h2_measured - lin_model.h2_eq))
        u = _clamp(lin_model.u_eq + du, sim.inflow_min, sim.inflow_max)
        d = _disturbance_value(t, disturbance)

        q12 = c12 * math.sqrt(max(h1 - h2, 0.0))
        q2_base = c2 * math.sqrt(max(h2, 0.0))
        qin = u + d if disturbance.kind == "inflow" else u
        q2 = q2_base + d if disturbance.kind == "outflow" else q2_base

        dh1 = (qin - q12) / max(area1, 1e-6)
        dh2 = (q12 - q2) / max(area2, 1e-6)
        h1 = _clamp(h1 + sim.dt_s * dh1, tank.h_min, tank.h_max)
        h2 = _clamp(h2 + sim.dt_s * dh2, tank.h_min, tank.h_max)

        t_arr.append((k + 1) * sim.dt_s)
        h1_arr.append(h1)
        h2_arr.append(h2)
        h1_measured_arr.append(h1_measured)
        h2_measured_arr.append(h2_measured)
        u_arr.append(u)
        disturbance_arr.append(d)

        error = sim.setpoint - h2_measured
        abs_error_integral += abs(error) * sim.dt_s
        sq_error_integral += (error * error) * sim.dt_s
        control_variation += abs(u - last_u)
        control_energy += (u * u) * sim.dt_s
        last_u = u

    overshoot = max(0.0, max(h2_arr) - sim.setpoint)
    settle_s = _settling_time(t_arr, h2_arr, sim.setpoint)

    return {
        "time_s": t_arr,
        "h1_m": h1_arr,
        "h2_m": h2_arr,
        "h1_measured_m": h1_measured_arr,
        "h2_measured_m": h2_measured_arr,
        "setpoint_m": [sim.setpoint] * len(t_arr),
        "control_u_m3s": [u_arr[0] if u_arr else lin_model.u_eq] + u_arr,
        "disturbance_m3s": [0.0] + disturbance_arr,
        "disturbance_kind": disturbance.kind,
        "metrics": {
            "iae": abs_error_integral,
            "ise": sq_error_integral,
            "overshoot_m": overshoot,
            "settling_time_s": settle_s,
            "final_error_m": sim.setpoint - h2_arr[-1],
            "control_variation": control_variation,
            "control_energy": control_energy,
        },
        "config": {
            "tank": tank.__dict__,
            "sim": sim.__dict__,
            "lqr_weights": lqr_weights.__dict__,
            "lqr_design": {
                "h1_eq": lin_model.h1_eq,
                "h2_eq": lin_model.h2_eq,
                "u_eq": lin_model.u_eq,
                "k1": k1,
                "k2": k2,
            },
            "disturbance": disturbance.__dict__,
            "measurement_noise": measurement_noise.__dict__,
            "parameter_uncertainty": parameter_uncertainty.__dict__,
            "realized_plant": {"area1": area1, "area2": area2, "c12": c12, "c2": c2},
        },
    }


def _mpc_rollout_cost(
    x0: tuple[float, float],
    du_seq: list[float],
    model: LinearizedDualTankModel,
    mpc: MPCConfig,
) -> float:
    x1, x2 = x0
    cost = 0.0
    for du in du_seq:
        x1_next = model.ad11 * x1 + model.ad12 * x2 + model.bd1 * du
        x2_next = model.ad21 * x1 + model.ad22 * x2 + model.bd2 * du
        cost += mpc.q_h1 * (x1_next * x1_next) + mpc.q_h2 * (x2_next * x2_next) + mpc.r_du * (du * du)
        x1, x2 = x1_next, x2_next
    return cost


def _solve_projected_gradient_mpc(
    x0: tuple[float, float],
    model: LinearizedDualTankModel,
    mpc: MPCConfig,
    du_min: float,
    du_max: float,
    warm_start: list[float] | None = None,
) -> list[float]:
    horizon = max(2, int(mpc.horizon_steps))
    du_seq = [0.0] * horizon
    if warm_start:
        for i in range(min(horizon, len(warm_start))):
            du_seq[i] = _clamp(warm_start[i], du_min, du_max)

    alpha = max(1e-4, float(mpc.step_size))
    eps = max(1e-7, float(mpc.grad_eps))
    max_iters = max(1, int(mpc.optimizer_iters))
    tol = max(0.0, float(mpc.tol))

    for _ in range(max_iters):
        base_cost = _mpc_rollout_cost(x0=x0, du_seq=du_seq, model=model, mpc=mpc)
        grad: list[float] = []
        for j in range(horizon):
            old = du_seq[j]
            du_seq[j] = _clamp(old + eps, du_min, du_max)
            cp = _mpc_rollout_cost(x0=x0, du_seq=du_seq, model=model, mpc=mpc)
            du_seq[j] = _clamp(old - eps, du_min, du_max)
            cm = _mpc_rollout_cost(x0=x0, du_seq=du_seq, model=model, mpc=mpc)
            du_seq[j] = old
            grad.append((cp - cm) / (2.0 * eps))

        step = alpha
        accepted = False
        next_seq = du_seq[:]
        while step >= 1e-6:
            for j in range(horizon):
                next_seq[j] = _clamp(du_seq[j] - step * grad[j], du_min, du_max)
            next_cost = _mpc_rollout_cost(x0=x0, du_seq=next_seq, model=model, mpc=mpc)
            if next_cost <= base_cost:
                accepted = True
                break
            step *= 0.5

        if not accepted:
            break

        max_delta = max(abs(next_seq[j] - du_seq[j]) for j in range(horizon))
        du_seq = next_seq[:]
        if max_delta <= tol:
            break

    return du_seq


def simulate_dual_tank_mpc(
    tank: DualTankConfig,
    sim: SimulationConfig,
    disturbance: DisturbanceConfig,
    mpc_config: MPCConfig | None = None,
    measurement_noise: MeasurementNoiseConfig | None = None,
    parameter_uncertainty: ParameterUncertaintyConfig | None = None,
) -> dict:
    measurement_noise = measurement_noise or MeasurementNoiseConfig()
    parameter_uncertainty = parameter_uncertainty or ParameterUncertaintyConfig()
    mpc_config = mpc_config or MPCConfig()

    rng_meas = random.Random(measurement_noise.seed)
    rng_unc = random.Random(parameter_uncertainty.seed)

    area1 = tank.area1
    area2 = tank.area2
    c12 = tank.c12
    c2 = tank.c2
    if parameter_uncertainty.enabled:
        area1 *= 1.0 + rng_unc.uniform(-parameter_uncertainty.rel_area1, parameter_uncertainty.rel_area1)
        area2 *= 1.0 + rng_unc.uniform(-parameter_uncertainty.rel_area2, parameter_uncertainty.rel_area2)
        c12 *= 1.0 + rng_unc.uniform(-parameter_uncertainty.rel_c12, parameter_uncertainty.rel_c12)
        c2 *= 1.0 + rng_unc.uniform(-parameter_uncertainty.rel_c2, parameter_uncertainty.rel_c2)

    h2_eq = _clamp(sim.setpoint, max(1e-4, tank.h_min + 1e-6), tank.h_max)
    lin_model = linearize_dual_tank(tank=tank, dt_s=sim.dt_s, h2_eq=h2_eq)
    du_min = sim.inflow_min - lin_model.u_eq
    du_max = sim.inflow_max - lin_model.u_eq

    steps = max(1, int(sim.duration_s / sim.dt_s))
    t_arr: list[float] = [0.0]
    h1_arr: list[float] = [sim.initial_h1]
    h2_arr: list[float] = [sim.initial_h2]
    h1_measured_arr: list[float] = [sim.initial_h1]
    h2_measured_arr: list[float] = [sim.initial_h2]
    u_arr: list[float] = []
    disturbance_arr: list[float] = []

    h1 = sim.initial_h1
    h2 = sim.initial_h2
    abs_error_integral = 0.0
    sq_error_integral = 0.0
    control_variation = 0.0
    control_energy = 0.0
    last_u = lin_model.u_eq
    warm_du: list[float] | None = None

    for k in range(steps):
        t = k * sim.dt_s
        h1_measured = h1
        h2_measured = h2
        if measurement_noise.enabled:
            h1_measured += measurement_noise.bias_h1 + rng_meas.gauss(0.0, measurement_noise.std_h1)
            h2_measured += measurement_noise.bias_h2 + rng_meas.gauss(0.0, measurement_noise.std_h2)

        x0 = (h1_measured - lin_model.h1_eq, h2_measured - lin_model.h2_eq)
        du_seq = _solve_projected_gradient_mpc(
            x0=x0,
            model=lin_model,
            mpc=mpc_config,
            du_min=du_min,
            du_max=du_max,
            warm_start=warm_du,
        )
        du = du_seq[0] if du_seq else 0.0
        u = _clamp(lin_model.u_eq + du, sim.inflow_min, sim.inflow_max)
        warm_du = du_seq[1:] + [du_seq[-1]] if du_seq else None

        d = _disturbance_value(t, disturbance)

        q12 = c12 * math.sqrt(max(h1 - h2, 0.0))
        q2_base = c2 * math.sqrt(max(h2, 0.0))
        qin = u + d if disturbance.kind == "inflow" else u
        q2 = q2_base + d if disturbance.kind == "outflow" else q2_base

        dh1 = (qin - q12) / max(area1, 1e-6)
        dh2 = (q12 - q2) / max(area2, 1e-6)
        h1 = _clamp(h1 + sim.dt_s * dh1, tank.h_min, tank.h_max)
        h2 = _clamp(h2 + sim.dt_s * dh2, tank.h_min, tank.h_max)

        t_arr.append((k + 1) * sim.dt_s)
        h1_arr.append(h1)
        h2_arr.append(h2)
        h1_measured_arr.append(h1_measured)
        h2_measured_arr.append(h2_measured)
        u_arr.append(u)
        disturbance_arr.append(d)

        error = sim.setpoint - h2_measured
        abs_error_integral += abs(error) * sim.dt_s
        sq_error_integral += (error * error) * sim.dt_s
        control_variation += abs(u - last_u)
        control_energy += (u * u) * sim.dt_s
        last_u = u

    overshoot = max(0.0, max(h2_arr) - sim.setpoint)
    settle_s = _settling_time(t_arr, h2_arr, sim.setpoint)

    return {
        "time_s": t_arr,
        "h1_m": h1_arr,
        "h2_m": h2_arr,
        "h1_measured_m": h1_measured_arr,
        "h2_measured_m": h2_measured_arr,
        "setpoint_m": [sim.setpoint] * len(t_arr),
        "control_u_m3s": [u_arr[0] if u_arr else lin_model.u_eq] + u_arr,
        "disturbance_m3s": [0.0] + disturbance_arr,
        "disturbance_kind": disturbance.kind,
        "metrics": {
            "iae": abs_error_integral,
            "ise": sq_error_integral,
            "overshoot_m": overshoot,
            "settling_time_s": settle_s,
            "final_error_m": sim.setpoint - h2_arr[-1],
            "control_variation": control_variation,
            "control_energy": control_energy,
        },
        "config": {
            "tank": tank.__dict__,
            "sim": sim.__dict__,
            "mpc_config": mpc_config.__dict__,
            "mpc_design": {
                "h1_eq": lin_model.h1_eq,
                "h2_eq": lin_model.h2_eq,
                "u_eq": lin_model.u_eq,
                "du_min": du_min,
                "du_max": du_max,
            },
            "disturbance": disturbance.__dict__,
            "measurement_noise": measurement_noise.__dict__,
            "parameter_uncertainty": parameter_uncertainty.__dict__,
            "realized_plant": {"area1": area1, "area2": area2, "c12": c12, "c2": c2},
        },
    }
