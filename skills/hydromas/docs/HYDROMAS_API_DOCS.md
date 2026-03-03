# HydroMAS API 文档知识库

> 来源: hydromas_call.py::_API_SKILLS 自动抽取

## 总览

| API | 方法 | 路径 | 说明 |
|-----|------|------|------|
| `chart_render` | `POST` | `/api/chart/render` | 渲染过程线图 Render Chart |
| `chart_schematic` | `POST` | `/api/chart/schematic` | 水箱示意图 Tank Schematic |
| `chart_simulate_and_chart` | `POST` | `/api/chart/simulate-and-chart` | 仿真+图表一键生成 Simulate & Chart |
| `control_defaults` | `GET` | `/api/control/defaults` | 获取控制器默认参数 Get Control Defaults |
| `control_run` | `POST` | `/api/control/run` | 控制器仿真 Control Simulation (PID/MPC) |
| `dataclean_interpolate` | `POST` | `/api/dataclean/interpolate` | 缺失值插值 Gap Interpolation |
| `dataclean_outliers` | `POST` | `/api/dataclean/outliers` | 异常值检测 Outlier Detection |
| `design_sensitivity` | `POST` | `/api/design/sensitivity` | 参数敏感性分析 Sensitivity Analysis |
| `design_sizing` | `POST` | `/api/design/sizing` | 水箱容量设计 Tank Sizing |
| `dispatch_optimize` | `POST` | `/api/dispatch/optimize` | 全局调度优化 Global Dispatch Optimization |
| `evaluation_performance` | `POST` | `/api/evaluation/performance` | 性能评价 Performance Evaluation |
| `evaluation_wnal` | `POST` | `/api/evaluation/wnal` | WNAL水网自主等级评估 WNAL Assessment |
| `evaporation_predict` | `POST` | `/api/evaporation/predict` | 蒸发量预测 Evaporation Prediction |
| `identification_arx` | `POST` | `/api/identification/arx` | ARX模型辨识 ARX Model Identification |
| `identification_run` | `POST` | `/api/identification/run` | 系统辨识 System Identification |
| `leak_detection_detect` | `POST` | `/api/leak-detection/detect` | 泄漏检测 Leak Detection |
| `leak_detection_localize` | `POST` | `/api/leak-detection/localize` | 泄漏定位 Leak Localization |
| `odd_check` | `POST` | `/api/odd/check` | ODD安全边界检查 ODD Safety Check |
| `odd_check_series` | `POST` | `/api/odd/check-series` | ODD时序安全检查 ODD Time-Series Check |
| `odd_mrc_plan` | `POST` | `/api/odd/mrc-plan` | 最小风险方案 MRC Plan |
| `odd_specs` | `GET` | `/api/odd/specs` | 获取ODD规格 Get ODD Specifications |
| `prediction_run` | `POST` | `/api/prediction/run` | 水位预测 Water Level Prediction |
| `prediction_sample` | `GET` | `/api/prediction/sample-data` | 获取示例预测数据 Get Sample Prediction Data |
| `report_daily` | `POST` | `/api/report/daily` | 日运营报告 Daily Operations Report |
| `report_tank_analysis` | `POST` | `/api/report/tank-analysis` | 水箱综合分析报告 Tank Analysis Report |
| `reuse_match` | `POST` | `/api/reuse/match` | 回用水源匹配 Reuse Water Source Matching |
| `reuse_optimize` | `POST` | `/api/reuse/optimize` | 回用方案优化 Reuse Scheduling Optimization |
| `scheduling_run` | `POST` | `/api/scheduling/run` | 调度优化 Scheduling Optimization |
| `simulation_defaults` | `GET` | `/api/simulation/defaults` | 获取仿真默认参数 Get Simulation Defaults |
| `simulation_run` | `POST` | `/api/simulation/run` | 水箱仿真 Tank Simulation |
| `water_balance_anomaly` | `POST` | `/api/water-balance/anomaly` | 水平衡异常检测 Water Balance Anomaly Detection |
| `water_balance_calc` | `POST` | `/api/water-balance/calc` | 水平衡计算 Water Balance Calculation |

---

## chart_render

- 说明: 渲染过程线图 Render Chart
- 端点: `POST /api/chart/render`

### 默认参数

