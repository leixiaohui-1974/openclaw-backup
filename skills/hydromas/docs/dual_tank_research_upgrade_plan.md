# Dual Tank Research Upgrade Plan

## Phase 1: Linearization & LQR
1. Derive linearized state-space model around nominal operating point.
2. Implement discrete-time LQR controller.
3. Compare with baseline PID.

## Phase 2: MPC
1. Implement finite-horizon quadratic MPC.
2. Add input constraints.
3. Compare performance metrics.

## Phase 3: Adaptive PID
1. Online gain adjustment using simple gradient rule.
2. Compare convergence behavior.

## Comparative Study
Controllers to compare:
- Baseline PID
- Optimized PID
- LQR
- MPC
- Adaptive PID

Metrics:
- IAE
- ISE
- Overshoot
- Control energy
- Settling time

Robustness:
- Monte Carlo with parameter uncertainty
- Measurement noise sensitivity

Report update:
Add section: "Controller Comparative Study"
Include overlay plots and performance table.
