# HEARTBEAT.md - 定期检查任务

## 每次心跳检查（轮换执行，每次选1-2项）

- [ ] **磁盘空间**: `df -h /` — 如果使用率 >85% 则告警，建议 `storage_manager.py archive`
- [ ] **工作区备份**: 检查 `~/.openclaw/workspace/` 是否有未提交的改动，提醒用户用 `备份` 命令
- [ ] **Docker 服务**: `docker ps` 确认 SearXNG 容器在运行
- [ ] **HydroMAS 服务**: `curl -s http://localhost:8000/api/gateway/health` 确认 HydroMAS 运行正常，挂了则重启
- [ ] **HydroMAS全链路巡检+自愈**: `bash ~/.openclaw/workspace/skills/hydromas/scripts/chain_watchdog.sh --notify-target "user:ou_607e1555930b5636c8b88b176b9d3bf2"`（含 Codex 冷却触发机制）
- [ ] **OSS 挂载**: `ls /home/admin/oss-workspace/` 确认 ossfs 挂载正常

## 每日一次（8:00-22:00 之间）

- [ ] **memory 整理**: 检查最近的 memory/YYYY-MM-DD.md，将重要内容归纳到 MEMORY.md