```json
{
  "time": [
    0,
    1,
    2,
    3,
    4,
    5,
    6,
    7,
    8,
    9,
    10,
    11,
    12,
    13,
    14,
    15,
    16,
    17,
    18,
    19,
    20,
    21,
    22,
    23,
    24,
    25,
    26,
    27,
    28,
    29,
    30,
    31,
    32,
    33,
    34,
    35,
    36,
    37,
    38,
    39,
    40,
    41,
    42,
    43,
    44,
    45,
    46,
    47,
    48,
    49,
    50,
    51,
    52,
    53,
    54,
    55,
    56,
    57,
    58,
    59,
    60,
    61,
    62,
    63,
    64,
    65,
    66,
    67,
    68,
    69,
    70,
    71,
    72,
    73,
    74,
    75,
    76,
    77,
    78,
    79,
    80,
    81,
    82,
    83,
    84,
    85,
    86,
    87,
    88,
    89,
    90,
    91,
    92,
    93,
    94,
    95,
    96,
    97,
    98,
    99,
    100,
    101,
    102,
    103,
    104,
    105,
    106,
    107,
    108,
    109,
    110,
    111,
    112,
    113,
    114,
    115,
    116,
    117,
    118,
    119,
    120,
    121,
    122,
    123,
    124,
    125,
    126,
    127,
    128,
    129,
    130,
    131,
    132,
    133,
    134,
    135,
    136,
    137,
    138,
    139,
    140,
    141,
    142,
    143,
    144,
    145,
    146,
    147,
    148,
    149,
    150,
    151,
    152,
    153,
    154,
    155,
    156,
    157,
    158,
    159,
    160,
    161,
    162,
    163,
    164,
    165,
    166,
    167,
    168,
    169,
    170,
    171,
    172,
    173,
    174,
    175,
    176,
    177,
    178,
    179,
    180,
    181,
    182,
    183,
    184,
    185,
    186,
    187,
    188,
    189,
    190,
    191,
    192,
    193,
    194,
    195,
    196,
    197,
    198,
    199,
    200,
    201,
    202,
    203,
    204,
    205,
    206,
    207,
    208,
    209,
    210,
    211,
    212,
    213,
    214,
    215,
    216,
    217,
    218,
    219,
    220,
    221,
    222,
    223,
    224,
    225,
    226,
    227,
    228,
    229,
    230,
    231,
    232,
    233,
    234,
    235,
    236,
    237,
    238,
    239,
    240,
    241,
    242,
    243,
    244,
    245,
    246,
    247,
    248,
    249,
    250,
    251,
    252,
    253,
    254,
    255,
    256,
    257,
    258,
    259,
    260,
    261,
    262,
    263,
    264,
    265,
    266,
    267,
    268,
    269,
    270,
    271,
    272,
    273,
    274,
    275,
    276,
    277,
    278,
    279,
    280,
    281,
    282,
    283,
    284,
    285,
    286,
    287,
    288,
    289,
    290,
    291,
    292,
    293,
    294,
    295,
    296,
    297,
    298,
    299,
    300
  ],
  "water_level": [
    0.5,
    0.495,
    0.49005,
    0.4851495,
    0.480298005,
    0.47549502494999996,
    0.4707400747005,
    0.46603267395349496,
    0.46137234721396003,
    0.4567586237418204,
    0.4521910375044022,
    0.4476691271293582,
    0.4431924358580646,
    0.4387605114994839,
    0.4343729063844891,
    0.4300291773206442,
    0.42572888554743776,
    0.4214715966919634,
    0.41725688072504374,
    0.4130843119177933,
    0.4089534687986154,
    0.4048639341106292,
    0.40081529476952293,
    0.3968071418218277,
    0.3928390704036094,
    0.3889106796995733,
    0.38502157290257755,
    0.3811713571735518,
    0.3773596436018163,
    0.3735860471657981,
    0.3698501866941401,
    0.36615168482719873,
    0.3624901679789267,
    0.35886526629913745,
    0.35527661363614604,
    0.3517238474997846,
    0.34820660902478673,
    0.34472454293453886,
    0.3412772975051935,
    0.33786452453014154,
    0.33448587928484014,
    0.33114102049199173,
    0.3278296102870718,
    0.3245513141842011,
    0.32130580104235906,
    0.31809274303193547,
    0.31491181560161613,
    0.3117626974456,
    0.308645070471144,
    0.3055586197664325,
    0.3025030335687682,
    0.2994780032330805,
    0.2964832232007497,
    0.2935183909687422,
    0.29058320705905477,
    0.28767737498846424,
    0.2848006012385796,
    0.28195259522619376,
    0.27913306927393183,
    0.27634173858119254,
    0.2735783211953806,
    0.2708425379834268,
    0.2681341126035925,
    0.2654527714775566,
    0.262798243762781,
    0.2601702613251532,
    0.25756855871190165,
    0.25499287312478264,
    0.2524429443935348,
    0.24991851494959946,
    0.24741932980010348,
    0.24494513650210245,
    0.24249568513708142,
    0.2400707282857106,
    0.23767002100285348,
    0.23529332079282494,
    0.23294038758489669,
    0.23061098370904773,
    0.22830487387195725,
    0.22602182513323768,
    0.2237616068819053,
    0.22152399081308624,
    0.21930875090495539,
    0.21711566339590582,
    0.21494450676194676,
    0.2127950616943273,
    0.210667111077384,
    0.20856043996661017,
    0.20647483556694407,
    0.20441008721127463,
    0.2023659863391619,
    0.20034232647577027,
    0.19833890321101255,
    0.19635551417890243,
    0.1943919590371134,
    0.19244803944674227,
    0.19052355905227483,
    0.18861832346175209,
    0.18673214022713458,
    0.18486481882486322,
    0.1830161706366146,
    0.18118600893024844,
    0.17937414884094596,
    0.1775804073525365,
    0.17580460327901112,
    0.174046557246221,
    0.1723060916737588,
    0.17058303075702122,
    0.168877200449451,
    0.1671884284449565,
    0.16551654416050693,
    0.16386137871890186,
    0.16222276493171284,
    0.1606005372823957,
    0.15899453190957175,
    0.15740458659047601,
    0.15583054072457125,
    0.15427223531732553,
    0.1527295129641523,
    0.15120221783451077,
    0.14969019565616565,
    0.148193293699604,
    0.14671136076260796,
    0.14524424715498188,
    0.14379180468343206,
    0.14235388663659773,
    0.14093034777023175,
    0.13952104429252943,
    0.13812583384960414,
    0.1367445755111081,
    0.13537712975599703,
    0.13402335845843705,
    0.13268312487385267,
    0.13135629362511414,
    0.13004273068886302,
    0.12874230338197437,
    0.12745488034815464,
    0.1261803315446731,
    0.12491852822922635,
    0.12366934294693409,
    0.12243264951746474,
    0.1212083230222901,
    0.1199962397920672,
    0.11879627739414651,
    0.11760831462020506,
    0.116432231474003,
    0.11526790915926297,
    0.11411523006767034,
    0.11297407776699364,
    0.1118443369893237,
    0.11072589361943046,
    0.10961863468323615,
    0.10852244833640379,
    0.10743722385303975,
    0.10636285161450935,
    0.10529922309836426,
    0.10424623086738062,
    0.1032037685587068,
    0.10217173087311975,
    0.10115001356438855,
    0.10013851342874465,
    0.09913712829445721,
    0.09814575701151264,
    0.09716429944139751,
    0.09619265644698353,
    0.0952307298825137,
    0.09427842258368856,
    0.09333563835785168,
    0.09240228197427315,
    0.09147825915453042,
    0.09056347656298512,
    0.08965784179735527,
    0.08876126337938171,
    0.0878736507455879,
    0.086994914238132,
    0.0861249650957507,
    0.08526371544479318,
    0.08441107829034525,
    0.0835669675074418,
    0.08273129783236738,
    0.08190398485404371,
    0.08108494500550327,
    0.08027409555544823,
    0.07947135459989375,
    0.07867664105389481,
    0.07788987464335587,
    0.0771109758969223,
    0.07633986613795309,
    0.07557646747657355,
    0.07482070280180782,
    0.07407249577378973,
    0.07333177081605184,
    0.07259845310789131,
    0.0718724685768124,
    0.07115374389104429,
    0.07044220645213384,
    0.0697377843876125,
    0.06904040654373637,
    0.068350002478299,
    0.06766650245351602,
    0.06698983742898086,
    0.06631993905469105,
    0.06565673966414413,
    0.0650001722675027,
    0.06435017054482767,
    0.0637066688393794,
    0.06306960215098559,
    0.06243890612947574,
    0.06181451706818098,
    0.06119637189749917,
    0.060584408178524174,
    0.059978564096738934,
    0.059378778455771546,
    0.05878499067121383,
    0.05819714076450169,
    0.05761516935685667,
    0.0570390176632881,
    0.05646862748665522,
    0.05590394121178867,
    0.05534490179967078,
    0.05479145278167408,
    0.05424353825385733,
    0.05370110287131876,
    0.05316409184260557,
    0.052632450924179515,
    0.05210612641493772,
    0.051585065150788346,
    0.05106921449928046,
    0.050558522354287656,
    0.050052937130744775,
    0.04955240775943733,
    0.04905688368184295,
    0.04856631484502452,
    0.04808065169657428,
    0.04759984517960854,
    0.04712384672781245,
    0.04665260826053433,
    0.04618608217792898,
    0.04572422135614969,
    0.0452669791425882,
    0.04481430935116231,
    0.04436616625765069,
    0.04392250459507418,
    0.04348327954912344,
    0.0430484467536322,
    0.04261796228609588,
    0.04219178266323492,
    0.041769864836602576,
    0.04135216618823655,
    0.04093864452635418,
    0.04052925808109064,
    0.04012396550027973,
    0.03972272584527693,
    0.039325498586824166,
    0.03893224360095592,
    0.03854292116494636,
    0.0381574919532969,
    0.03777591703376393,
    0.03739815786342629,
    0.03702417628479203,
    0.036653934521944105,
    0.03628739517672466,
    0.035924521224957415,
    0.03556527601270784,
    0.035209623252580764,
    0.03485752702005496,
    0.034508951749854404,
    0.03416386223235586,
    0.0338222236100323,
    0.03348400137393198,
    0.03314916136019266,
    0.032817669746590734,
    0.032489493049124823,
    0.03216459811863358,
    0.03184295213744724,
    0.03152452261607277,
    0.03120927738991204,
    0.03089718461601292,
    0.03058821276985279,
    0.030282330642154263,
    0.02997950733573272,
    0.029679712262375393,
    0.029382915139751636,
    0.02908908598835412,
    0.02879819512847058,
    0.028510213177185873,
    0.028225111045414013,
    0.027942859934959874,
    0.027663431335610274,
    0.02738679702225417,
    0.02711292905203163,
    0.026841799761511315,
    0.0265733817638962,
    0.02630764794625724,
    0.026044571466794664,
    0.02578412575212672,
    0.02552628449460545,
    0.025271021649659397,
    0.025018311433162802,
    0.024768128318831174,
    0.02452044703564286
  ],
  "outflow": [],
  "inflow": [],
  "title": "HydroMAS Chart"
}
```

