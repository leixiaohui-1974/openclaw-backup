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

### 1. 飞书文档报告（推荐，一键生成完整报告）

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py report "仿真双容水箱"
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py report "运行四预闭环分析" --role operator
```

自动完成：HydroMAS 仿真 → matplotlib 图表 → 创建飞书文档 → 写入内容+插图 → 授权 → 返回文档链接。

### 2. 自然语言对话（纯文本+图表）

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py chat "仿真双容水箱"
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py chat "运行四预闭环分析"
```

角色自动识别：含"仿真/模拟/水箱"→researcher，含"控制设计/PID"→designer，其余→operator

### 3. 一键仿真+图表

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py sim 300 --title "双容水箱仿真"
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py sim 600 --initial_h 1.0
```

### 4. 直接调用技能

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py skill <技能名> [JSON参数]
```

### 5. 查看可用技能

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py skills [--role operator]
```

### 6. GitHub书稿/API文档 → 知识库 + 飞书

```bash
# 同步 GitHub 目录，按“书”聚合，生成本地知识库并发布飞书文档
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py book-kb sync \
  --github-url "https://github.com/leixiaohui-1974/books/tree/main/books/T2_revision" \
  --user-openid "ou_607e1555930b5636c8b88b176b9d3bf2"

# 只构建知识库，不发布飞书
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py book-kb sync \
  --github-url "https://github.com/leixiaohui-1974/books/tree/main/books/T2_revision" \
  --no-feishu

# 查询知识库（支持提示词检索）
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py book-kb query "四预闭环" --top-k 5

# 用 HydroMAS 底层算法 API 文档测试同一机制
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py book-kb sync-api-docs --no-feishu
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py book-kb query "simulation_run 默认参数" --top-k 5
```

## API 技能直调（32 个端点全参数暴露）

```bash
# 列出所有 API 技能
python3 scripts/hydromas_call.py api list

# 查看某技能的默认参数
python3 scripts/hydromas_call.py api simulation_run --show-defaults

# 用默认参数调用
python3 scripts/hydromas_call.py api simulation_run

# 覆盖部分参数调用
python3 scripts/hydromas_call.py api simulation_run '{"initial_h": 1.0, "duration": 600}'
python3 scripts/hydromas_call.py api control_run '{"controller_type": "MPC", "setpoint": 1.5}'
python3 scripts/hydromas_call.py api evaluation_wnal '{"capabilities": {"sensing": 80}}'
```

覆盖的 API 分组：
- **仿真**: `simulation_run`, `simulation_defaults`
- **控制**: `control_run`, `control_defaults`
- **预测**: `prediction_run`, `prediction_sample`
- **调度**: `scheduling_run`, `dispatch_optimize`
- **评价**: `evaluation_performance`, `evaluation_wnal`
- **设计**: `design_sensitivity`, `design_sizing`
- **数据清洗**: `dataclean_outliers`, `dataclean_interpolate`
- **系统辨识**: `identification_run`, `identification_arx`
- **水平衡**: `water_balance_calc`, `water_balance_anomaly`
- **蒸发**: `evaporation_predict`
- **泄漏**: `leak_detection_detect`, `leak_detection_localize`
- **回用**: `reuse_match`, `reuse_optimize`
- **ODD**: `odd_check`, `odd_check_series`, `odd_mrc_plan`, `odd_specs`
- **报告**: `report_tank_analysis`, `report_daily`
- **图表**: `chart_render`, `chart_simulate_and_chart`, `chart_schematic`

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
| `演化状态` | evolve status | - | EvoMap 演化状态查看 |
| `演化运行` | evolve run | - | 执行单次演化周期 |
| `演化固化` | evolve solidify | - | 固化最近演化结果 |
| `演化启动` | evolve daemon-start | - | 启动持续演化守护进程 |
| `演化停止` | evolve daemon-stop | - | 停止演化守护进程 |

## EvoMap 演化管理

通过 GEP（基因组演化协议）实现系统自动优化，包含：

- **基因库**: 6 个基因（repair/optimize/innovate），含 3 个 HydroMAS 专用基因
- **守护进程**: 持续扫描 OpenClaw 会话日志，自动检测错误信号并生成修复方案
- **PCEC 循环**: 感知(Perceive) → 选择(Choose) → 执行(Execute) → 提交(Commit)
- **安全机制**: 爆炸半径控制、自动回滚、验证步骤、单例锁

```bash
# 查看演化状态
python3 scripts/hydromas_call.py evolve status

# 执行单次演化
python3 scripts/hydromas_call.py evolve run

# 启动/停止守护进程
python3 scripts/hydromas_call.py evolve daemon-start
python3 scripts/hydromas_call.py evolve daemon-stop
```

## 交互语法（角色/案例/参数三层上下文）

### 角色前缀
- `@运维` / `@operator` — 运维助理（四预、调度、日报）
- `@科研` / `@researcher` — 科研助理（仿真、分析、预测）
- `@设计` / `@designer` — 设计助理（控制、优化、敏感性）

### 案例标签
- `#水箱` / `#tank` — 双容水箱案例
- `#氧化铝` / `#alumina` / `#水网` — 氧化铝厂水网案例

