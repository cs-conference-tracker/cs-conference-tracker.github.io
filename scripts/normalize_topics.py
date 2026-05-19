#!/usr/bin/env python3
"""normalize_topics.py — collapse the auto-added lowercase topic keys back
onto the curated CamelCase set in data/glossary.yaml.

Round-5 agents emitted lowercase/long-form topic strings (e.g. "machine-
learning", "ai", "wireless"). The catch-up script that silenced validator
warnings registered each one as a new glossary entry, which exploded the
Topics dropdown into ~150 noisy fine-grained items. This script:

  1. Maps every lowercase variant in data/conferences.yaml back to the
     correct curated key (e.g. machine-learning → ML, hci → HCI).
  2. Keeps only the curated 24 topics plus two new ones (Bio, Quantum) in
     glossary.yaml.
  3. Re-bakes data/*.json.

Run once after a round of agent output:
    python3 scripts/normalize_topics.py
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("pip install pyyaml\n")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# lowercase/longform → curated CamelCase key
RENAME = {
    # AI / ML / NLP / CV
    "ai": "AI", "agents": "AI", "planning": "AI", "kr": "AI",
    "machine-learning": "ML", "ml": "ML", "statistics": "ML", "pattern-recognition": "ML",
    "nlp": "NLP", "speech": "NLP",
    "computer-vision": "CV", "vision": "CV",
    # HCI / Ubicomp / Mobile / IoT
    "hci": "HCI", "cscw": "HCI", "social-computing": "HCI", "web-science": "HCI",
    "ubicomp": "Ubicomp", "wearable": "Ubicomp",
    "mobile": "Mobile",
    "iot": "IoT", "sensors": "Sensors",
    "cps": "CPS", "control": "CPS", "smart-systems": "CPS", "modeling": "CPS",
    "smart-computing": "SmartCity", "smart-grid": "SmartCity", "buildings": "SmartCity",
    "energy": "SmartCity", "sustainability": "SmartCity", "society": "SmartCity",
    # IR
    "information-retrieval": "IR", "retrieval": "IR", "search": "IR",
    "ranking": "IR", "recommender-systems": "IR",
    # Networks / Systems
    "networks": "Networks", "networking": "Networks", "communications": "Networks",
    "wireless": "Networks", "internet": "Networks", "measurement": "Networks",
    "systems": "Systems", "distributed-systems": "Systems",
    "distributed-computing": "Systems", "distributed": "Systems",
    "parallel-computing": "Systems", "hpc": "Systems",
    "cluster-computing": "Systems", "edge": "Systems", "cloud": "Systems",
    "operating-systems": "Systems", "real-time-systems": "Systems",
    "performance": "Systems", "storage": "Systems", "computing": "Systems",
    # Data
    "database": "DB", "data-engineering": "DB", "data-management": "DB",
    "data-mining": "DM",
    # Security
    "security": "Security", "cryptography": "Security", "privacy": "Security",
    # SE / PL
    "software-engineering": "SE", "software-architecture": "SE",
    "software-maintenance": "SE", "testing": "SE", "empirical": "SE",
    "requirements-engineering": "SE", "program-analysis": "SE",
    "service-computing": "SE", "reliability": "SE", "engineering": "SE",
    "programming-languages": "PL", "compilers": "PL", "concurrency": "PL",
    "formal-methods": "PL", "verification": "PL",
    "logic": "Theory", "automated-reasoning": "Theory", "sat": "Theory",
    "constraints": "Theory", "automata": "Theory",
    # Theory
    "theory": "Theory", "algorithms": "Theory", "complexity": "Theory",
    "combinatorics": "Theory", "discrete-math": "Theory",
    "optimization": "Theory", "geometry": "Theory",
    # Graphics / Multimedia
    "graphics": "Graphics", "animation": "Graphics", "rendering": "Graphics",
    "visualization": "Graphics", "3d": "Graphics", "vr": "Graphics",
    "ar": "Graphics", "xr": "Graphics", "games": "Graphics", "cad": "Graphics",
    "multimedia": "Graphics", "signal-processing": "Graphics",
    "audio": "Graphics", "documents": "Graphics",
    # Robotics
    "robotics": "Robotics",
    # Architecture / Hardware
    "architecture": "Arch", "hardware": "Arch", "eda": "Arch",
    "embedded": "Arch", "embedded-systems": "Arch", "fpga": "Arch",
    "reconfigurable-computing": "Arch",
    # Bio / Health (new curated bucket)
    "bioinformatics": "Bio", "biology": "Bio", "biomedical": "Bio",
    "biomedicine": "Bio", "computational-biology": "Bio",
    "molecular-biology": "Bio", "medical-ai": "Bio", "medicine": "Bio",
    "healthcare": "Bio", "connected-health": "Bio",
    "health-data": "Bio", "health-informatics": "Bio", "informatics": "Bio",
    # Quantum (new curated bucket)
    "quantum": "Quantum",
}

# Final curated set: original 24 + Bio + Quantum.
# full_name and category are {en, zh, ja} dicts so the topic dropdown and
# popover render the right language when the user switches with the EN/中/日
# toggle. The dropdown still shows the CamelCase abbreviation as the key.
def _t(en, zh, ja):
    return {"en": en, "zh": zh, "ja": ja}

CURATED = {
    "AI":        {"full_name": _t("Artificial Intelligence",     "人工智能",         "人工知能"),
                  "category":  _t("AI / ML",                     "AI / 机器学习",     "AI / 機械学習")},
    "ML":        {"full_name": _t("Machine Learning",            "机器学习",         "機械学習"),
                  "category":  _t("AI / ML",                     "AI / 机器学习",     "AI / 機械学習")},
    "DM":        {"full_name": _t("Data Mining",                 "数据挖掘",         "データマイニング"),
                  "category":  _t("AI / ML",                     "AI / 机器学习",     "AI / 機械学習")},
    "NLP":       {"full_name": _t("Natural Language Processing", "自然语言处理",     "自然言語処理"),
                  "category":  _t("AI / ML",                     "AI / 机器学习",     "AI / 機械学習")},
    "CV":        {"full_name": _t("Computer Vision",             "计算机视觉",       "コンピュータビジョン"),
                  "category":  _t("AI / ML",                     "AI / 机器学习",     "AI / 機械学習")},
    "IR":        {"full_name": _t("Information Retrieval",       "信息检索",         "情報検索"),
                  "category":  _t("AI / ML",                     "AI / 机器学习",     "AI / 機械学習")},
    "HCI":       {"full_name": _t("Human-Computer Interaction",  "人机交互",         "ヒューマンコンピュータインタラクション"),
                  "category":  _t("Interaction",                 "交互",             "インタラクション")},
    "Ubicomp":   {"full_name": _t("Ubiquitous Computing",        "普适计算",         "ユビキタスコンピューティング"),
                  "category":  _t("Interaction",                 "交互",             "インタラクション")},
    "Mobile":    {"full_name": _t("Mobile Computing",            "移动计算",         "モバイルコンピューティング"),
                  "category":  _t("Interaction",                 "交互",             "インタラクション")},
    "IoT":       {"full_name": _t("Internet of Things",          "物联网",           "IoT（モノのインターネット）"),
                  "category":  _t("Interaction",                 "交互",             "インタラクション")},
    "Sensors":   {"full_name": _t("Sensor Networks",             "传感器网络",       "センサネットワーク"),
                  "category":  _t("Interaction",                 "交互",             "インタラクション")},
    "CPS":       {"full_name": _t("Cyber-Physical Systems",      "信息物理系统",     "サイバーフィジカルシステム"),
                  "category":  _t("Interaction",                 "交互",             "インタラクション")},
    "SmartCity": {"full_name": _t("Smart Cities",                "智慧城市",         "スマートシティ"),
                  "category":  _t("Interaction",                 "交互",             "インタラクション")},
    "GIS":       {"full_name": _t("Geographic Information Systems", "地理信息系统", "地理情報システム"),
                  "category":  _t("Interaction",                 "交互",             "インタラクション")},
    "Networks":  {"full_name": _t("Computer Networks",           "计算机网络",       "コンピュータネットワーク"),
                  "category":  _t("Systems",                     "系统",             "システム")},
    "Systems":   {"full_name": _t("Operating & Distributed Systems", "操作系统与分布式系统", "OS・分散システム"),
                  "category":  _t("Systems",                     "系统",             "システム")},
    "Arch":      {"full_name": _t("Computer Architecture",       "计算机体系结构",   "コンピュータアーキテクチャ"),
                  "category":  _t("Systems",                     "系统",             "システム")},
    "DB":        {"full_name": _t("Databases",                   "数据库",           "データベース"),
                  "category":  _t("Data",                        "数据",             "データ")},
    "Security":  {"full_name": _t("Computer Security",           "计算机安全",       "コンピュータセキュリティ"),
                  "category":  _t("Security",                    "安全",             "セキュリティ")},
    "SE":        {"full_name": _t("Software Engineering",        "软件工程",         "ソフトウェア工学"),
                  "category":  _t("SE / PL",                     "软工 / 编程语言",  "ソフトウェア工学 / 言語")},
    "PL":        {"full_name": _t("Programming Languages",       "程序设计语言",     "プログラミング言語"),
                  "category":  _t("SE / PL",                     "软工 / 编程语言",  "ソフトウェア工学 / 言語")},
    "Theory":    {"full_name": _t("Theoretical Computer Science", "理论计算机科学",  "理論計算機科学"),
                  "category":  _t("Theory",                      "理论",             "理論")},
    "Graphics":  {"full_name": _t("Computer Graphics & Multimedia", "计算机图形学与多媒体", "コンピュータグラフィックス・マルチメディア"),
                  "category":  _t("Graphics",                    "图形学",           "グラフィックス")},
    "Robotics":  {"full_name": _t("Robotics",                    "机器人学",         "ロボティクス"),
                  "category":  _t("Robotics",                    "机器人",           "ロボティクス")},
    "Bio":       {"full_name": _t("Bioinformatics & Health",     "生物信息学与健康", "バイオインフォマティクス・医療"),
                  "category":  _t("Interdisciplinary",           "交叉学科",         "学際")},
    "Quantum":   {"full_name": _t("Quantum Computing",           "量子计算",         "量子コンピューティング"),
                  "category":  _t("Interdisciplinary",           "交叉学科",         "学際")},
}


def normalize_one(topics: list[str] | None) -> list[str]:
    """Map each topic through RENAME, drop unknowns, dedupe preserving order."""
    if not topics:
        return topics or []
    seen: dict[str, None] = {}
    for t in topics:
        if not isinstance(t, str):
            continue
        # If already a curated key, keep it.
        # If it's a known lowercase variant, rename it.
        # Otherwise, drop (most fine-grained junk falls out here).
        key = t if t in CURATED else RENAME.get(t)
        if key and key in CURATED and key not in seen:
            seen[key] = None
    return list(seen.keys())


def main() -> int:
    confs = yaml.safe_load((DATA / "conferences.yaml").read_text(encoding="utf-8"))
    changed = 0
    dropped_examples: set[str] = set()
    for c in confs:
        before = c.get("topics") or []
        after = normalize_one(before)
        # Track what got dropped so we can warn the maintainer
        for t in before:
            if t not in CURATED and not RENAME.get(t):
                dropped_examples.add(t)
        if after != before:
            c["topics"] = after
            changed += 1

    (DATA / "conferences.yaml").write_text(
        yaml.dump(confs, sort_keys=False, allow_unicode=True, width=200),
        encoding="utf-8",
    )
    sys.stderr.write(f"normalized topics on {changed} venues\n")
    if dropped_examples:
        sys.stderr.write(
            f"dropped {len(dropped_examples)} unmapped tags: "
            f"{', '.join(sorted(dropped_examples)[:15])}"
            + ("…" if len(dropped_examples) > 15 else "") + "\n"
        )

    # Rewrite glossary so topics: contains only the curated set, in the
    # canonical order. Preserve other glossary top-level keys.
    gloss = yaml.safe_load((DATA / "glossary.yaml").read_text(encoding="utf-8"))
    gloss["topics"] = {k: v for k, v in CURATED.items()}
    (DATA / "glossary.yaml").write_text(
        yaml.dump(gloss, sort_keys=False, allow_unicode=True, width=200),
        encoding="utf-8",
    )
    sys.stderr.write(f"glossary topics reduced to {len(CURATED)} curated entries\n")

    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_json.py")])
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py")]).returncode


if __name__ == "__main__":
    sys.exit(main())
