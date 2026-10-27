#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
发消息前的结构自检。

用法：
    python3 check_message.py 消息文件.txt
    echo "消息内容" | python3 check_message.py
    python3 check_message.py --selftest

只管形状，不管内容对不对。内容靠协议，形状靠这个脚本。

四套排版全部走纯文字符号，不依赖 Markdown 渲染：
    A 描述   裸段落
    B 提问   · 中点开头
    C 方法论 ▍ 开头 + 小标题
    D 动作   中文数字 + 【】 括住

退出码：0 全部通过或有 WARN；1 有 FAIL。
"""

import re
import sys

# 出现即算错的词。这是黑名单，不是建议。
BANNED = ["坚持", "自律", "加油", "战胜自己", "每天打卡", "毅力不够"]

PHASE_RE = re.compile(r"现在是第[一二三](?:阶)?段")
CN_NUM_HEAD = re.compile(r"^\s*[一二三四五六七八九十]、")
DOT_HEAD = re.compile(r"^\s*[·・]\s*")
METHOD_HEAD = re.compile(r"^\s*▍")
BRACKET_ACTION = re.compile(r"【[^】]+】")
QUESTION = re.compile(r"[？?]\s*$")
# 动作被写成「先……再……」的串联，会变成流程表，用户一条都不办。
SPLIT_ACTION = re.compile(r"先跟[^，。]{0,6}说|先说|先开口|先转钱|再转钱|再说")

# 方法论里会用到、但必须先给定义的抽象名词。裸着出现就是术语裸奔。
ABSTRACT_TERMS = [
    "意愿", "动机", "动作单元", "动作层", "锚点", "保底版",
    "习惯回路", "复利", "自我损耗", "执行意图", "承诺一致",
    "启动成本", "反馈回路", "剂量", "情境线索", "替代行为",
]

# 定义标记。出现任何一种，算这个词被交代过。
DEF_MARKER = re.compile(r"(说白了|意思是|指的是|叫做|叫|即|[，,]\s*是|就是)")

# Markdown 符号泄漏。手机端不渲染，这些会原样露出来。
LEAK_PATTERNS = [
    (re.compile(r"\*\*"), "** 加粗"),
    (re.compile(r"^\s*>\s", re.M), "> 引用块"),
    (re.compile(r"^\s*---\s*$", re.M), "--- 分隔线"),
    (re.compile(r"^\s*[-*]\s+", re.M), "- 或 * 列表"),
    (re.compile(r"^\s*#{1,6}\s", re.M), "# 标题"),
    (re.compile(r"`{3}"), "``` 代码块"),
]


def visible_len(text: str) -> int:
    """中文字符 + 英文单词，粗算用户要读多少。"""
    cn = len(re.findall(r"[\u4e00-\u9fff]", text))
    en = len(re.findall(r"[A-Za-z]+", text))
    return cn + en


def method_blocks(lines):
    """把每个 ▍ 块连到下一个空行为止，整块取出来。"""
    blocks, i = [], 0
    while i < len(lines):
        if METHOD_HEAD.match(lines[i]):
            j = i + 1
            while j < len(lines) and lines[j].strip():
                j += 1
            blocks.append("\n".join(lines[i:j]))
            i = j
        else:
            i += 1
    return blocks


# 「方法 → 他自己的事」那一段允许出现第二人称，之前的部分不许。
MAPPING_MARK = re.compile(r"(放到你这件事上|对应到你|在你的情况|搁在你身上)")


def check(text: str):
    fails, warns, oks = [], [], []
    lines = text.split("\n")

    # R1 长度
    n = visible_len(text)
    if n > 400:
        fails.append(f"R1 长度超标：约 {n} 字，硬上限 400。超了用户不看")
    elif n > 250:
        warns.append(f"R1 长度偏长：约 {n} 字，建议压到 250 以内")
    else:
        oks.append(f"R1 长度 {n} 字，合格")

    # R11 Markdown 符号泄漏（最先看，因为它最毁观感）
    leaks = [name for pat, name in LEAK_PATTERNS if pat.search(text)]
    if leaks:
        fails.append(
            f"R11 有 Markdown 符号漏在外面：{leaks}。手机端不渲染，会显示成符号垃圾"
        )
    else:
        oks.append("R11 没有 Markdown 符号泄漏")

    # R2 提问混形：中文数字开头且问号结尾
    bad_q = [
        i + 1
        for i, line in enumerate(lines)
        if CN_NUM_HEAD.match(line) and QUESTION.search(line)
    ]
    if bad_q:
        fails.append(
            f"R2 提问用了中文数字（第 {bad_q} 行）。提问一律中点「·」，"
            "中文数字是动作的写法，用了就撞形"
        )
    else:
        oks.append("R2 提问没有和动作撞形")

    # R3 提问条数
    dots = [l for l in lines if DOT_HEAD.match(l)]
    if len(dots) > 4:
        warns.append(f"R3 提问 {len(dots)} 条，上限 4 条，超了他会挑着答")
    elif dots:
        oks.append(f"R3 提问 {len(dots)} 条，合格")

    # R4/R8 动作
    actions = BRACKET_ACTION.findall(text)
    if len(actions) > 3:
        fails.append(f"R8 动作 {len(actions)} 条，上限 3 条。第四条开始他不做")
    elif actions:
        oks.append(f"R8 动作 {len(actions)} 条，合格")

    # 方括号里埋条件
    cond = [a for a in actions if "有空" in a or "如果" in a or "尽量" in a]
    if cond:
        fails.append(f"R4 动作里埋了条件：{cond}。这几个字一加，这条动作就不存在了")

    # R14 动作不许写成两步串联
    split = [a for a in actions if SPLIT_ACTION.search(a)]
    if split:
        fails.append(
            f"R14 动作被拆成两步串联：{split[0]}。写成「先跟他说，再转钱」，"
            "他会当成流程表，办第一条就散。改法：两条独立动作，一次发完，"
            "只要截图，中间不插问句、不再确认"
        )
    elif actions:
        oks.append("R14 动作没有串成流程")

    # R5 方法论块
    method_lines = [l for l in lines if METHOD_HEAD.match(l)]
    unnamed = [l for l in method_lines if "为什么" not in l and "《" not in l]
    if method_lines and unnamed:
        warns.append(
            f"R5 有 {len(unnamed)} 个 ▍ 后面既没有「为什么……」小标题，也没引书名"
        )
    if len(method_lines) > 1:
        warns.append(f"R7 出现了 {len(method_lines)} 个方法论块，一条消息只准一个")
    elif method_lines:
        oks.append("R5 方法论已成块")

    # 有「为什么」但没进 ▍ 块（排除提问句：「是因为什么？」里也含这两个字）
    stray = [
        l
        for l in lines
        if re.search(r"为什么[^？?]", l)
        and not METHOD_HEAD.match(l)
        and not DOT_HEAD.match(l)
        and len(l.strip()) < 30
    ]
    if stray and not method_lines:
        warns.append(f"R5 有「为什么……」这样的判断句（第 {stray[0][:12]}…），但没做成 ▍ 块")

    # R12 方法论块讲的是人的通性，不是这件事的操作说明
    blocks = method_blocks(lines)
    if blocks:
        personal = []
        for b in blocks:
            pre = MAPPING_MARK.split(b)[0]
            if re.search(r"[你您]", pre):
                personal.append(pre)
        if personal:
            head = personal[0].split("\n")[0][:20]
            fails.append(
                f"R12 方法论前半段出现了第二人称（{head}…）。「方法→他自己的事」"
                "那一段才允许写「你」，在它之前只准讲通性。出现在前半段，说明"
                "讲的是这件事的操作细节，不是方法本身，回头改"
            )
        else:
            oks.append("R12 方法论讲的是通性，没有落到具体这个人身上")

        # R13 术语不许裸奔：抽象名词出现就得当场给定义
        naked = []
        for b in blocks:
            terms = [t for t in ABSTRACT_TERMS if t in b]
            if terms and not DEF_MARKER.search(b):
                naked.append(terms)
        if naked:
            fails.append(
                f"R13 方法论里用了没交代过的概念：{naked[0]}。"
                "这些词对用户是生词，前面从没出现过，突然拿来当论据等于没说。"
                "改法：在同一个方法论块的第一句先给定义，一句一个词，"
                "用「X，是……」这种句式，再讲原理"
            )
        elif blocks:
            oks.append("R13 方法论里的概念都当场交代过")

    # R6 黑名单
    hits = [w for w in BANNED if w in text]
    if hits:
        fails.append(f"R6 出现黑名单词：{hits}")
    else:
        oks.append("R6 没有黑名单词")

    # R10 押注表述方向
    neg = [w for w in ["不舒服的事", "惩罚", "羞辱", "让你难受的事"] if w in text]
    if "押" in text and neg:
        warns.append(
            f"R10 押金表述偏负向：{neg}。直接说「押一笔钱，做不到就归你」，或者「押请你吃一顿」——"
            "落点从疼换成舍不得，机制不变"
        )

    # R9 阶段开场四段的检查
    if PHASE_RE.search(text):
        if "只做一件事" not in text:
            fails.append("R9 报了阶段，但没有「这一段只做一件事：……」的概括句")
        elif not re.search(r"只做一件事[：:][^。]{4,}", text):
            warns.append("R9 概括句像是在写机制名。它必须落在他能看见的动作上")
        else:
            oks.append("R9 阶段开场有概括句")
        if not method_lines:
            warns.append("R9 阶段开场缺方法论块（▍）")
        if not dots and not actions:
            warns.append("R9 阶段开场既没有提问也没有动作，他读完不知道下一步干什么")

    return fails, warns, oks


def report(text: str) -> int:
    fails, warns, oks = check(text)
    for x in oks:
        print(f"  PASS  {x}")
    for x in warns:
        print(f"  WARN  {x}")
    for x in fails:
        print(f"  FAIL  {x}")
    if not fails and not warns:
        print("\n可以发。")
    elif not fails:
        print("\n能发，但有几处可以收一收。")
    else:
        print("\n别发。先把 FAIL 改掉。")
    return 1 if fails else 0


SELFTEST = {
    "合格样本（纯文字版）": """前面两段都是今天做完就完了，这一段不一样：它要在往后三周里每天跑一次。

