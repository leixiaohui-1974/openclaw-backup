"""Report markdown and plotting for advanced dual-tank PID analysis."""

from __future__ import annotations

import math
import os
import time

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .optimization import optimize_pid_multiobjective
from .simulation import (
    DisturbanceConfig,
    DualTankConfig,
    MeasurementNoiseConfig,
    PIDGains,
    ParameterUncertaintyConfig,
    SimulationConfig,
    simulate_dual_tank_pid,
)


def _chart_path(prefix: str, out_dir: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, f"{prefix}_{int(time.time() * 1000)}.png")


def _save_overlay_level_plot(sim_baseline: dict, sim_opt: dict, out_dir: str) -> str:
    p = _chart_path("dual_tank_pid_level_overlay", out_dir)
    plt.figure(figsize=(10, 4.8))
    plt.plot(sim_baseline["time_s"], sim_baseline["h2_m"], label="Baseline PID h2", linewidth=1.8, alpha=0.95)
    plt.plot(sim_opt["time_s"], sim_opt["h2_m"], label="Optimized PID h2", linewidth=2.2)
    plt.plot(sim_opt["time_s"], sim_opt["setpoint_m"], "--", label="Setpoint", linewidth=1.6, color="#666")
    plt.xlabel("Time (s)")
    plt.ylabel("Water Level (m)")
    plt.title("Baseline vs Optimized PID: Water Level")
    plt.grid(alpha=0.25)
    plt.legend()
    plt.tight_layout()
    plt.savefig(p, dpi=150)
    plt.close()
    return p


def _save_overlay_control_plot(sim_baseline: dict, sim_opt: dict, out_dir: str) -> str:
    p = _chart_path("dual_tank_pid_control_overlay", out_dir)
    plt.figure(figsize=(10, 4.8))
    plt.plot(
        sim_baseline["time_s"],
        sim_baseline["control_u_m3s"],
        label="Baseline PID control",
        linewidth=1.8,
        alpha=0.9,
    )
    plt.plot(
        sim_opt["time_s"],
        sim_opt["control_u_m3s"],
        label="Optimized PID control",
        linewidth=2.0,
        color="#d67b00",
    )
    plt.xlabel("Time (s)")
    plt.ylabel("Control Inflow u (m3/s)")
    plt.title("Control Signal Overlay")
    plt.grid(alpha=0.25)
    plt.legend()
    plt.tight_layout()
    plt.savefig(p, dpi=150)
    plt.close()
    return p


def _save_disturbance_plot(sim_out: dict, out_dir: str) -> str:
    p = _chart_path("dual_tank_pid_disturbance", out_dir)
    kind = sim_out.get("disturbance_kind", "outflow")
    plt.figure(figsize=(10, 3.8))
    plt.step(sim_out["time_s"], sim_out["disturbance_m3s"], where="post", color="#b1282b", linewidth=2.0)
    plt.xlabel("Time (s)")
    plt.ylabel("Disturbance (m3/s)")
    plt.title(f"Disturbance Profile ({kind} step)")
    plt.grid(alpha=0.25)
    plt.tight_layout()
    plt.savefig(p, dpi=150)
    plt.close()
    return p


def _save_optimization_plot(opt_out: dict, out_dir: str) -> str:
    p = _chart_path("dual_tank_pid_optimization", out_dir)
    xs = [t["trial"] for t in opt_out["trials"]]
    ys = [t["score"] for t in opt_out["trials"]]
    best = opt_out["best"]
    plt.figure(figsize=(10, 4.0))
    plt.plot(xs, ys, color="#1f6feb", linewidth=1.2)
    plt.scatter([best["trial"]], [best["score"]], color="#2da44e", zorder=3, label="Selected best")
    plt.xlabel("Trial")
    plt.ylabel("Composite Score (lower is better)")
    method = opt_out.get("method", "unknown")
    plt.title(f"PID Optimization Process ({method})")
    plt.grid(alpha=0.25)
    plt.legend()
    plt.tight_layout()
    plt.savefig(p, dpi=150)
    plt.close()
    return p