### 命令行调用示例

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api chart_render
```

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api chart_render '{"time": [0], "water_level": [0.5]}'
```

---

## chart_schematic

- 说明: 水箱示意图 Tank Schematic
- 端点: `POST /api/chart/schematic`

### 默认参数

```json
{
  "tank_area_m2": 1.0,
  "initial_h_m": 0.5,
  "outlet_area_m2": 0.01,
  "discharge_coeff": 0.6,
  "q_in_m3s": 0.01,
  "h_max_m": 2.0
}
```

### 命令行调用示例

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api chart_schematic
```

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api chart_schematic '{"tank_area_m2": 1.1, "initial_h_m": 0.55}'
```

---

## chart_simulate_and_chart

- 说明: 仿真+图表一键生成 Simulate & Chart
- 端点: `POST /api/chart/simulate-and-chart`

### 默认参数

```json
{
  "duration": 300,
  "initial_h": 0.5,
  "title": "水箱仿真结果"
}
```

### 命令行调用示例

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api chart_simulate_and_chart
```

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api chart_simulate_and_chart '{"duration": 301, "initial_h": 0.55}'
```

---

## control_defaults

- 说明: 获取控制器默认参数 Get Control Defaults
- 端点: `GET /api/control/defaults`

### 默认参数

```json
{}
```

### 命令行调用示例

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api control_defaults
```

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api control_defaults '{}'
```