### 参数覆盖
- 水箱: `初始水位1.0米`, `时长600秒`, `面积2平方米`, `kp=3.0`, `setpoint=1.5`
- 氧化铝: `日取水量10000`, `目标回用率0.5`

### 元命令
- `帮助` / `help` — 显示完整帮助
- `查看参数` / `当前设置` — 查看当前角色+案例+参数覆盖
- `重置参数` — 清空参数覆盖，恢复默认
- `切换水箱` / `切换氧化铝` — 切换案例

### 优先级
- **角色**: `--role` CLI > `@前缀` > 会话记忆 > 关键词启发式 > 默认 operator
- **案例**: `#标签` > 会话记忆 > 内容启发式 > 默认 alumina
- **参数**: 案例默认 < 技能默认 < 会话持久化 < 当次内联

## 示例

```bash
# 带角色/案例前缀的飞书文档报告
python3 scripts/hydromas_call.py report "@科研 #水箱 仿真初始水位1.0米，时长600秒" --user-openid "ou_xxx"
python3 scripts/hydromas_call.py report "@运维 运行四预闭环" --user-openid "ou_xxx"
python3 scripts/hydromas_call.py report "@设计 #氧化铝 蒸发优化"

# 传统用法（仍然兼容）
python3 scripts/hydromas_call.py report "仿真双容水箱"
python3 scripts/hydromas_call.py report "运行四预闭环分析"
python3 scripts/hydromas_call.py report "设计水箱PID控制器"

# 纯文本对话
python3 scripts/hydromas_call.py chat "@科研 #水箱 运行水箱仿真，面积2平方米"

# 元命令
python3 scripts/hydromas_call.py chat "查看参数" --user-openid "ou_xxx"
python3 scripts/hydromas_call.py chat "重置参数" --user-openid "ou_xxx"

# 直接调用技能
python3 scripts/hydromas_call.py skill forecast '{"horizon": 24}'
python3 scripts/hydromas_call.py skill daily_report '{"date": "2026-02-28"}'
```

## 架构

```
飞书用户 → OpenClaw Agent → hydromas_call.py → HydroMAS FastAPI (port 8000)
                                 │                  ├── /api/gateway/chat    (NL对话)
                                 │                  ├── /api/gateway/skill   (技能调用)
                                 │                  ├── /api/chart/render    (图表生成)
                                 │                  └── /api/gateway/health  (健康检查)
                                 │
                                 ├── report 命令 → 飞书 API (创建文档+写入+插图+授权)
                                 │                     └── 返回文档链接给用户
                                 │
                                 └── evolve 命令 → EvoMap Evolver (GEP 演化引擎)
                                                    ├── 扫描 OpenClaw 会话日志
                                                    ├── 提取信号 → 选择基因 → 生成修复方案
                                                    └── 守护进程持续运行 (daemon mode)
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

## 链路监控与自动修复（HydroMAS + OpenClaw + Feishu）

```bash
# 单次巡检（检测链路、必要时重启 HydroMAS、触发 Codex 审计修复）
bash ~/.openclaw/workspace/skills/hydromas/scripts/chain_watchdog.sh \
  --notify-target "user:ou_607e1555930b5636c8b88b176b9d3bf2" \
  --feishu-ping-target "user:ou_607e1555930b5636c8b88b176b9d3bf2"
```

机制说明：
- HydroMAS 不健康：自动重启 `uvicorn`。
- OpenClaw 网关异常：记录告警并通知。
- 近期会话错误分数超过阈值：按冷却时间触发 `codex_hydromas_audit.sh --fast` 自动修复，避免频繁调用 Codex。

## Codex 架构审计（防空转版）

当用户要求“启动 Codex 审计 hydromas / 自动重构”时，统一使用下面脚本，避免跑错目录或空仓：

```bash
bash ~/.openclaw/workspace/skills/hydromas/scripts/codex_hydromas_audit.sh
```

特性：
- 启动前强制检查：`/home/admin/hydromas` 是否 git 仓库、`core/agents/web` 是否存在
- 强制使用 `codex exec -C /home/admin/hydromas --dangerously-bypass-approvals-and-sandbox`
- 自动记录日志与会话信息到 `/tmp/hydromas-codex-audit/`
- 执行后强校验产物：`ARCHITECTURE_AUDIT.md` 与 `ROADMAP.md`，缺任一即判失败

可选：自定义提示词
```bash
bash ~/.openclaw/workspace/skills/hydromas/scripts/codex_hydromas_audit.sh \
  --prompt "Analyze repo and generate ARCHITECTURE_AUDIT.md + ROADMAP.md, then implement first refactor."
```

可选：快速模式（更快更省 token）
```bash
bash ~/.openclaw/workspace/skills/hydromas/scripts/codex_hydromas_audit.sh --fast
```

可选：进度自动回传飞书（OpenClaw 可见）
```bash
bash ~/.openclaw/workspace/skills/hydromas/scripts/codex_hydromas_audit.sh \
  --notify-channel feishu \
  --notify-target "user:ou_xxx" \
  --progress-interval 20
```
