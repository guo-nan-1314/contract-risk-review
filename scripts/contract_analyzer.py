#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
合同文本结构化分析器
从合同文本中提取关键要素，识别合同类型，进行基础风险模式匹配。

作者：user_7400cfba
版本：1.0.0
"""

import argparse
import json
import re
import sys
from datetime import datetime


# ─── 合同类型特征库 ──────────────────────────────────────────────
CONTRACT_TYPE_PATTERNS = {
    "劳动合同": {
        "keywords": ["劳动合同", "用人单位", "劳动者", "工资", "社保", "试用期",
                     "工作时间", "加班", "休假", "竞业限制", "保密义务", "解除劳动"],
        "required_clauses": [
            "用人单位信息", "劳动者信息", "合同期限", "工作内容", "工作地点",
            "工作时间", "劳动报酬", "社会保险", "劳动保护", "合同解除条件"
        ]
    },
    "租赁合同": {
        "keywords": ["租赁合同", "出租方", "承租方", "租金", "押金", "租赁物",
                     "租赁期限", "维修", "装修", "转租", "退租", "续租"],
        "required_clauses": [
            "出租方信息", "承租方信息", "租赁物描述", "租赁期限", "租金金额",
            "支付方式", "押金条款", "维修责任", "转租限制", "违约责任",
            "续租条件", "退租条件"
        ]
    },
    "买卖合同": {
        "keywords": ["买卖合同", "买方", "卖方", "标的物", "价款", "交付",
                     "验收", "质量保证", "付款方式", "所有权转移", "风险转移"],
        "required_clauses": [
            "买方信息", "卖方信息", "标的物描述", "数量", "质量标准",
            "价款", "付款方式", "交付时间", "交付地点", "验收标准",
            "所有权转移", "风险转移", "违约责任"
        ]
    },
    "保密协议": {
        "keywords": ["保密协议", "保密义务", "保密信息", "商业秘密", "保密期限",
                     "竞业限制", "泄密", "信息保密", "技术秘密", "客户信息"],
        "required_clauses": [
            "披露方信息", "接收方信息", "保密信息定义", "保密范围",
            "保密期限", "保密义务", "例外情形", "违约责任",
            "信息返还/销毁", "争议解决"
        ]
    },
    "服务协议": {
        "keywords": ["服务协议", "服务合同", "甲方", "乙方", "服务内容",
                     "服务期限", "服务费用", "服务质量", "验收", "知识产权"],
        "required_clauses": [
            "甲方信息", "乙方信息", "服务内容", "服务标准", "服务期限",
            "服务费用", "付款方式", "验收标准", "知识产权归属",
            "保密条款", "违约责任", "合同解除", "争议解决"
        ]
    }
}


# ─── 高风险条款模式 ──────────────────────────────────────────────
HIGH_RISK_PATTERNS = [
    {
        "name": "无限连带责任",
        "pattern": r"(承担.*无限.*连带.*责任|对.*所有.*损失.*承担.*责任)",
        "risk": "一方承担无限连带责任，可能导致个人财产被追偿",
        "suggestion": "建议限定责任范围或设定赔偿上限",
        "legal_basis": "《民法典》第178条"
    },
    {
        "name": "单方无条件解除权",
        "pattern": r"(甲方?有权.*随时.*解除|甲方?有权.*单方.*解除.*无需.*理由|乙方?不得.*解除)",
        "risk": "一方拥有无条件解除权，另一方处于极度被动地位",
        "suggestion": "建议约定解除条件和程序，双方对等",
        "legal_basis": "《民法典》第562-563条"
    },
    {
        "name": "违约金过高",
        "pattern": r"(违约金.*(?:百分之[五六七八九十]|\d{2,3}%|全部.*损失))",
        "risk": "违约金比例过高，超过法定合理范围",
        "suggestion": "违约金一般不超过合同标的额的30%",
        "legal_basis": "《民法典》第585条"
    },
    {
        "name": "排除主要权利",
        "pattern": r"(放弃.*诉讼.*权利|不得.*起诉|不得.*主张.*权利|排除.*抗辩权)",
        "risk": "格式条款排除对方主要权利",
        "suggestion": "该条款可能因违反公平原则被认定无效",
        "legal_basis": "《民法典》第497条"
    },
    {
        "name": "竞业限制无补偿",
        "pattern": r"(竞业限制.*(?:期限|范围|义务).*(?:无|不).*(?:补偿|报酬|费用))",
        "risk": "竞业限制未约定经济补偿",
        "suggestion": "竞业限制必须约定经济补偿",
        "legal_basis": "《劳动合同法》第23-24条"
    },
    {
        "name": "试用期违法",
        "pattern": r"(试用期.*(?:超过|大于).*(?:六个月|[1-9]个月))",
        "risk": "试用期超过法定上限",
        "suggestion": "合同期3个月-1年：≤1月；1-3年：≤2月；3年以上：≤6月",
        "legal_basis": "《劳动合同法》第19条"
    }
]


# ─── 中风险条款模式 ──────────────────────────────────────────────
MEDIUM_RISK_PATTERNS = [
    {
        "name": "管辖权不对等",
        "pattern": r"(争议.*(?:由.*甲方?所在地|提交.*甲方?指定).*(?:法院|仲裁))",
        "risk": "管辖权约定在对方所在地",
        "suggestion": "建议约定合同履行地法院管辖",
        "legal_basis": "《民事诉讼法》第35条"
    },
    {
        "name": "单方变更权",
        "pattern": r"(甲方?有权.*(?:单方|自行).*(?:变更|调整|修改))",
        "risk": "一方可单方变更合同内容",
        "suggestion": "建议约定变更需双方协商一致",
        "legal_basis": "《民法典》第543条"
    },
    {
        "name": "免责条款过宽",
        "pattern": r"(甲方?对.*(?:任何|一切).*(?:损失|损害).*(?:不承担|不负责|免责))",
        "risk": "免责范围过宽",
        "suggestion": "人身损害和故意/重大过失不得免责",
        "legal_basis": "《民法典》第506条"
    }
]


# ─── 核心函数 ─────────────────────────────────────────────────────

def extract_elements(text):
    """从合同文本中提取关键要素"""
    elements = {"parties": [], "amounts": [], "dates": [], "key_terms": []}
    party_patterns = [
        r"(?:甲方|出租方|卖方|用人单位|发包人|委托方)[：:]\s*(.+?)(?:\n|，|,)",
        r"(?:乙方|承租方|买方|劳动者|承包人|受托方)[：:]\s*(.+?)(?:\n|，|,)",
    ]
    for pattern in party_patterns:
        matches = re.findall(pattern, text)
        elements["parties"].extend([m.strip() for m in matches if m.strip()])
    amount_patterns = [
        r"(?:人民币|¥|￥)\s*([\d,，.]+)\s*(?:元|万|万元)",
        r"([\d,，.]+)\s*(?:元|万|万元)",
    ]
    for pattern in amount_patterns:
        matches = re.findall(pattern, text)
        elements["amounts"].extend([m.strip() for m in matches if m.strip()])
    date_patterns = [
        r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日",
        r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})",
    ]
    for pattern in date_patterns:
        matches = re.findall(pattern, text)
        for m in matches:
            if isinstance(m, tuple):
                elements["dates"].append(f"{m[0]}-{m[1].zfill(2)}-{m[2].zfill(2)}")
            else:
                elements["dates"].append(m.strip())
    for key in elements:
        elements[key] = list(dict.fromkeys(elements[key]))
    return elements


def identify_contract_type(text):
    """识别合同类型"""
    scores = {}
    for ctype, info in CONTRACT_TYPE_PATTERNS.items():
        score = sum(1 for kw in info["keywords"] if kw in text)
        scores[ctype] = score
    if not scores or max(scores.values()) == 0:
        return "未识别", 0
    best_type = max(scores, key=scores.get)
    return best_type, scores[best_type]


def scan_risks(text):
    """扫描风险条款"""
    risks = {"high": [], "medium": []}
    for item in HIGH_RISK_PATTERNS:
        if re.search(item["pattern"], text):
            risks["high"].append({"name": item["name"], "risk": item["risk"],
                                  "suggestion": item["suggestion"],
                                  "legal_basis": item["legal_basis"]})
    for item in MEDIUM_RISK_PATTERNS:
        if re.search(item["pattern"], text):
            risks["medium"].append({"name": item["name"], "risk": item["risk"],
                                    "suggestion": item["suggestion"],
                                    "legal_basis": item["legal_basis"]})
    return risks


def check_missing_clauses(text, contract_type):
    """检查缺失条款"""
    if contract_type not in CONTRACT_TYPE_PATTERNS:
        return []
    required = CONTRACT_TYPE_PATTERNS[contract_type]["required_clauses"]
    missing = []
    clause_keywords_map = {
        "用人单位信息": ["用人单位", "公司名称"], "劳动者信息": ["劳动者", "员工"],
        "出租方信息": ["出租方", "出租人"], "承租方信息": ["承租方", "承租人"],
        "租赁物描述": ["租赁物", "房屋"], "租赁期限": ["租赁期限", "租期"],
        "租金金额": ["租金", "月租"], "支付方式": ["支付方式", "付款方式"],
        "押金条款": ["押金", "保证金"], "维修责任": ["维修", "修绒"],
        "买方信息": ["买方"], "卖方信息": ["卖方"],
        "标的物描述": ["标的物", "商品"], "质量标准": ["质量", "标准"],
        "验收标准": ["验收", "检验"], "所有权转移": ["所有权转移"],
        "风险转移": ["风险转移"], "违约责任": ["违约", "赔偿"],
        "争议解决": ["争议", "仲裁", "诉讼"],
        "甲方信息": ["甲方"], "乙方信息": ["乙方"],
        "服务内容": ["服务内容"], "服务标准": ["服务标准"],
        "服务期限": ["服务期限"], "服务费用": ["服务费用"],
        "知识产权归属": ["知识产权"], "保密条款": ["保密"],
        "合同解除": ["解除", "终止"], "合同期限": ["合同期限"],
        "工作内容": ["工作内容"], "工作地点": ["工作地点"],
        "工作时间": ["工作时间"], "劳动报酬": ["工资", "薪酬"],
        "社会保险": ["社保", "五险一金"], "劳动保护": ["劳动保护"],
        "合同解除条件": ["解除条件"], "续租条件": ["续租"],
        "退租条件": ["退租"], "交付时间": ["交付时间"],
        "交付地点": ["交付地点"], "数量": ["数量"],
        "价款": ["价款", "金额"],
        "披露方信息": ["披露方"], "接收方信息": ["接收方"],
        "保密信息定义": ["保密信息"], "保密期限": ["保密期限"],
        "保密义务": ["保密义务"], "例外情形": ["例外", "除外"],
        "信息返还/销毁": ["返还", "销毁"], "保密范围": ["保密范围"],
    }
    for clause in required:
        keywords = clause_keywords_map.get(clause, [clause])
        found = any(kw in text for kw in keywords)
        if not found:
            missing.append(clause)
    return missing


def format_text_output(result):
    """格式化文本输出"""
    lines = []
    lines.append("=" * 50)
    lines.append("  合同文本结构化分析结果")
    lines.append("=" * 50)
    lines.append(f"\n  合同类型：{result['contract_type']}")
    lines.append(f"  识别置信度：{result['type_confidence']} 个关键词匹配")
    lines.append("\n" + "-" * 50)
    lines.append("  关键要素提取")
    lines.append("-" * 50)
    if result["elements"]["parties"]:
        lines.append(f"  当事人：{', '.join(result['elements']['parties'][:4])}")
    if result["elements"]["amounts"]:
        lines.append(f"  涉及金额：{', '.join(result['elements']['amounts'][:5])}")
    if result["elements"]["dates"]:
        lines.append(f"  关键日期：{', '.join(result['elements']['dates'][:5])}")
    lines.append("\n" + "-" * 50)
    lines.append("  风险条款扫描")
    lines.append("-" * 50)
    high_risks = result["risks"]["high"]
    med_risks = result["risks"]["medium"]
    if high_risks:
        lines.append(f"\n  🔴 高风险：{len(high_risks)} 项")
        for i, r in enumerate(high_risks, 1):
            lines.append(f"  {i}. {r['name']}")
            lines.append(f"     风险：{r['risk']}")
            lines.append(f"     建议：{r['suggestion']}")
    else:
        lines.append("\n  ✅ 未发现高风险条款")
    if med_risks:
        lines.append(f"\n  🟡 中风险：{len(med_risks)} 项")
        for i, r in enumerate(med_risks, 1):
            lines.append(f"  {i}. {r['name']}")
    else:
        lines.append("\n  ✅ 未发现中风险条款")
    missing = result["missing_clauses"]
    lines.append("\n" + "-" * 50)
    lines.append("  缺失条款检测")
    lines.append("-" * 50)
    if missing:
        lines.append(f"\n  ❌ 缺失 {len(missing)} 项必备条款：")
        for i, clause in enumerate(missing, 1):
            lines.append(f"  {i}. {clause}")
    else:
        lines.append("\n  ✅ 必备条款完整")
    lines.append("\n" + "=" * 50)
    lines.append("  ⚖️ 本分析仅供参考，不构成法律意见")
    lines.append("=" * 50)
    return "\n".join(lines)


def analyze_contract(text):
    """主分析函数"""
    contract_type, confidence = identify_contract_type(text)
    elements = extract_elements(text)
    risks = scan_risks(text)
    missing = check_missing_clauses(text, contract_type)
    return {
        "contract_type": contract_type,
        "type_confidence": confidence,
        "elements": elements,
        "risks": risks,
        "missing_clauses": missing,
        "analysis_time": datetime.now().isoformat(),
        "text_length": len(text)
    }


# ─── CLI 入口 ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="合同文本结构化分析器")
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--file", "-f", help="合同文件路径")
    input_group.add_argument("--stdin", action="store_true", help="从标准输入读取")
    input_group.add_argument("--text", "-t", help="直接传入合同文本")
    parser.add_argument("--json", action="store_true", help="JSON格式输出")
    parser.add_argument("--extract", action="store_true", help="仅提取要素不扫描风险")
    args = parser.parse_args()
    if args.file:
        try:
            with open(args.file, "r", encoding="utf-8") as f:
                text = f.read()
        except FileNotFoundError:
            print(f"错误：文件不存在 - {args.file}", file=sys.stderr)
            sys.exit(1)
    elif args.stdin:
        text = sys.stdin.read()
    elif args.text:
        text = args.text
    if not text or not text.strip():
        print("错误：合同文本为空", file=sys.stderr)
        sys.exit(1)
    result = analyze_contract(text)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_text_output(result))


if __name__ == "__main__":
    main()