---

## control_run

- 说明: 控制器仿真 Control Simulation (PID/MPC)
- 端点: `POST /api/control/run`

### 默认参数

```json
{
  "setpoint": 1.0,
  "controller_type": "PID",
  "duration": 300,
  "dt": 1.0,
  "initial_h": 0.5,
  "params": {
    "kp": 2.0,
    "ki": 0.1,
    "kd": 0.5
  },
  "tank_params": {
    "area": 1.0,
    "cd": 0.6,
    "outlet_area": 0.01,
    "h_max": 2.0
  }
}
```

### 命令行调用示例

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api control_run
```

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api control_run '{"setpoint": 1.1, "controller_type": "PID_override"}'
```

---

## dataclean_interpolate

- 说明: 缺失值插值 Gap Interpolation
- 端点: `POST /api/dataclean/interpolate`

### 默认参数

```json
{
  "data": [
    1.0,
    0.98,
    null,
    0.93,
    null,
    null,
    0.85,
    0.83,
    0.8,
    0.78
  ],
  "method": "linear"
}
```

### 命令行调用示例

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api dataclean_interpolate
```

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api dataclean_interpolate '{"data": [1.0], "method": "linear_override"}'
```

---

## dataclean_outliers

- 说明: 异常值检测 Outlier Detection
- 端点: `POST /api/dataclean/outliers`

### 默认参数

```json
{
  "data": [
    1.0,
    0.98,
    0.95,
    5.0,
    0.9,
    0.88,
    0.85,
    0.83,
    0.8,
    0.78
  ],
  "method": "3sigma",
  "threshold": 3.0
}
```

### 命令行调用示例

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api dataclean_outliers
```

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api dataclean_outliers '{"data": [1.0], "method": "3sigma_override"}'
```

---

## design_sensitivity

- 说明: 参数敏感性分析 Sensitivity Analysis
- 端点: `POST /api/design/sensitivity`

### 默认参数

```json
{
  "base_params": {
    "area": 1.0,
    "cd": 0.6,
    "outlet_area": 0.01,
    "q_in": 0.01
  },
  "param_ranges": {
    "area": [
      0.5,
      2.0
    ],
    "cd": [
      0.4,
      0.8
    ],
    "outlet_area": [
      0.005,
      0.02
    ],
    "q_in": [
      0.005,
      0.02
    ]
  },
  "method": "OAT",
  "n_levels": 10
}
```

### 命令行调用示例

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api design_sensitivity
```

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api design_sensitivity '{"base_params": {"area": 1.0}, "param_ranges": {"area": [0.5, 2.0]}}'
```

---

## design_sizing

- 说明: 水箱容量设计 Tank Sizing
- 端点: `POST /api/design/sizing`

### 默认参数

```json
{
  "demand_peak": 0.03,
  "duration_hours": 4.0,
  "safety_factor": 1.2
}
```

### 命令行调用示例

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api design_sizing
```

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api design_sizing '{"demand_peak": 0.033, "duration_hours": 4.4}'
```

---

## dispatch_optimize

- 说明: 全局调度优化 Global Dispatch Optimization
- 端点: `POST /api/dispatch/optimize`

### 默认参数

```json
{
  "demand_forecast": {
    "total": 10400,
    "peak": 500,
    "duration_h": 24
  },
  "supply_config": {
    "wujiang": {
      "capacity": 7800
    },
    "flood_channel": {
      "capacity": 2600
    }
  },
  "reuse_config": {
    "capacity": 2400,
    "rate": 0.36
  },
  "method": "lp"
}
```

### 命令行调用示例

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api dispatch_optimize
```

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api dispatch_optimize '{"demand_forecast": {"total": 10400}, "supply_config": {"wujiang": {"capacity": 7800}}}'
```

---

## evaluation_performance

- 说明: 性能评价 Performance Evaluation
- 端点: `POST /api/evaluation/performance`

### 默认参数

```json
{
  "observed": [
    1.0,
    0.95,
    0.9,
    0.85,
    0.8,
    0.78,
    0.76,
    0.75,
    0.74,
    0.74
  ],
  "predicted": [
    1.0,
    0.96,
    0.91,
    0.86,
    0.81,
    0.79,
    0.77,
    0.76,
    0.75,
    0.74
  ],
  "metrics": [
    "RMSE",
    "MAE",
    "NSE"
  ],
  "time_series": null,
  "setpoint": null
}
```

### 命令行调用示例

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api evaluation_performance
```

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api evaluation_performance '{"observed": [1.0], "predicted": [1.0]}'
```

---

## evaluation_wnal

- 说明: WNAL水网自主等级评估 WNAL Assessment
- 端点: `POST /api/evaluation/wnal`

### 默认参数

```json
{
  "capabilities": {
    "sensing": 65,
    "communication": 70,
    "modeling": 55,
    "prediction": 60,
    "control": 50,
    "odd_monitoring": 45,
    "decision_support": 40
  }
}
```

### 命令行调用示例

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api evaluation_wnal
```

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api evaluation_wnal '{"capabilities": {"sensing": 65}}'
```

---

## evaporation_predict

- 说明: 蒸发量预测 Evaporation Prediction
- 端点: `POST /api/evaporation/predict`

### 默认参数

```json
{
  "tower_params": {
    "water_flow_m3h": 500,
    "t_in": 42,
    "t_out": 32,
    "n_cells": 4,
    "fan_power_kw": 55
  },
  "weather": {
    "t_db": 28,
    "t_wb": 22,
    "humidity": 0.65,
    "wind_speed": 2.5
  }
}
```