现在是第三阶段。这一段只做一件事：定一个你顺口的时间，我每天准点问你一句，你回一句。

▍为什么是问，不是提醒
先说记录。在所有改变行为的方法里，最稳的做法之一是记自己。但做成打卡表就没人填。

所以我不用提醒，我用问。你答一句，我记一句。

你怎么顺口就怎么回。最后定一件事，我几点问你不烦：

· 十一点半，你刚要铺板子那会儿
· 十二点，你刚收工那会儿
· 第二天早上
""",
    "旧的 Markdown 版（应该被拦）": """现在是第三阶段。这一段只做一件事：定一个时间。

> **为什么是问**
> 记录会改变行为。

- 十一点半
- 十二点
""",
    "提问用中文数字": """先问两件：

一、你想找谁？
二、照片哪天发？
""",
    "动作四条": """今晚做四件事：

一、【把甲挪到乙】

二、【把丙挪到丁】

三、【把戊拿出来】

四、【拍张照】
""",
    "动作拆成两步串联": """行，小陈，两百。

现在去办：

一、【先跟小陈说清楚，再转钱】

二、【转完截图给我】
""",
    "动作埋条件": """今晚一件事：

一、【有空的话把垫子铺开】
""",
    "方法论写成这件事的操作说明": """现在是第一段。这一段只做一件事：改门口。

