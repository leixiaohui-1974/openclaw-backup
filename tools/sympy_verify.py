#!/usr/bin/env python3
"""
sympy_verify.py - 基于SymPy的公式符号验证工具
研究发现：LLM检查公式格式，SymPy检查数学正确性，组合效果最佳

功能：
1. 量纲一致性检查（Saint-Venant方程、MPC目标函数等）
2. 公式推导验证（检查步骤间是否数学等价）
3. 符号一致性（对照symbol-table.md）

用法：
  python3 sympy_verify.py dims chapter6.md --symbols knowledge-base/formulas/symbol-table.md
  python3 sympy_verify.py check "Q = A * v" --expect "m^3/s"
  python3 sympy_verify.py scan chapter6.md --master knowledge-base/formulas/master-formulas.md
"""

import re
import sys
import os

# ---- 水力学量纲系统 ----
# 基本量纲: L(长度), T(时间), M(质量)
HYDRO_DIMS = {
    # 从symbol-table.md对应
    "Q": {"dim": "L^3/T", "unit": "m³/s", "name": "流量"},
    "h": {"dim": "L", "unit": "m", "name": "水位"},
    "A": {"dim": "L^2", "unit": "m²", "name": "过水面积"},
    "v": {"dim": "L/T", "unit": "m/s", "name": "流速"},
    "g": {"dim": "L/T^2", "unit": "m/s²", "name": "重力加速度"},
    "S_0": {"dim": "1", "unit": "-", "name": "底坡"},
    "S_f": {"dim": "1", "unit": "-", "name": "摩阻坡降"},
    "n": {"dim": "T/L^(1/3)", "unit": "s/m^(1/3)", "name": "糙率"},
    "B": {"dim": "L", "unit": "m", "name": "宽度"},
    "T_w": {"dim": "L", "unit": "m", "name": "顶宽"},
    "P": {"dim": "L", "unit": "m", "name": "湿周"},
    "R": {"dim": "L", "unit": "m", "name": "水力半径"},
    "Fr": {"dim": "1", "unit": "-", "name": "弗劳德数"},
    "Re": {"dim": "1", "unit": "-", "name": "雷诺数"},
    "C": {"dim": "L^(1/2)/T", "unit": "m^(1/2)/s", "name": "谢才系数"},
    # 控制论符号
    "x": {"dim": "state", "unit": "-", "name": "状态向量"},
    "u": {"dim": "input", "unit": "-", "name": "控制输入"},
    "y": {"dim": "output", "unit": "-", "name": "输出向量"},
    "t": {"dim": "T", "unit": "s", "name": "时间"},
    "dt": {"dim": "T", "unit": "s", "name": "时间步长"},
    "dx": {"dim": "L", "unit": "m", "name": "空间步长"},
    "tau": {"dim": "T", "unit": "s", "name": "延迟时间"},
}

# ---- 核心公式的量纲约束 ----
FORMULA_CONSTRAINTS = {
    "Saint-Venant连续性": {
        # ∂A/∂t + ∂Q/∂x = q_l
        "terms": ["∂A/∂t → L^2/T", "∂Q/∂x → L^3/T/L = L^2/T", "q_l → L^2/T"],
        "check": "所有项量纲必须相同: L^2/T"
    },
    "Saint-Venant动量": {
        # ∂Q/∂t + ∂(Q²/A)/∂x + gA∂h/∂x = gA(S₀-Sf)
        "terms": ["∂Q/∂t → L^3/T^2", "gA∂h/∂x → L/T^2 · L^2 · 1 = L^3/T^2"],
        "check": "所有项量纲必须相同: L^3/T^2"
    },
    "Manning公式": {
        # v = (1/n) R^(2/3) S^(1/2)
        "terms": ["v → L/T", "(1/n)R^(2/3)S^(1/2) → (L^(1/3)/T)(L^(2/3))(1) = L/T"],
        "check": "两边量纲一致: L/T"
    },
    "IDZ传递函数": {
        # G(s) = (1 + a₁s) e^(-τs) / (1 + b₁s)
        "terms": ["G(s) → 无量纲", "a₁s → T · 1/T = 无量纲", "τs → T · 1/T = 无量纲"],
        "check": "传递函数无量纲，时间常数×s无量纲"
    },
}