### 命令行调用示例

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api evaporation_predict
```

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api evaporation_predict '{"tower_params": {"water_flow_m3h": 500}, "weather": {"t_db": 28}}'
```

---

## identification_arx

- 说明: ARX模型辨识 ARX Model Identification
- 端点: `POST /api/identification/arx`

### 默认参数

```json
{
  "y": [
    0.5,
    0.48,
    0.46,
    0.44,
    0.42,
    0.41,
    0.4,
    0.39,
    0.38,
    0.38
  ],
  "u": [
    0.01,
    0.01,
    0.01,
    0.01,
    0.01,
    0.01,
    0.01,
    0.01,
    0.01,
    0.01
  ],
  "na": 2,
  "nb": 2
}
```

### 命令行调用示例

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api identification_arx
```

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api identification_arx '{"y": [0.5], "u": [0.01]}'
```

---

## identification_run

- 说明: 系统辨识 System Identification
- 端点: `POST /api/identification/run`

### 默认参数

```json
{
  "observed_h": [
    0.5,
    0.48,
    0.46,
    0.44,
    0.42,
    0.41,
    0.4,
    0.39,
    0.38,
    0.38
  ],
  "observed_q_out": [
    0.0042,
    0.0041,
    0.004,
    0.0039,
    0.0038,
    0.0038,
    0.0037,
    0.0037,
    0.0036,
    0.0036
  ],
  "model_type": "nonlinear",
  "initial_guess": null
}
```

### 命令行调用示例

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api identification_run
```

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api identification_run '{"observed_h": [0.5], "observed_q_out": [0.0042]}'
```

---

## leak_detection_detect

- 说明: 泄漏检测 Leak Detection
- 端点: `POST /api/leak-detection/detect`

### 默认参数

```json
{
  "graph_nodes": [
    {
      "id": "water_treatment",
      "q_in": 433,
      "q_out": 420,
      "q_loss": 13
    },
    {
      "id": "clear_pool",
      "q_in": 420,
      "q_out": 415,
      "q_loss": 5
    },
    {
      "id": "high_pool",
      "q_in": 665,
      "q_out": 650,
      "q_loss": 15
    },
    {
      "id": "ws_dissolution",
      "q_in": 158,
      "q_out": 140,
      "q_loss": 18
    },
    {
      "id": "ws_evaporation",
      "q_in": 50,
      "q_out": 42,
      "q_loss": 8
    },
    {
      "id": "ws_decomposition",
      "q_in": 21,
      "q_out": 19,
      "q_loss": 2
    },
    {
      "id": "ws_red_mud",
      "q_in": 136,
      "q_out": 100,
      "q_loss": 36
    },
    {
      "id": "ws_calcination",
      "q_in": 33,
      "q_out": 20,
      "q_loss": 13
    },
    {
      "id": "ws_raw_material",
      "q_in": 17,
      "q_out": 15,
      "q_loss": 2
    },
    {
      "id": "ws_auxiliary",
      "q_in": 18,
      "q_out": 16,
      "q_loss": 2
    },
    {
      "id": "cooling_towers",
      "q_in": 175,
      "q_out": 0,
      "q_loss": 0
    },
    {
      "id": "reuse_station",
      "q_in": 250,
      "q_out": 240,
      "q_loss": 10
    }
  ],
  "graph_edges": [
    {
      "source": "water_treatment",
      "target": "clear_pool",
      "flow": 100
    },
    {
      "source": "clear_pool",
      "target": "high_pool",
      "flow": 100
    },
    {
      "source": "high_pool",
      "target": "ws_dissolution",
      "flow": 100
    },
    {
      "source": "high_pool",
      "target": "ws_evaporation",
      "flow": 100
    },
    {
      "source": "high_pool",
      "target": "ws_decomposition",
      "flow": 100
    },
    {
      "source": "high_pool",
      "target": "ws_red_mud",
      "flow": 100
    },
    {
      "source": "high_pool",
      "target": "ws_calcination",
      "flow": 100
    },
    {
      "source": "high_pool",
      "target": "ws_raw_material",
      "flow": 100
    },
    {
      "source": "high_pool",
      "target": "ws_auxiliary",
      "flow": 100
    },
    {
      "source": "high_pool",
      "target": "cooling_towers",
      "flow": 100
    },
    {
      "source": "ws_dissolution",
      "target": "reuse_station",
      "flow": 100
    },
    {
      "source": "ws_evaporation",
      "target": "reuse_station",
      "flow": 100
    },
    {
      "source": "reuse_station",
      "target": "high_pool",
      "flow": 100
    }
  ],
  "threshold": 0.95
}
```

### 命令行调用示例

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api leak_detection_detect
```

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api leak_detection_detect '{"graph_nodes": [{"id": "water_treatment", "q_in": 433, "q_out": 420, "q_loss": 13}], "graph_edges": [{"source": "water_treatment", "target": "clear_pool", "flow": 100}]}'
```

---

## leak_detection_localize

- 说明: 泄漏定位 Leak Localization
- 端点: `POST /api/leak-detection/localize`

### 默认参数