▍为什么是三件小事
动机高的时候才推得动。车在楼下没挪，你下楼就会先往地铁口走。

今晚一件事：

一、【把车挪到你出楼门看见的地方】
""",
    "方法论里术语裸奔": """现在是第一段，只做一件事：改摆法不改决心。

▍为什么先降难度
意愿会飘，难度能改，所以先动难度。锚点不好用就换一个。

今晚一件事：

一、【把车挪出来】
""",
    "黑名单": "你要坚持下去，靠自律，加油。",
    "报阶段无概括": """现在是第二阶段。上一步摆好了。

▍为什么要有外人
人对自己的判断没有裁判权。

· 你想找谁？
""",
}


def selftest() -> int:
    bad = 0
    for name, text in SELFTEST.items():
        print(f"\n=== {name} ===")
        code = report(text)
        expect_fail = name != "合格样本（纯文字版）"
        if bool(code) != expect_fail:
            print(f"  !! 自测失败：期望 {'有 FAIL' if expect_fail else '无 FAIL'}")
            bad += 1
    print("\n自测通过" if bad == 0 else f"\n自测失败 {bad} 项")
    return 1 if bad else 0


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] == "--selftest":
        return selftest()
    if args:
        text = open(args[0], encoding="utf-8").read()
    else:
        text = sys.stdin.read()
    return report(text)


if __name__ == "__main__":
    sys.exit(main())