def _save_pareto_plot(opt_out: dict, out_dir: str) -> str:
    p = _chart_path("dual_tank_pid_pareto", out_dir)
    trials = opt_out.get("trials", [])
    pareto = opt_out.get("pareto_front", [])
    x_all = [t["metrics"].get("iae", 0.0) for t in trials]
    y_all = [t["metrics"].get("overshoot_m", 0.0) for t in trials]
    e_all = [t["metrics"].get("control_energy", 0.0) for t in trials]
    x_pf = [t["metrics"].get("iae", 0.0) for t in pareto]
    y_pf = [t["metrics"].get("overshoot_m", 0.0) for t in pareto]
    e_pf = [t["metrics"].get("control_energy", 0.0) for t in pareto]

    plt.figure(figsize=(10, 4.8))
    plt.scatter(x_all, y_all, c=e_all, cmap="Blues", alpha=0.35, s=30, label="Candidates")
    if pareto:
        plt.scatter(x_pf, y_pf, c=e_pf, cmap="autumn", edgecolors="black", s=60, label="Pareto front")
    plt.xlabel("IAE")
    plt.ylabel("Overshoot (m)")
    plt.title("Multi-objective Pareto Tradeoff (color=control energy)")
    plt.grid(alpha=0.25)
    plt.legend()
    plt.tight_layout()
    plt.savefig(p, dpi=150)
    plt.close()
    return p


