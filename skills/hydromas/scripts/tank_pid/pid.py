"""PID controller primitives."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PIDController:
    kp: float
    ki: float
    kd: float
    dt: float
    u_min: float
    u_max: float
    integral: float = 0.0
    prev_error: float = 0.0

    def reset(self) -> None:
        self.integral = 0.0
        self.prev_error = 0.0

    def step(self, error: float, base_inflow: float) -> float:
        self.integral += error * self.dt
        derivative = (error - self.prev_error) / self.dt if self.dt > 0 else 0.0
        u_unsat = base_inflow + self.kp * error + self.ki * self.integral + self.kd * derivative
        u = min(self.u_max, max(self.u_min, u_unsat))
        if u != u_unsat and self.ki > 1e-12:
            # Simple anti-windup: unwind integral when actuator saturates.
            self.integral -= (u_unsat - u) / self.ki
        self.prev_error = error
        return u
