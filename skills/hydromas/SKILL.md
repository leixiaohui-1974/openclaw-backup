---
name: hydromas
description: "HydroMAS 水网智能决策平台网关。通过 HTTP API 调用仿真、预测、控制设计、ODD评估、水平衡、泄漏检测、蒸发优化、回用调度、日报生成等 17 项水利技能和 15 个 Agent。支持自然语言对话和直接技能调用。"
version: 1.0.0
tags: [hydromas, water, simulation, control, prediction, odd, dispatch]
---

# HydroMAS — 水网智能决策平台

通过 OpenClaw 在飞书中调用 HydroMAS 的全部能力。

## 服务地址

- **本地**: `http://localhost:8000`
- **网关 API**: `/api/gateway/`
- **健康检查**: `GET /api/gateway/health`

## 快速调用

### 1. 自然语言对话（推荐）

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py chat "你的问题" [--role operator|researcher|designer]
```

**三种角色**：
- `operator`（运维，默认）：四预系统、ODD检查、调度优化、日报、泄漏检测、水平衡
- `researcher`（科研）：仿真建模、数据分析、预测评价、系统辨识、WNAL评估
- `designer`（设计）：控制设计、优化设计、敏感性分析、蒸发优化、回用优化

### 2. 直接调用技能

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py skill <技能名> [JSON参数]
```

### 3. 查看可用技能

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py skills [--role operator]
```

## 飞书触发词 → HydroMAS 技能映射

| 飞书命令 | HydroMAS 技能 | 角色 | 说明 |
|----------|--------------|------|------|
| `水箱仿真` | simulate_tank | researcher | 水箱ODE仿真 |
| `管网仿真` | simulate_network | researcher | WNTR管网仿真 |
| `预测水位` | forecast | operator | 水位预报（四预第一环） |
| `预警` | warning | operator | 分级预警（四预第二环） |
| `预演` | rehearsal | operator | 多方案推演（四预第三环） |
| `预案` | plan | operator | 应急预案（四预第四环） |
| `四预闭环` | four_prediction_loop | operator | 一键运行完整四预 |
| `ODD检查` | odd_assessment | operator | 安全运行设计域检查 |
| `控制设计` | control_system_design | designer | PID/MPC控制器设计 |
| `优化设计` | optimization_design | designer | 水箱参数优化 |
| `数据分析` | data_analysis_predict | researcher | 清洗→特征→预测→评价 |
| `WNAL评估` | full_lifecycle | researcher | 水网自主运行等级评估 |
| `水平衡` | daily_report | operator | 全厂水平衡核算 |
| `泄漏检测` | leak_diagnosis | operator | GNN管网泄漏检测 |
| `蒸发优化` | evap_optimization | designer | 冷却塔/焙烧蒸发优化 |
| `回用优化` | reuse_scheduling | designer | 水回用路径优化 |
| `全局调度` | global_dispatch | operator | 全厂取水配水优化 |
| `日报` | daily_report | operator | 每日运营报告 |

## 示例

```bash
# 运维人员：一键四预
python3 scripts/hydromas_call.py chat "运行四预闭环分析"

# 科研人员：仿真建模
python3 scripts/hydromas_call.py chat "运行水箱仿真，面积2平方米，初始水位0.5米" --role researcher

# 设计人员：控制设计
python3 scripts/hydromas_call.py chat "设计水箱PID控制器" --role designer

# 直接调用技能
python3 scripts/hydromas_call.py skill forecast '{"horizon": 24}'
python3 scripts/hydromas_call.py skill daily_report '{"date": "2026-02-28"}'
```

## 架构

```
飞书用户 → OpenClaw Agent → hydromas_call.py → HydroMAS FastAPI (port 8000)
                                                    ├── /api/gateway/chat    (NL对话)
                                                    ├── /api/gateway/skill   (技能调用)
                                                    ├── /api/gateway/roles   (角色查询)
                                                    ├── /api/gateway/skills  (技能列表)
                                                    └── /api/gateway/health  (健康检查)
```

## 服务管理

```bash
# 启动
cd /home/admin/hydromas && source .venv/bin/activate
nohup python3 -m uvicorn web.app:app --host 0.0.0.0 --port 8000 > /tmp/hydromas.log 2>&1 &

# 检查状态
curl -s http://localhost:8000/api/gateway/health

# 查看日志
tail -f /tmp/hydromas.log

# 停止
pkill -f "uvicorn web.app:app"
```