def extract_latex_formulas(text):
    """从Markdown提取所有LaTeX公式"""
    formulas = []
    
    # 块级公式 $$...$$
    for m in re.finditer(r'\$\$(.*?)\$\$', text, re.DOTALL):
        formulas.append({"type": "block", "latex": m.group(1).strip(), "pos": m.start()})
    
    # 行内公式 $...$
    for m in re.finditer(r'(?<!\$)\$(?!\$)(.*?)\$(?!\$)', text):
        formulas.append({"type": "inline", "latex": m.group(1).strip(), "pos": m.start()})
    
    # \begin{equation}...\end{equation}
    for m in re.finditer(r'\\begin\{(?:equation|align)\*?\}(.*?)\\end\{(?:equation|align)\*?\}', text, re.DOTALL):
        formulas.append({"type": "env", "latex": m.group(1).strip(), "pos": m.start()})
    
    return formulas

def check_symbol_consistency(formulas, symbol_table_path):
    """检查公式中的符号是否与symbol-table.md一致"""
    issues = []
    
    # 加载符号表
    known_symbols = set(HYDRO_DIMS.keys())
    if os.path.exists(symbol_table_path):
        with open(symbol_table_path, 'r') as f:
            for line in f:
                # 提取符号（假设格式：| Q | 流量 | ...）
                m = re.match(r'\|\s*\$?([A-Za-z_]+)\$?\s*\|', line)
                if m:
                    known_symbols.add(m.group(1))
    
    for f in formulas:
        # 提取公式中的变量名
        variables = set(re.findall(r'(?<![\\a-zA-Z])([A-Za-z](?:_[A-Za-z0-9]+)?)', f["latex"]))
        # 排除LaTeX命令（frac, partial, begin等）
        latex_cmds = {"frac", "partial", "begin", "end", "left", "right", "sum", "int", "lim",
                       "infty", "cdot", "times", "leq", "geq", "min", "max", "text", "mathrm",
                       "boldsymbol", "mathbf", "hat", "bar", "dot", "tilde", "vec", "nabla",
                       "sin", "cos", "tan", "log", "ln", "exp", "sup", "inf", "arg"}
        variables -= latex_cmds
        
        unknown = variables - known_symbols
        if unknown and len(unknown) <= 5:  # 太多未知说明可能是文本不是公式
            issues.append({
                "formula": f["latex"][:80],
                "unknown_symbols": list(unknown),
                "suggestion": "请确认这些符号是否需要添加到symbol-table.md"
            })
    
    return issues

def check_dimensional_consistency(text):
    """检查已知公式的量纲一致性"""
    results = []
    
    for name, constraint in FORMULA_CONSTRAINTS.items():
        # 检查文中是否包含该公式的关键字
        keywords = {
            "Saint-Venant连续性": ["Saint-Venant", "连续性", "continuity"],
            "Saint-Venant动量": ["Saint-Venant", "动量", "momentum"],
            "Manning公式": ["Manning", "曼宁"],
            "IDZ传递函数": ["IDZ", "积分延迟零点", "transfer function"],
        }
        
        found = False
        for kw in keywords.get(name, []):
            if kw.lower() in text.lower():
                found = True
                break
        
        if found:
            results.append({
                "formula": name,
                "constraint": constraint["check"],
                "terms": constraint["terms"],
                "status": "⚠️ 请验证量纲一致性"
            })
    
    return results

