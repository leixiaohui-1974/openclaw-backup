---
name: chs-digital-twin
description: "水网数字孪生技术助手。当用户提到数字孪生、SCADA、OPC UA、边缘计算、传感器选型、水力模型平台、PINN等水网信息化技术时触发。支持从感知到仿真的全链路技术咨询。"
version: 1.0.0
tags: [chs, digital-twin, scada, iot, water-network]
---

# 数字孪生水网助手

支持从传感到仿真的全链路技术咨询。

## 技术栈

### 1. 感知层
- 传感器: 雷达水位计、电磁流量计、水质多参数、视频AI
- 通信: 4G/5G/NB-IoT/LoRa，延迟与带宽选型
- 边缘计算: 数据预处理、异常检测、本地缓存

### 2. 模型层
- 1D水动力: Saint-Venant → ROM (IDZ/Muskingum)
- 2D水动力: 浅水方程 (SWE)
- 数据驱动: LSTM/Transformer时序预测
- 混合模型: PINN (物理信息神经网络)

### 3. 平台层
- SCADA: Modbus TCP/RTU、OPC UA、IEC 61850
- 云-边-端三层协同: 云端全局优化、边缘实时控制、端侧安全联锁
- 三模式切换: 自主模式 → 辅助模式 → 手动模式

### 4. 知识层
- 知识图谱: Neo4j + Cypher
- 规则引擎: 调度规则形式化
- 认知AI: LLM + RAG + 水利知识库

### 5. 安全层
- SCADA网络安全: 入侵检测、安全区域划分
- 数据安全: 加密传输、访问控制
- 韧性设计: 降级策略、应急预案