```json
{
  "graph_nodes": [
    {
      "id": "water_treatment",
      "q_in": 433,
      "q_out": 420,
      "q_loss": 13
    },
    {
      "id": "clear_pool",
      "q_in": 420,
      "q_out": 415,
      "q_loss": 5
    },
    {
      "id": "high_pool",
      "q_in": 665,
      "q_out": 650,
      "q_loss": 15
    },
    {
      "id": "ws_dissolution",
      "q_in": 158,
      "q_out": 140,
      "q_loss": 18
    },
    {
      "id": "ws_evaporation",
      "q_in": 50,
      "q_out": 42,
      "q_loss": 8
    },
    {
      "id": "ws_decomposition",
      "q_in": 21,
      "q_out": 19,
      "q_loss": 2
    },
    {
      "id": "ws_red_mud",
      "q_in": 136,
      "q_out": 100,
      "q_loss": 36
    },
    {
      "id": "ws_calcination",
      "q_in": 33,
      "q_out": 20,
      "q_loss": 13
    },
    {
      "id": "ws_raw_material",
      "q_in": 17,
      "q_out": 15,
      "q_loss": 2
    },
    {
      "id": "ws_auxiliary",
      "q_in": 18,
      "q_out": 16,
      "q_loss": 2
    },
    {
      "id": "cooling_towers",
      "q_in": 175,
      "q_out": 0,
      "q_loss": 0
    },
    {
      "id": "reuse_station",
      "q_in": 250,
      "q_out": 240,
      "q_loss": 10
    }
  ],
  "graph_edges": [
    {
      "source": "water_treatment",
      "target": "clear_pool",
      "flow": 100
    },
    {
      "source": "clear_pool",
      "target": "high_pool",
      "flow": 100
    },
    {
      "source": "high_pool",
      "target": "ws_dissolution",
      "flow": 100
    },
    {
      "source": "high_pool",
      "target": "ws_evaporation",
      "flow": 100
    },
    {
      "source": "high_pool",
      "target": "ws_decomposition",
      "flow": 100
    },
    {
      "source": "high_pool",
      "target": "ws_red_mud",
      "flow": 100
    },
    {
      "source": "high_pool",
      "target": "ws_calcination",
      "flow": 100
    },
    {
      "source": "high_pool",
      "target": "ws_raw_material",
      "flow": 100
    },
    {
      "source": "high_pool",
      "target": "ws_auxiliary",
      "flow": 100
    },
    {
      "source": "high_pool",
      "target": "cooling_towers",
      "flow": 100
    },
    {
      "source": "ws_dissolution",
      "target": "reuse_station",
      "flow": 100
    },
    {
      "source": "ws_evaporation",
      "target": "reuse_station",
      "flow": 100
    },
    {
      "source": "reuse_station",
      "target": "high_pool",
      "flow": 100
    }
  ],
  "threshold": 0.95
}
```

### 命令行调用示例

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api leak_detection_localize
```

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api leak_detection_localize '{"graph_nodes": [{"id": "water_treatment", "q_in": 433, "q_out": 420, "q_loss": 13}], "graph_edges": [{"source": "water_treatment", "target": "clear_pool", "flow": 100}]}'
```

---

## odd_check

- 说明: ODD安全边界检查 ODD Safety Check
- 端点: `POST /api/odd/check`

### 默认参数

```json
{
  "state": {
    "water_level": 1.2,
    "inflow_rate": 0.01,
    "outflow_rate": 0.008,
    "pressure": 101.3
  },
  "odd_config": null
}
```

### 命令行调用示例

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api odd_check
```

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api odd_check '{"state": {"water_level": 1.2}, "odd_config": null}'
```

---

## odd_check_series

- 说明: ODD时序安全检查 ODD Time-Series Check
- 端点: `POST /api/odd/check-series`

### 默认参数

```json
{
  "states": [
    {
      "water_level": 1.2,
      "inflow_rate": 0.01
    },
    {
      "water_level": 1.3,
      "inflow_rate": 0.01
    },
    {
      "water_level": 1.5,
      "inflow_rate": 0.012
    },
    {
      "water_level": 1.7,
      "inflow_rate": 0.015
    }
  ],
  "times": [
    0,
    60,
    120,
    180
  ],
  "odd_config": null
}
```

### 命令行调用示例

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api odd_check_series
```

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api odd_check_series '{"states": [{"water_level": 1.2, "inflow_rate": 0.01}], "times": [0]}'
```

---

## odd_mrc_plan

- 说明: 最小风险方案 MRC Plan
- 端点: `POST /api/odd/mrc-plan`

### 默认参数

```json
{
  "state": {
    "water_level": 1.9,
    "inflow_rate": 0.02,
    "outflow_rate": 0.005
  },
  "odd_config": null
}
```

### 命令行调用示例

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api odd_mrc_plan
```

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api odd_mrc_plan '{"state": {"water_level": 1.9}, "odd_config": null}'
```

---

## odd_specs

- 说明: 获取ODD规格 Get ODD Specifications
- 端点: `GET /api/odd/specs`

### 默认参数

```json
{}
```

### 命令行调用示例

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api odd_specs
```

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api odd_specs '{}'
```

---

## prediction_run

- 说明: 水位预测 Water Level Prediction
- 端点: `POST /api/prediction/run`

### 默认参数

```json
{
  "historical_data": [
    1.5,
    1.48,
    1.45,
    1.43,
    1.4,
    1.38,
    1.35,
    1.33,
    1.3,
    1.28,
    1.25,
    1.22,
    1.2,
    1.18,
    1.15,
    1.13,
    1.1,
    1.08,
    1.06,
    1.04,
    1.02,
    1.0,
    0.98,
    0.96
  ],
  "horizon": 60,
  "model": "linear",
  "lookback": null,
  "degree": 2
}
```

### 命令行调用示例

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api prediction_run
```

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api prediction_run '{"historical_data": [1.5], "horizon": 61}'
```

---

## prediction_sample

- 说明: 获取示例预测数据 Get Sample Prediction Data
- 端点: `GET /api/prediction/sample-data`

### 默认参数

```json
{}
```

### 命令行调用示例

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api prediction_sample
```

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api prediction_sample '{}'
```

---

## report_daily

- 说明: 日运营报告 Daily Operations Report
- 端点: `POST /api/report/daily`