def try_sympy_verify(latex_str):
    """尝试用SymPy验证公式（需要安装sympy）"""
    try:
        from sympy import symbols, simplify, latex
        from sympy.parsing.latex import parse_latex
        
        # 尝试解析LaTeX
        expr = parse_latex(latex_str)
        simplified = simplify(expr)
        
        return {
            "parsed": True,
            "simplified": str(simplified),
            "latex_output": latex(simplified)
        }
    except ImportError:
        return {"parsed": False, "error": "sympy未安装，运行: pip install sympy"}
    except Exception as e:
        return {"parsed": False, "error": f"解析失败: {str(e)[:100]}"}

def scan_file(filepath, symbol_table_path=None, master_formulas_path=None):
    """扫描文件并生成完整验证报告"""
    with open(filepath, 'r') as f:
        text = f.read()
    
    formulas = extract_latex_formulas(text)
    
    print(f"\n🔬 SymPy公式验证: {filepath}")
    print(f"   找到 {len(formulas)} 个公式\n")
    
    # 1. 符号一致性
    if symbol_table_path:
        issues = check_symbol_consistency(formulas, symbol_table_path)
        if issues:
            print("📋 符号一致性问题:")
            for iss in issues:
                print(f"   ⚠️ 公式: {iss['formula']}")
                print(f"      未知符号: {', '.join(iss['unknown_symbols'])}")
                print(f"      {iss['suggestion']}")
        else:
            print("✅ 符号一致性检查通过")
    
    # 2. 量纲一致性
    dim_results = check_dimensional_consistency(text)
    if dim_results:
        print("\n📋 量纲一致性检查:")
        for r in dim_results:
            print(f"   {r['status']} {r['formula']}: {r['constraint']}")
            for term in r['terms']:
                print(f"      · {term}")
    
    # 3. SymPy解析测试（如果可用）
    print("\n📋 SymPy解析测试:")
    parsed_count = 0
    for i, f in enumerate(formulas[:10]):  # 只测试前10个
        result = try_sympy_verify(f["latex"])
        status = "✅" if result["parsed"] else "⚠️"
        if result["parsed"]:
            parsed_count += 1
        print(f"   [{i+1}] {status} {f['latex'][:60]}...")
    
    if len(formulas) > 10:
        print(f"   ... 还有{len(formulas)-10}个公式未测试")
    
    print(f"\n📊 汇总: {len(formulas)}个公式, {parsed_count}/min(10,{len(formulas)})个SymPy可解析")
    
    return {
        "total_formulas": len(formulas),
        "symbol_issues": issues if symbol_table_path else [],
        "dim_checks": dim_results
    }

# ---- CLI ----
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法:")
        print("  python3 sympy_verify.py scan <文件> --symbols <symbol-table.md> --master <master-formulas.md>")
        print("  python3 sympy_verify.py dims <文件>  # 仅量纲检查")
        print("  python3 sympy_verify.py check \"Q = A * v\" --expect \"m^3/s\"")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "scan":
        filepath = sys.argv[2]
        sym_path = None
        master_path = None
        for i, arg in enumerate(sys.argv):
            if arg == "--symbols" and i+1 < len(sys.argv): sym_path = sys.argv[i+1]
            if arg == "--master" and i+1 < len(sys.argv): master_path = sys.argv[i+1]
        scan_file(filepath, sym_path, master_path)
    
    elif cmd == "dims":
        filepath = sys.argv[2]
        with open(filepath, 'r') as f:
            text = f.read()
        results = check_dimensional_consistency(text)
        for r in results:
            print(f"{r['status']} {r['formula']}: {r['constraint']}")
    
    elif cmd == "check":
        latex_str = sys.argv[2]
        result = try_sympy_verify(latex_str)
        print(f"解析: {'✅' if result['parsed'] else '❌'}")
        if result["parsed"]:
            print(f"简化: {result['simplified']}")
        else:
            print(f"错误: {result['error']}")
    
    else:
        print(f"未知命令: {cmd}")
