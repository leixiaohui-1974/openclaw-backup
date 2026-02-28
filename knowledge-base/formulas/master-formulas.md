# CHS 主公式库 (Master Formulas)

> 所有 Agent 写作时必须从本库复用 LaTeX，不得自行重写。
> 审稿 Agent 以此为准校对公式正确性。

## 管网水力学

### Saint-Venant 方程（明渠）
$$\frac{\partial A}{\partial t} + \frac{\partial Q}{\partial x} = q_l$$
$$\frac{\partial Q}{\partial t} + \frac{\partial}{\partial x}\left(\frac{Q^2}{A}\right) + gA\frac{\partial h}{\partial x} = gA(S_0 - S_f)$$

### Hazen-Williams 公式
$$h_f = \frac{10.67 \cdot L \cdot Q^{1.852}}{C^{1.852} \cdot D^{4.87}}$$

### 节点连续性方程
$$\sum_{j \in \text{in}(i)} Q_j - \sum_{j \in \text{out}(i)} Q_j = d_i$$

### 能量方程（管段）
$$H_i - H_j = h_{f,ij} + h_{m,ij}$$

## 控制理论

### 状态空间模型
$$\dot{x}(t) = Ax(t) + Bu(t)$$
$$y(t) = Cx(t) + Du(t)$$

### 离散化
$$x(k+1) = A_d x(k) + B_d u(k)$$

### MPC 代价函数
$$J = \sum_{k=0}^{N_p-1} \left[ \|y(k) - y_{\text{ref}}(k)\|_Q^2 + \|\Delta u(k)\|_R^2 \right]$$

### IDZ 传递函数（Litrico & Fromion）
$$G(s) = \frac{a_0 + a_1 s}{1 + b_1 s + b_2 s^2} e^{-\tau s}$$

## 水质模型

### 余氯衰减（一阶）
$$C(t) = C_0 \cdot e^{-k_b t}$$

### 管壁反应
$$\frac{\partial C}{\partial t} + v \frac{\partial C}{\partial x} = -k_b C - \frac{k_w}{r_h} C$$

## 常用符号快查

| 符号 | 含义 | 单位 |
|------|------|------|
| $Q$ | 流量 | m³/s |
| $H$ | 水头 | m |
| $h_f$ | 沿程水头损失 | m |
| $C$ | Hazen-Williams 糙率系数 | — |
| $D$ | 管径 | m |
| $A$ | 过水断面积 | m² |
| $x$ | 状态向量 | — |
| $u$ | 控制输入 | — |
| $y$ | 输出 | — |