def _normalize_for_radar(values: list[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if math.isclose(lo, hi):
        return [1.0 for _ in values]
    return [(hi - v) / (hi - lo) for v in values]


def _save_radar_plot(controllers: list[dict], out_dir: str) -> str:
    p = _chart_path("dual_tank_pid_radar", out_dir)
    if not controllers:
        fig = plt.figure(figsize=(6, 6))
        fig.text(0.5, 0.5, "No controllers", ha="center", va="center")
        plt.savefig(p, dpi=150)
        plt.close()
        return p

    labels = ["IAE", "Overshoot", "Control energy", "Settling time"]
    iae_vals = [c["metrics"].get("iae", 0.0) for c in controllers]
    over_vals = [c["metrics"].get("overshoot_m", 0.0) for c in controllers]
    energy_vals = [c["metrics"].get("control_energy", 0.0) for c in controllers]
    settle_vals = [
        float(c["metrics"].get("settling_time_s") if c["metrics"].get("settling_time_s") is not None else 1e9)
        for c in controllers
    ]

    normalized = [
        _normalize_for_radar(iae_vals),
        _normalize_for_radar(over_vals),
        _normalize_for_radar(energy_vals),
        _normalize_for_radar(settle_vals),
    ]
    n = len(labels)
    angles = [2 * math.pi * i / n for i in range(n)]
    angles += [angles[0]]

    fig = plt.figure(figsize=(6.8, 6.8))
    ax = fig.add_subplot(111, polar=True)
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(labels)
    ax.set_yticklabels([])
    ax.set_ylim(0, 1.0)

    for idx, c in enumerate(controllers):
        vals = [normalized[i][idx] for i in range(n)]
        vals += [vals[0]]
        name = c.get("name", f"C{idx + 1}")
        ax.plot(angles, vals, linewidth=1.8, label=name)
        ax.fill(angles, vals, alpha=0.08)

    ax.set_title("Controller Performance Radar (higher is better)")
    ax.legend(loc="upper right", bbox_to_anchor=(1.25, 1.1))
    plt.tight_layout()
    plt.savefig(p, dpi=150)
    plt.close()
    return p


def _render_top_table(opt_out: dict) -> str:
    lines = [
        "| Rank | Kp | Ki | Kd | Score | IAE | Overshoot(m) | CtrlEnergy | Settling(s) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for i, item in enumerate(opt_out["top"], 1):
        m = item["metrics"]
        settling = m.get("settling_time_s")
        settle_s = f"{settling:.1f}" if isinstance(settling, (int, float)) else "N/A"
        lines.append(
            f"| {i} | {item['kp']:.4f} | {item['ki']:.4f} | {item['kd']:.4f} | "
            f"{item['score']:.4f} | {m.get('iae', 0.0):.4f} | {m.get('overshoot_m', 0.0):.4f} | "
            f"{m.get('control_energy', 0.0):.4f} | {settle_s} |"
        )
    return "\n".join(lines)


def _run_robustness_sweep(
    tank: DualTankConfig,
    sim: SimulationConfig,
    disturbance: DisturbanceConfig,
    gains: PIDGains,
    noise_cfg: MeasurementNoiseConfig | None,
    uncertainty_cfg: ParameterUncertaintyConfig | None,
    samples: int,
) -> dict:
    if samples <= 0:
        return {"samples": 0, "iae_mean": 0.0, "overshoot_mean": 0.0, "control_energy_mean": 0.0}

    iae_vals = []
    over_vals = []
    energy_vals = []
    settle_vals = []
    for i in range(samples):
        n_cfg = noise_cfg
        u_cfg = uncertainty_cfg
        if n_cfg:
            n_cfg = MeasurementNoiseConfig(**{**n_cfg.__dict__, "seed": n_cfg.seed + i})
        if u_cfg:
            u_cfg = ParameterUncertaintyConfig(**{**u_cfg.__dict__, "seed": u_cfg.seed + i})
        out = simulate_dual_tank_pid(
            tank=tank,
            sim=sim,
            gains=gains,
            disturbance=disturbance,
            measurement_noise=n_cfg,
            parameter_uncertainty=u_cfg,
        )
        m = out["metrics"]
        iae_vals.append(m.get("iae", 0.0))
        over_vals.append(m.get("overshoot_m", 0.0))
        energy_vals.append(m.get("control_energy", 0.0))
        settle_vals.append(m.get("settling_time_s", None))

    valid_settle = [x for x in settle_vals if isinstance(x, (int, float))]
    return {
        "samples": samples,
        "iae_mean": sum(iae_vals) / len(iae_vals),
        "iae_max": max(iae_vals),
        "overshoot_mean": sum(over_vals) / len(over_vals),
        "overshoot_max": max(over_vals),
        "control_energy_mean": sum(energy_vals) / len(energy_vals),
        "settling_mean": (sum(valid_settle) / len(valid_settle)) if valid_settle else None,
    }


def generate_pid_report_artifacts(
    tank: DualTankConfig,
    sim: SimulationConfig,
    seed_gains: PIDGains,
    disturbance: DisturbanceConfig,
    out_dir: str,
    optimizer_method: str = "random_refine",
    noise_cfg: MeasurementNoiseConfig | None = None,
    uncertainty_cfg: ParameterUncertaintyConfig | None = None,
    robust_samples: int = 8,
) -> dict:
    sim_baseline = simulate_dual_tank_pid(
        tank=tank,
        sim=sim,
        gains=seed_gains,
        disturbance=disturbance,
        measurement_noise=noise_cfg,
        parameter_uncertainty=uncertainty_cfg,
    )
    opt_out = optimize_pid_multiobjective(
        tank=tank,
        sim=sim,
        disturbance=disturbance,
        seed_gains=seed_gains,
        top_k=5,
        method=optimizer_method,
        measurement_noise=noise_cfg,
        parameter_uncertainty=uncertainty_cfg,
    )
    best = opt_out["best"]
    best_gains = PIDGains(kp=best["kp"], ki=best["ki"], kd=best["kd"])
    sim_best = simulate_dual_tank_pid(
        tank=tank,
        sim=sim,
        gains=best_gains,
        disturbance=disturbance,
        measurement_noise=noise_cfg,
        parameter_uncertainty=uncertainty_cfg,
    )

    top_for_radar = [
        {
            "name": "Baseline",
            "metrics": sim_baseline["metrics"],
        }
    ]
    for i, cand in enumerate(opt_out.get("top", [])[:3], 1):
        top_for_radar.append({"name": f"Opt-{i}", "metrics": cand["metrics"]})

    robustness = _run_robustness_sweep(
        tank=tank,
        sim=sim,
        disturbance=disturbance,
        gains=best_gains,
        noise_cfg=noise_cfg,
        uncertainty_cfg=uncertainty_cfg,
        samples=max(0, robust_samples),
    )

    return {
        "optimization": opt_out,
        "selected_gains": best_gains,
        "baseline_gains": seed_gains,
        "simulation_best": sim_best,
        "simulation_baseline": sim_baseline,
        "robustness": robustness,
        "plots": {
            "water_level_vs_setpoint": _save_overlay_level_plot(sim_baseline, sim_best, out_dir),
            "control_signal": _save_overlay_control_plot(sim_baseline, sim_best, out_dir),
            "disturbance_profile": _save_disturbance_plot(sim_best, out_dir),
            "optimization_process": _save_optimization_plot(opt_out, out_dir),
            "pareto_tradeoff": _save_pareto_plot(opt_out, out_dir),
            "performance_radar": _save_radar_plot(top_for_radar, out_dir),
        },
    }


def build_pid_report_markdown(pid_artifacts: dict) -> str:
    opt_out = pid_artifacts["optimization"]
    gains = pid_artifacts["selected_gains"]
    seed_gains = pid_artifacts.get("baseline_gains", PIDGains())
    sim_best = pid_artifacts["simulation_best"]
    sim_base = pid_artifacts["simulation_baseline"]
    m = sim_best["metrics"]
    mb = sim_base["metrics"]
    dcfg = sim_best["config"]["disturbance"]
    ncfg = sim_best["config"].get("measurement_noise", {})
    ucfg = sim_best["config"].get("parameter_uncertainty", {})
    robust = pid_artifacts.get("robustness", {})

    lines = [
        "## 八、双容水箱 PID 扰动抑制与参数优化（高级版）",
        "",
        "### 8.1 扰动与鲁棒仿真设定",
        f"- 扰动类型: `{dcfg.get('kind', 'outflow')}`",
        f"- 阶跃开始时刻: `{dcfg.get('start_s', 0):.1f}s`",
        f"- 阶跃幅值: `{dcfg.get('magnitude', 0):.6f} m3/s`",
        f"- 测量噪声: `enabled={ncfg.get('enabled', False)}, std_h2={ncfg.get('std_h2', 0):.5f} m`",
        "- 参数不确定性: "
        f"`enabled={ucfg.get('enabled', False)}, rel_area1={ucfg.get('rel_area1', 0):.2%}, "
        f"rel_area2={ucfg.get('rel_area2', 0):.2%}, rel_c12={ucfg.get('rel_c12', 0):.2%}, "
        f"rel_c2={ucfg.get('rel_c2', 0):.2%}`",
        "",
        "### 8.2 多目标优化与替代优化器",
        f"- 优化方法: `{opt_out.get('method', 'unknown')}`",
        f"- 搜索规模: `{len(opt_out.get('trials', []))} 组参数`",
        f"- Pareto 非支配解数量: `{len(opt_out.get('pareto_front', []))}`",
        f"- 基线参数: `Kp={seed_gains.kp:.4f}, Ki={seed_gains.ki:.4f}, Kd={seed_gains.kd:.4f}`",
        f"- 选中参数: `Kp={gains.kp:.4f}, Ki={gains.ki:.4f}, Kd={gains.kd:.4f}`",
        "",
        _render_top_table(opt_out),
        "",
        "### 8.3 基线 PID vs 优化 PID 对比",
        f"- IAE: `{mb.get('iae', 0.0):.4f}` → `{m.get('iae', 0.0):.4f}`",
        f"- 超调量: `{mb.get('overshoot_m', 0.0):.4f} m` → `{m.get('overshoot_m', 0.0):.4f} m`",
        f"- 控制能量: `{mb.get('control_energy', 0.0):.4f}` → `{m.get('control_energy', 0.0):.4f}`",
        f"- 稳定时间: `{mb.get('settling_time_s', 'N/A')}` s → `{m.get('settling_time_s', 'N/A')}` s",
        "",
        "### 8.4 多目标 trade-off 讨论",
        "- Pareto 前沿展示了 IAE、超调、控制能量之间的不可同时最优关系。",
        "- 选中参数偏向于在低超调和可接受控制能量之间折中，同时保持误差积分较低。",
        "",
        "### 8.5 鲁棒性分析",
        f"- Monte Carlo 样本数: `{robust.get('samples', 0)}`",
        f"- 平均 IAE: `{robust.get('iae_mean', 0.0):.4f}`，最坏 IAE: `{robust.get('iae_max', 0.0):.4f}`",
        f"- 平均超调: `{robust.get('overshoot_mean', 0.0):.4f} m`，最坏超调: `{robust.get('overshoot_max', 0.0):.4f} m`",
        f"- 平均控制能量: `{robust.get('control_energy_mean', 0.0):.4f}`",
        "",
        "### 8.6 水位-设定值叠加对比图",
        "（见下方插图）",
        "",
        "### 8.7 控制信号叠加图",
        "（见下方插图）",
        "",
        "### 8.8 扰动曲线图",
        "（见下方插图）",
        "",
        "### 8.9 优化过程图",
        "（见下方插图）",
        "",
        "### 8.10 Pareto trade-off 图",
        "（见下方插图）",
        "",
        "### 8.11 性能雷达图",
        "（见下方插图）",
        "",
    ]
    return "\n".join(lines)
