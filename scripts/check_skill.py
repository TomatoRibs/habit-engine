#!/usr/bin/env python3
"""skill 包级规范校验。

检查的是「这个包作为一个交付物合不合格」，不是「某条消息说得好不好」。
后者由 check_message.py 负责。

用法：
    python3 scripts/check_skill.py            # 全量检查
    python3 scripts/check_skill.py --strict   # WARN 也当失败
    python3 scripts/check_skill.py --list     # 只列规则

退出码：0 全过，1 有 FAIL（--strict 时有 WARN 也算）。
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL_MD = ROOT / "SKILL.md"
CHANGELOG = ROOT / "CHANGELOG.md"
REFS = ROOT / "references"
SCRIPTS = ROOT / "scripts"

FAIL, WARN, OK = "FAIL", "WARN", "OK"

# metadata 里必须有值的字段。缺一个，这个包就被当成「半成品」。
REQUIRED_META = ["author", "version", "category", "license", "created"]

# 目录里不许出现的东西。运行时数据属于使用者，不属于 skill 包。
FORBIDDEN_DIRS = ["state", "node_modules", "__pycache__", ".git"]

# 一个文件少于这么多行，基本等于占位符。
MIN_LINES = 30

results = []


def add(level, code, msg):
    results.append((level, code, msg))


def read(p):
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def parse_frontmatter(text):
    """不依赖 pyyaml，手写解析。只认顶层 key 和 metadata 下的 key。"""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None, None
    block = m.group(1)
    top, meta = {}, {}
    in_meta = False
    cur_key = None
    for line in block.split("\n"):
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        s = line.strip()
        if s.startswith("metadata:"):
            in_meta = True
            continue
        if indent == 0 and ":" in s:
            in_meta = False
            k, v = s.split(":", 1)
            top[k.strip()] = v.strip().strip('"').strip("'")
            cur_key = k.strip()
        elif in_meta and indent > 0 and ":" in s:
            k, v = s.split(":", 1)
            meta[k.strip()] = v.strip().strip('"').strip("'")
        elif indent > 0 and cur_key:
            # block scalar 的续行
            top[cur_key] = (top.get(cur_key, "") + " " + s).strip()
    return top, meta


def check_structure():
    if not SKILL_MD.exists():
        add(FAIL, "S01", "SKILL.md 不存在")
        return None, None
    text = read(SKILL_MD)
    top, meta = parse_frontmatter(text)
    if top is None:
        add(FAIL, "S01", "SKILL.md 开头没有成对的 --- frontmatter")
        return text, None
    add(OK, "S01", "SKILL.md 与 frontmatter 齐全")

    # name 必须等于目录名，否则调用时对不上
    name = top.get("name", "")
    if name != ROOT.name:
        add(FAIL, "S02", f"frontmatter name「{name}」≠ 目录名「{ROOT.name}」")
    else:
        add(OK, "S02", f"name 与目录名一致（{name}）")

    # description 是唯一的分发入口，太短等于没写
    desc = top.get("description", "")
    if len(desc) < 100:
        add(FAIL, "S03", f"description 只有 {len(desc)} 字，触发词覆盖不足")
    elif "触" not in desc and "trigger" not in desc.lower():
        add(WARN, "S03", "description 没写触发词段落，靠模型自己猜")
    else:
        add(OK, "S03", f"description {len(desc)} 字，含触发词")

    missing = [k for k in REQUIRED_META if not meta.get(k)]
    if missing:
        add(FAIL, "S04", f"metadata 缺 {missing}")
    else:
        add(OK, "S04", f"metadata 六个必填字段齐全，version={meta['version']}")

    return text, meta


def check_license(meta):
    if not meta or meta.get("license") != "MIT":
        add(WARN, "S05", "license 字段不是 MIT，跳过配文件检查")
        return
    if not (ROOT / "LICENSE").exists():
        add(FAIL, "S05", "metadata 声明 MIT，但目录里没有 LICENSE 文件")
    else:
        body = read(ROOT / "LICENSE")
        if "MIT License" not in body or len(body) < 400:
            add(FAIL, "S05", "LICENSE 存在但内容不完整")
        else:
            add(OK, "S05", "LICENSE 与 license 字段一致")


def check_references(text):
    """SKILL.md 里点名的文件必须真的存在；存在但没被点名的，是孤儿。"""
    refs_named = set(re.findall(r"`?references/([0-9]{2}-[a-z0-9-]+\.md)`?", text))
    scripts_named = set(re.findall(r"`?(?:scripts/)?([a-z_]+\.py)`?", text))
    assets_named = re.findall(r"`?assets/([^`）)\s]+)`?", text)

    bad = []
    for f in sorted(refs_named):
        if not (REFS / f).exists():
            bad.append(f"references/{f}")
    for f in sorted(scripts_named):
        if not (SCRIPTS / f).exists():
            bad.append(f"scripts/{f}")
    if bad:
        add(FAIL, "S06", f"SKILL.md 点名但文件不存在：{bad}")
    elif refs_named or scripts_named:
        add(OK, "S06", f"点名的 {len(refs_named)} 份 reference、{len(scripts_named)} 个脚本全部存在")

    # 编号连续性：00,01,02… 不许跳号
    have = sorted(p.name for p in REFS.glob("[0-9][0-9]-*.md")) if REFS.exists() else []
    nums = [int(n[:2]) for n in have]
    gaps = [n for n in range(max(nums) + 1) if n not in nums] if nums else []
    if gaps:
        add(FAIL, "S07", f"references 编号断号：缺 {gaps}（现有 {nums}）")
    else:
        add(OK, "S07", f"references 编号连续（00–{max(nums):02d}）" if nums else "无 references")

    # 孤儿：文件在，但 SKILL.md 从没提它，等于白写
    if have:
        orphans = [f for f in have if f not in refs_named]
        if orphans:
            add(WARN, "S08", f"孤儿文件（存在但加载表没提）：{orphans}")
        else:
            add(OK, "S08", "无孤儿参考文件")

    if assets_named:
        missing = [a for a in assets_named if not (ROOT / "assets" / a).exists()]
        if missing:
            add(FAIL, "S09", f"assets 点名但不存在：{missing}")
        else:
            add(OK, "S09", "assets 引用完整")
    else:
        add(OK, "S09", "未引用 assets，无需检查")


def check_version(text, meta):
    """版本号在三个地方必须一致：frontmatter、正文「当前 x.y.z」、CHANGELOG 首条。"""
    if not meta:
        return
    v = meta.get("version", "")
    m = re.search(r"当前\s*([0-9]+\.[0-9]+\.[0-9]+)", text)
    body_v = m.group(1) if m else None

    cl = read(CHANGELOG)
    mc = re.search(r"^##\s*([0-9]+\.[0-9]+\.[0-9]+)", cl, re.M)
    cl_v = mc.group(1) if mc else None

    if body_v != v:
        add(FAIL, "S10", f"正文写「当前 {body_v}」，frontmatter 写 {v}")
    if cl_v != v:
        add(FAIL, "S10", f"CHANGELOG 首条是 {cl_v}，frontmatter 是 {v}")
    if body_v == v == cl_v:
        add(OK, "S10", f"版本三处一致（{v}）")


def check_changelog():
    cl = read(CHANGELOG)
    if not cl:
        add(FAIL, "S11", "CHANGELOG.md 不存在或为空")
        return
    heads = re.findall(r"^##\s*([0-9]+\.[0-9]+\.[0-9]+)(.*)$", cl, re.M)
    if not heads:
        add(FAIL, "S11", "CHANGELOG 里没有任何版本条目")
        return
    nodate = [h[0] for h in heads if not re.search(r"\d{4}-\d{2}-\d{2}", h[1])]
    if nodate:
        add(WARN, "S11", f"这些版本条目没有日期：{nodate}")
    # 版本号必须严格递减（最新的在最上面）
    nums = [tuple(int(x) for x in h[0].split(".")) for h in heads]
    if nums != sorted(nums, reverse=True):
        add(WARN, "S11", "CHANGELOG 版本顺序不是从新到旧")
    if not nodate and nums == sorted(nums, reverse=True):
        add(OK, "S11", f"CHANGELOG {len(heads)} 条，顺序正确、均有日期")


def check_placeholders():
    """残留的 TODO / 待补 / 尚未建成，是「做了一半」最硬的证据。"""
    pat = re.compile(r"TODO|FIXME|XXX|待补|待写|尚未建成|占位")
    hits = []
    for p in sorted(ROOT.rglob("*.md")):
        if p.name == "CHANGELOG.md":
            continue  # 变更史里出现旧措辞是史实，不是占位
        for i, line in enumerate(read(p).split("\n"), 1):
            if pat.search(line):
                hits.append(f"{p.relative_to(ROOT)}:{i}")
    if hits:
        add(FAIL, "S12", f"发现 {len(hits)} 处占位/未完成标记：{hits[:6]}")
    else:
        add(OK, "S12", "无占位标记")


def check_hygiene():
    dirty = [d for d in FORBIDDEN_DIRS if (ROOT / d).exists()]
    if dirty:
        add(WARN, "S13", f"包内存放了不该有的目录：{dirty}（运行时数据应放使用者工作区）")
    else:
        add(OK, "S13", "包内无运行时数据")

    thin = []
    for p in sorted(list(REFS.glob("*.md")) + list(ROOT.glob("*.md"))):
        n = len(read(p).split("\n"))
        if n < MIN_LINES:
            thin.append(f"{p.name}({n} 行)")
    if thin:
        add(WARN, "S14", f"内容过薄，疑似占位：{thin}")
    else:
        add(OK, "S14", "无过薄文件")


def check_scripts():
    cm = SCRIPTS / "check_message.py"
    if not cm.exists():
        add(FAIL, "S15", "scripts/check_message.py 不存在")
        return
    try:
        r = subprocess.run(
            [sys.executable, str(cm), "--selftest"],
            capture_output=True, text=True, timeout=60,
        )
        tail = (r.stdout or "").strip().split("\n")[-1] if r.stdout else ""
        if "FAIL" in tail.upper() and "0" not in tail:
            add(FAIL, "S15", f"check_message.py 自测未全过：{tail}")
        else:
            add(OK, "S15", f"check_message.py 自测通过（{tail[:60]}）")
    except Exception as e:
        add(FAIL, "S15", f"自测跑不起来：{e}")


# 被推翻过的口径。任何一份 references 里再出现（除否定语境），就是条款改了、执行文件没改。
DEAD_PHRASES = [
    "押一件你真在乎的事", "你想找谁", "赌约", "五十到一百",
    "人和钱一起说", "定一个你顺口的时间", "每天一句，按你说的改",
    "你真在乎的东西", "转他两百", "押一件让你不舒服的事",
]
# 整行出现这些词，说明这句是在「说明错误写法」，不是在用旧口径
EXEMPT = ["不许", "不要", "禁止", "反例", "错在", "写成", "偏负向",
          "已废除", "废掉", "长什么样", "违反"]


def check_dead_phrases():
    hits = []
    for p in sorted(REFS.glob("*.md")):
        for i, line in enumerate(read(p).split("\n"), 1):
            for d in DEAD_PHRASES:
                idx = line.find(d)
                if idx < 0:
                    continue
                if any(k in line for k in EXEMPT):
                    continue  # 这一行在引用禁令或举例，不算残留
                hits.append(f"{p.name}:{i}「{d}」")
    if hits:
        add(FAIL, "S16",
            f"references 里残留已废除的旧口径 {len(hits)} 处：{hits[:5]}。"
            "这些说法在 1.6.x 已被逐条推翻，条款改了执行文件没改，输出就会退回去")
    else:
        add(OK, "S16", "references 无已废除的旧口径")


def check_demo_sync():
    """样本里的每条消息，必须过得了 check_message.py。

    这是条款和示例的机器绑定：条款改了、示例没改，这里就会红。
    历史上犯过两次（第四轮、第六轮），都是规则写对了、示例停在上一版，
    模型照着示例模仿，输出就退回旧版。
    """
    demo = REFS / "05-demo-cooking.md"
    cm = SCRIPTS / "check_message.py"
    if not demo.exists() or not cm.exists():
        add(WARN, "S17", "缺 05-demo-cooking.md 或 check_message.py，无法校验样本")
        return

    blocks, cur = [], []
    for line in read(demo).split("\n"):
        if line.startswith(">"):
            cur.append(line[1:].lstrip())
        else:
            if cur:
                blocks.append("\n".join(cur))
                cur = []
    if cur:
        blocks.append("\n".join(cur))

    import tempfile, os
    bad = []
    for i, b in enumerate(blocks, 1):
        if len(b.strip()) < 10:
            continue
        fd, path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        Path(path).write_text(b, encoding="utf-8")
        try:
            r = subprocess.run([sys.executable, str(cm), path],
                               capture_output=True, text=True, timeout=30)
            out = (r.stdout or "") + (r.stderr or "")
            if "✗" in out:
                first = [l.strip() for l in out.split("\n") if l.strip().startswith("✗")]
                bad.append(f"第{i}条：{first[0][:40] if first else '不合格'}")
        finally:
            os.unlink(path)

    if bad:
        add(FAIL, "S17",
            f"样本有 {len(bad)} 条消息过不了 check_message：{bad[:3]}。"
            "示例比条款更容易被模仿，示例错了等于规则没改")
    else:
        add(OK, "S17", f"样本 {len([b for b in blocks if len(b.strip())>=10])} 条消息全部通过 check_message")


RULES = [
    ("S01", "SKILL.md 与 frontmatter 成对存在"),
    ("S02", "frontmatter name 等于目录名"),
    ("S03", "description 有长度、有触发词"),
    ("S04", "metadata 六个必填字段齐全"),
    ("S05", "license 声明配得上 LICENSE 文件"),
    ("S06", "点名的 reference / 脚本全部存在"),
    ("S07", "references 编号连续，不跳号"),
    ("S08", "无孤儿参考文件"),
    ("S09", "assets 引用完整"),
    ("S10", "版本三处一致（frontmatter / 正文 / CHANGELOG）"),
    ("S11", "CHANGELOG 每条有日期、从新到旧"),
    ("S12", "无 TODO / 待补 / 尚未建成"),
    ("S13", "包内不放运行时数据"),
    ("S14", "无过薄文件"),
    ("S15", "check_message.py 自测通过"),
    ("S16", "references 无已废除的旧口径"),
    ("S17", "样本消息通过 check_message（条款与示例绑定）"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="WARN 也当失败")
    ap.add_argument("--list", action="store_true", help="只列规则")
    args = ap.parse_args()

    if args.list:
        for code, desc in RULES:
            print(f"{code}  {desc}")
        return 0

    print(f"校验对象：{ROOT}\n")

    text, meta = check_structure()
    check_license(meta)
    if text:
        check_references(text)
        check_version(text, meta)
    check_changelog()
    check_placeholders()
    check_hygiene()
    check_scripts()
    check_dead_phrases()
    check_demo_sync()

    order = {FAIL: 0, WARN: 1, OK: 2}
    for level in (FAIL, WARN, OK):
        group = [r for r in results if r[0] == level]
        if not group:
            continue
        for lv, code, msg in group:
            mark = {"FAIL": "✗", "WARN": "!", "OK": "✓"}[lv]
            print(f"  {mark} {code}  {msg}")

    n_fail = sum(1 for r in results if r[0] == FAIL)
    n_warn = sum(1 for r in results if r[0] == WARN)
    n_ok = sum(1 for r in results if r[0] == OK)
    print(f"\n{len(RULES)} 条规则：{n_ok} 过 / {n_warn} 警 / {n_fail} 败")

    if n_fail or (args.strict and n_warn):
        print("结论：不合格，先修完再谈交付。")
        return 1
    if n_warn:
        print("结论：可用，但有隐患。")
        return 0
    print("结论：全部通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