### 默认参数

```json
{
  "date": "2026-03-01",
  "include_sections": [
    "balance",
    "anomaly",
    "kpi",
    "evaporation",
    "reuse"
  ]
}
```

### 命令行调用示例

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api report_daily
```

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api report_daily '{"date": "2026-03-01_override", "include_sections": ["balance"]}'
```

---

## report_tank_analysis

- 说明: 水箱综合分析报告 Tank Analysis Report
- 端点: `POST /api/report/tank-analysis`

### 默认参数

```json
{
  "title": "双容水箱仿真",
  "duration": 300,
  "dt": 1.0,
  "initial_h": 0.5,
  "tank_params": {
    "area": 1.0,
    "cd": 0.6,
    "outlet_area": 0.01,
    "h_max": 2.0
  },
  "q_in_profile": [
    [
      0,
      0.01
    ]
  ]
}
```

### 命令行调用示例

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api report_tank_analysis
```

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api report_tank_analysis '{"title": "双容水箱仿真_override", "duration": 301}'
```

---

## reuse_match

- 说明: 回用水源匹配 Reuse Water Source Matching
- 端点: `POST /api/reuse/match`

### 默认参数

```json
{
  "source_quality": {
    "tds": 800,
    "ph": 12,
    "cod": 50
  },
  "target_requirements": [
    {
      "id": "cooling_towers",
      "flow_m3d": 4200,
      "quality_req": {
        "tds_max": 1000,
        "ph_range": [
          6,
          10
        ]
      }
    },
    {
      "id": "ws_raw_material",
      "flow_m3d": 400,
      "quality_req": {
        "tds_max": 2000
      }
    }
  ]
}
```

### 命令行调用示例

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api reuse_match
```

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api reuse_match '{"source_quality": {"tds": 800}, "target_requirements": [{"id": "cooling_towers", "flow_m3d": 4200, "quality_req": {"tds_max": 1000, "ph_range": [6, 10]}}]}'
```

---

## reuse_optimize

- 说明: 回用方案优化 Reuse Scheduling Optimization
- 端点: `POST /api/reuse/optimize`

### 默认参数

```json
{
  "source_quality": {
    "tds": 800,
    "ph": 12,
    "cod": 50
  },
  "target_requirements": [
    {
      "id": "cooling_towers",
      "flow_m3d": 4200,
      "quality_req": {
        "tds_max": 1000,
        "ph_range": [
          6,
          10
        ]
      }
    },
    {
      "id": "ws_raw_material",
      "flow_m3d": 400,
      "quality_req": {
        "tds_max": 2000
      }
    }
  ]
}
```

### 命令行调用示例

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api reuse_optimize
```

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api reuse_optimize '{"source_quality": {"tds": 800}, "target_requirements": [{"id": "cooling_towers", "flow_m3d": 4200, "quality_req": {"tds_max": 1000, "ph_range": [6, 10]}}]}'
```

---

## scheduling_run

- 说明: 调度优化 Scheduling Optimization
- 端点: `POST /api/scheduling/run`

### 默认参数

```json
{
  "demand_forecast": [
    10200,
    10400,
    10350,
    10500,
    10380,
    10450,
    10400
  ],
  "supply_capacity": 10800,
  "method": "lp",
  "constraints": {
    "min_level": 0.3,
    "max_level": 1.8
  },
  "objective": "minimize_cost"
}
```

### 命令行调用示例

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api scheduling_run
```

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api scheduling_run '{"demand_forecast": [10200], "supply_capacity": 10801}'
```

---

## simulation_defaults

- 说明: 获取仿真默认参数 Get Simulation Defaults
- 端点: `GET /api/simulation/defaults`

### 默认参数

```json
{}
```

### 命令行调用示例

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api simulation_defaults
```

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api simulation_defaults '{}'
```

---

## simulation_run

- 说明: 水箱仿真 Tank Simulation
- 端点: `POST /api/simulation/run`

### 默认参数

```json
{
  "duration": 300,
  "dt": 1.0,
  "initial_h": 0.5,
  "q_in_profile": [
    [
      0,
      0.01
    ]
  ],
  "tank_params": {
    "area": 1.0,
    "cd": 0.6,
    "outlet_area": 0.01,
    "h_max": 2.0
  },
  "solver": "rk4"
}
```

### 命令行调用示例

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api simulation_run
```

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api simulation_run '{"duration": 301, "dt": 1.1}'
```

---

## water_balance_anomaly

- 说明: 水平衡异常检测 Water Balance Anomaly Detection
- 端点: `POST /api/water-balance/anomaly`

### 默认参数

