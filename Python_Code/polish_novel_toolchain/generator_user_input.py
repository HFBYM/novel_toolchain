#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import re
import os
from pathlib import Path
# TODO 任务结束时显示系统时间
# ==================== 配置路径 ====================
BASE_DIR = Path("./Python_Code")
NOVEL_PATH = BASE_DIR / "novel" / "for_polish" / "末日重启.txt"
RULES_DIR = BASE_DIR / "polish_novel_toolchain"
RULES_PATH = RULES_DIR / "polish_rules.txt"

# 每部分目标字数
TARGET_CHARS = 2_5000

# ==================== 间隔提醒配置 ====================
REMINDER_INTERVAL = 1   # 每几章插入一次提醒（设为0则不插入）
REMINDER_TEXT = """
{自我检查：将原文语义紧密、逻辑连贯的句子合并为一个句子。一行内只能由一个句子，语句必须通顺，超过二十字时必须用逗号自然断开，禁止出现连续二十字无标点的情况}
"""

# ==================== 系统提示 ====================
SYSTEM_PROMPT = (
"""
【最高优先级死命令】
一个句子以句号为分割线，不能删除原文的“”
上一个换行符跟下一个换行符之间称为一行，一行内只能有一个句子
必须将原文语义紧密、逻辑连贯的句子合并为一个句子
语句必须通顺，超过二十字时必须用逗号自然断开，禁止出现连续二十字无标点的情况
不得输出连续换行符

【其他严格限制】
1. 绝对禁止改变设定、人名、地名、物品名
2. 尽量不使用破折号‘——’
4. 直接输出纯文本润色结果，不要任何解释，保留章节名
5. ‘{}’中的内容仅作提醒不输出
"""
)

# ==================== 工具函数 ====================
def load_text(path):
    encodings = ['utf-8', 'gbk', 'gb2312', 'gb18030']
    for enc in encodings:
        try:
            with open(path, 'r', encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    raise ValueError(f"无法以任何编码读取文件: {path}")

def split_chapters(text):
    pattern = re.compile(r'(第[零一二三四五六七八九十百千万亿\d]+章)')
    matches = list(pattern.finditer(text))
    if not matches:
        return [("全文", text)]
    chapters = []
    for i, match in enumerate(matches):
        title = match.group(1)
        start = match.end()
        end = matches[i+1].start() if i+1 < len(matches) else len(text)
        content = text[start:end]
        chapters.append((title, content))
    return chapters

def chinese_to_arabic(chinese):
    """中文数字转阿拉伯数字（支持常见写法）"""
    if not chinese:
        return 0
    if chinese.isdigit():
        return int(chinese)
    ch_map = {'零':0,'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,
              '十':10,'百':100,'千':1000,'万':10000,'亿':100000000}
    if '亿' in chinese:
        parts = chinese.split('亿')
        left = chinese_to_arabic(parts[0]) if parts[0] else 1
        right = chinese_to_arabic(parts[1]) if parts[1] else 0
        return left * 100000000 + right
    if '万' in chinese:
        parts = chinese.split('万')
        left = chinese_to_arabic(parts[0]) if parts[0] else 1
        right = chinese_to_arabic(parts[1]) if parts[1] else 0
        return left * 10000 + right
    result = 0
    temp = 0
    for ch in chinese:
        if ch in ch_map:
            val = ch_map[ch]
            if val >= 10:
                if temp == 0:
                    temp = 1
                result += temp * val
                temp = 0
            else:
                temp = val
    result += temp
    return result

def extract_chapter_number(title):
    match = re.search(r'第([零一二三四五六七八九十百千万亿\d]+)章', title)
    if match:
        num_str = match.group(1)
        if num_str.isdigit():
            return int(num_str)
        else:
            return chinese_to_arabic(num_str)
    return 0

def main():
    if not NOVEL_PATH.exists():
        print(f"❌ 小说文件不存在: {NOVEL_PATH}")
        return
    if not RULES_PATH.exists():
        print(f"❌ 润色规则文件不存在: {RULES_PATH}")
        return

    try:
        novel_text = load_text(NOVEL_PATH)
    except ValueError as e:
        print(f"❌ 读取小说失败: {e}")
        return

    try:
        polish_rules = load_text(RULES_PATH)
    except ValueError as e:
        print(f"❌ 读取规则失败: {e}")
        return

    chapters = split_chapters(novel_text)
    total_chapters = len(chapters)
    print(f"📚 检测到 {total_chapters} 个章节")

    # 拆分 part，保存 (全局索引, 标题, 内容)
    parts = []
    current_part = []      # 元素为 (idx, title, content)
    current_len = 0

    for idx, (title, content) in enumerate(chapters, start=1):
        chapter_len = len(content)
        if current_len + chapter_len > TARGET_CHARS and current_part:
            parts.append(current_part)
            current_part = []
            current_len = 0
        current_part.append((idx, title, content))
        current_len += chapter_len

    if current_part:
        parts.append(current_part)

    total_parts = len(parts)
    print(f"📦 拆分为 {total_parts} 个部分（目标每部分约 {TARGET_CHARS} 字符）")

    novel_stem = NOVEL_PATH.stem
    output_dir = BASE_DIR / "novel" /"for_ai"/ f"{novel_stem}"
    output_dir.mkdir(parents=True, exist_ok=True)

    for part_idx, part_chapters in enumerate(parts, start=1):
        # 提取首尾章节编号
        first_num = part_chapters[0][0]
        last_num = part_chapters[-1][0]
        range_str = f"{first_num}" if first_num == last_num else f"{first_num}-{last_num}"

        # 构建 part_text，插入间隔提醒
        part_text = ""
        part_char_count = 0
        for idx, title, content in part_chapters:
            # 标题 + 内容（保留原始分隔符）
            part_text += title + content
            part_char_count += len(title) + len(content)

            # 如果是间隔提醒的倍数，在内容后追加提醒行（不计入字符统计，但会被AI看到）
            if REMINDER_INTERVAL > 0 and idx % REMINDER_INTERVAL == 0:
                part_text += "\n" + REMINDER_TEXT + "\n"
                # 提醒行不计入字符统计（但为了计数准确，不增加）

            # 章节结束后加一个换行（分隔不同章节）
            part_text += "\n"
            part_char_count += 1  # 这个换行算作字符

        # 构建完整提示词
        user_prompt = f"""彻底并强制遗忘所有记忆，当作新对话开始。
你是一个严格遵守要求的资深小说润色专家。你要严格遵循下方的【润色总要求】和【润色规则】，对【待润色文本】进行润色。

【润色总要求】
{SYSTEM_PROMPT}

【润色规则】
{polish_rules}

【强制警告】以上所有规则必须逐条严格遵守，违反任何一条均为不合格输出，尤其是润色总要求。

【待润色文本】
{part_text}

润色后的文本："""

        output_file = output_dir / f"part{part_idx}_({range_str}).txt"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(user_prompt)

        print(f"✅ Part {part_idx} 已写入: {output_file}")
        print(f"   📄 包含 {len(part_chapters)} 个章节（第{first_num}章至第{last_num}章），约 {part_char_count} 个字符")
        if REMINDER_INTERVAL > 0:
            print(f"   🔔 已按每 {REMINDER_INTERVAL} 章插入提醒")

    print("\n🎉 所有部分生成完成！")
    print(f"📂 输出目录: {output_dir}")

if __name__ == "__main__":
    main()