```json
{
  "nodes_data": [
    {
      "node_id": "water_treatment",
      "node_type": "intake",
      "q_in": 433,
      "q_out": 420,
      "q_loss": 13
    },
    {
      "node_id": "clear_pool",
      "node_type": "pool",
      "q_in": 420,
      "q_out": 415,
      "q_loss": 5,
      "volume": 6000,
      "capacity": 8000
    },
    {
      "node_id": "high_pool",
      "node_type": "pool",
      "q_in": 665,
      "q_out": 650,
      "q_loss": 15,
      "volume": 10000,
      "capacity": 15000
    },
    {
      "node_id": "ws_dissolution",
      "node_type": "workshop",
      "q_in": 158,
      "q_out": 140,
      "q_loss": 18
    },
    {
      "node_id": "ws_evaporation",
      "node_type": "workshop",
      "q_in": 50,
      "q_out": 42,
      "q_loss": 8
    },
    {
      "node_id": "ws_decomposition",
      "node_type": "workshop",
      "q_in": 21,
      "q_out": 19,
      "q_loss": 2
    },
    {
      "node_id": "ws_red_mud",
      "node_type": "workshop",
      "q_in": 136,
      "q_out": 100,
      "q_loss": 36
    },
    {
      "node_id": "ws_calcination",
      "node_type": "workshop",
      "q_in": 33,
      "q_out": 20,
      "q_loss": 13
    },
    {
      "node_id": "ws_raw_material",
      "node_type": "workshop",
      "q_in": 17,
      "q_out": 15,
      "q_loss": 2
    },
    {
      "node_id": "ws_auxiliary",
      "node_type": "workshop",
      "q_in": 18,
      "q_out": 16,
      "q_loss": 2
    },
    {
      "node_id": "cooling_towers",
      "node_type": "workshop",
      "q_in": 175,
      "q_out": 0,
      "q_loss": 0,
      "q_evap": 175
    },
    {
      "node_id": "reuse_station",
      "node_type": "reuse",
      "q_in": 250,
      "q_out": 240,
      "q_loss": 10
    }
  ],
  "edges_data": [
    [
      "water_treatment",
      "clear_pool"
    ],
    [
      "clear_pool",
      "high_pool"
    ],
    [
      "high_pool",
      "ws_dissolution"
    ],
    [
      "high_pool",
      "ws_evaporation"
    ],
    [
      "high_pool",
      "ws_decomposition"
    ],
    [
      "high_pool",
      "ws_red_mud"
    ],
    [
      "high_pool",
      "ws_calcination"
    ],
    [
      "high_pool",
      "ws_raw_material"
    ],
    [
      "high_pool",
      "ws_auxiliary"
    ],
    [
      "high_pool",
      "cooling_towers"
    ],
    [
      "ws_dissolution",
      "reuse_station"
    ],
    [
      "ws_evaporation",
      "reuse_station"
    ],
    [
      "reuse_station",
      "high_pool"
    ]
  ]
}
```

### 命令行调用示例

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api water_balance_anomaly
```

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api water_balance_anomaly '{"nodes_data": [{"node_id": "water_treatment", "node_type": "intake", "q_in": 433, "q_out": 420, "q_loss": 13}], "edges_data": [["water_treatment", "clear_pool"]]}'
```

---

## water_balance_calc

- 说明: 水平衡计算 Water Balance Calculation
- 端点: `POST /api/water-balance/calc`

### 默认参数

```json
{
  "nodes_data": [
    {
      "node_id": "water_treatment",
      "node_type": "intake",
      "q_in": 433,
      "q_out": 420,
      "q_loss": 13
    },
    {
      "node_id": "clear_pool",
      "node_type": "pool",
      "q_in": 420,
      "q_out": 415,
      "q_loss": 5,
      "volume": 6000,
      "capacity": 8000
    },
    {
      "node_id": "high_pool",
      "node_type": "pool",
      "q_in": 665,
      "q_out": 650,
      "q_loss": 15,
      "volume": 10000,
      "capacity": 15000
    },
    {
      "node_id": "ws_dissolution",
      "node_type": "workshop",
      "q_in": 158,
      "q_out": 140,
      "q_loss": 18
    },
    {
      "node_id": "ws_evaporation",
      "node_type": "workshop",
      "q_in": 50,
      "q_out": 42,
      "q_loss": 8
    },
    {
      "node_id": "ws_decomposition",
      "node_type": "workshop",
      "q_in": 21,
      "q_out": 19,
      "q_loss": 2
    },
    {
      "node_id": "ws_red_mud",
      "node_type": "workshop",
      "q_in": 136,
      "q_out": 100,
      "q_loss": 36
    },
    {
      "node_id": "ws_calcination",
      "node_type": "workshop",
      "q_in": 33,
      "q_out": 20,
      "q_loss": 13
    },
    {
      "node_id": "ws_raw_material",
      "node_type": "workshop",
      "q_in": 17,
      "q_out": 15,
      "q_loss": 2
    },
    {
      "node_id": "ws_auxiliary",
      "node_type": "workshop",
      "q_in": 18,
      "q_out": 16,
      "q_loss": 2
    },
    {
      "node_id": "cooling_towers",
      "node_type": "workshop",
      "q_in": 175,
      "q_out": 0,
      "q_loss": 0,
      "q_evap": 175
    },
    {
      "node_id": "reuse_station",
      "node_type": "reuse",
      "q_in": 250,
      "q_out": 240,
      "q_loss": 10
    }
  ],
  "edges_data": [
    [
      "water_treatment",
      "clear_pool"
    ],
    [
      "clear_pool",
      "high_pool"
    ],
    [
      "high_pool",
      "ws_dissolution"
    ],
    [
      "high_pool",
      "ws_evaporation"
    ],
    [
      "high_pool",
      "ws_decomposition"
    ],
    [
      "high_pool",
      "ws_red_mud"
    ],
    [
      "high_pool",
      "ws_calcination"
    ],
    [
      "high_pool",
      "ws_raw_material"
    ],
    [
      "high_pool",
      "ws_auxiliary"
    ],
    [
      "high_pool",
      "cooling_towers"
    ],
    [
      "ws_dissolution",
      "reuse_station"
    ],
    [
      "ws_evaporation",
      "reuse_station"
    ],
    [
      "reuse_station",
      "high_pool"
    ]
  ]
}
```

### 命令行调用示例

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api water_balance_calc
```

```bash
python3 ~/.openclaw/workspace/skills/hydromas/scripts/hydromas_call.py api water_balance_calc '{"nodes_data": [{"node_id": "water_treatment", "node_type": "intake", "q_in": 433, "q_out": 420, "q_loss": 13}], "edges_data": [["water_treatment", "clear_pool"]]}'
```

---
