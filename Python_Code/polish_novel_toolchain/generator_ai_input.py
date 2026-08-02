#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import re
import os
import datetime
from pathlib import Path

# ==================== 配置路径 ====================
BASE_DIR = Path("./Python_Code")

NOVEL_PATH = BASE_DIR / "novel" / "for_polish" /  "开局拥有念能力.txt" 
RULES_PATH = BASE_DIR / "polish_novel_toolchain" / "polish_rules.md"

# 每部分目标字数
TARGET_CHARS = 25000

# ==================== 间隔提醒配置 ====================
REMINDER_INTERVAL = 1   # 每几章插入一次提醒（设为0则不插入）

# ==================== 工具函数 ====================
def load_text(path):
    """尝试多种编码读取文本文件"""
    encodings = ['utf-8', 'gbk', 'gb2312', 'gb18030']
    for enc in encodings:
        try:
            with open(path, 'r', encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    raise ValueError(f"无法以任何编码读取文件: {path}")

def split_chapters(text):
    """根据章节标题拆分小说文本"""
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
    """中文数字转阿拉伯数字"""
    if not chinese: return 0
    if chinese.isdigit(): return int(chinese)
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
    result, temp = 0, 0
    for ch in chinese:
        if ch in ch_map:
            val = ch_map[ch]
            if val >= 10:
                if temp == 0: temp = 1
                result += temp * val
                temp = 0
            else: temp = val
    result += temp
    return result

def extract_chapter_number(title):
    """从章节标题中提取章节序号"""
    match = re.search(r'第([零一二三四五六七八九十百千万亿\d]+)章', title)
    if match:
        num_str = match.group(1)
        return int(num_str) if num_str.isdigit() else chinese_to_arabic(num_str)
    return 0

# ==================== Markdown 规则文件处理 ====================
def generate_template(book_name, include_reminder):
    """生成标准的 Markdown 格式规则模板"""
    template = f"""# {book_name}

## General_Rules
（请在此处直接输入通用规则，直接回车换行即可，所见即所得）

## Detailed_Rules
（请在此处直接输入详细风格要求）
"""
    if include_reminder:
        template += f"""
## REMINDER_TEXT
（请在此处直接输入间隔提醒文本）
"""
    return template + "\n"

def parse_markdown_rules(text):
    """解析 Markdown 风格的规则文本"""
    rules = {}
    book_pattern = re.compile(r'^# (.+)$', re.MULTILINE)
    book_matches = list(book_pattern.finditer(text))
    
    if not book_matches:
        return {}
        
    for i, match in enumerate(book_matches):
        book_name = match.group(1).strip()
        start = match.end()
        end = book_matches[i+1].start() if i+1 < len(book_matches) else len(text)
        book_content = text[start:end]
        
        book_rules = {}
        module_pattern = re.compile(r'^## (General_Rules|Detailed_Rules|REMINDER_TEXT)$', re.MULTILINE)
        module_matches = list(module_pattern.finditer(book_content))
        
        for j, mod_match in enumerate(module_matches):
            mod_name = mod_match.group(1).strip()
            mod_start = mod_match.end()
            mod_end = module_matches[j+1].start() if j+1 < len(module_matches) else len(book_content)
            mod_content = book_content[mod_start:mod_end].strip()
            book_rules[mod_name] = mod_content
            
        rules[book_name] = book_rules
    return rules

def ensure_rules(path, book_name, include_reminder):
    """确保规则文件存在且包含当前书名的必要规则"""
    # 1. 文件不存在则创建
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        template = generate_template(book_name, include_reminder)
        path.write_text(template, encoding='utf-8')
        return False, "规则文件不存在，已创建空模板。"
        
    text = path.read_text(encoding='utf-8')
    modified = False
    
    # 2. 检查书名是否存在
    book_pattern = re.compile(rf'^# {re.escape(book_name)}\s*$', re.MULTILINE)
    if not book_pattern.search(text):
        template = generate_template(book_name, include_reminder)
        text = template + "\n" + text
        
        # ==================== 【修复点】：在此处写入文件 ====================
        path.write_text(text, encoding='utf-8') 
        # ================================================================
        
        return False, f"未找到书名 [{book_name}]，已在文件最上方创建。"
        
    # 3. 检查该书名下是否缺失模块
    match = book_pattern.search(text)
    start_idx = match.end()
    next_book = re.search(r'^# .+$', text[start_idx:], re.MULTILINE)
    end_idx = start_idx + next_book.start() if next_book else len(text)
    book_block = text[start_idx:end_idx]
    
    required_modules = ['General_Rules', 'Detailed_Rules']
    if include_reminder:
        required_modules.append('REMINDER_TEXT')
        
    missing_modules = []
    for mod in required_modules:
        if not re.search(rf'^## {mod}\s*$', book_block, re.MULTILINE):
            missing_modules.append(mod)
            
    if missing_modules:
        addition = "\n"
        for mod in missing_modules:
            addition += f"## {mod}\n（请在此处输入{mod}内容）\n\n"
        
        new_book_block = book_block.rstrip() + "\n" + addition
        text = text[:start_idx] + new_book_block + text[end_idx:]
        modified = True

    # 4. 如果有修改，保存文件
    if modified:
        path.write_text(text, encoding='utf-8')
        return False, f"书名 [{book_name}] 缺失以下部分：{', '.join(missing_modules)}。已自动添加，请补充内容。"

    # 5. 解析并检查内容是否为空
    rules = parse_markdown_rules(text)
    book_rules = rules.get(book_name, {})
    empty_modules = []
    for mod in required_modules:
        content = book_rules.get(mod, "")
        if not content or content.startswith("（请在此处"):
            empty_modules.append(mod)
            
    if empty_modules:
        return False, f"书名 [{book_name}] 的以下部分内容未填写：{', '.join(empty_modules)}。请打开文件补充具体规则。"

    return True, book_rules

# ==================== 主函数 ====================
def main():
    start_time = datetime.datetime.now()
    print(f"🚀 任务开始，当前系统时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")

    if not NOVEL_PATH.exists():
        print(f"❌ 小说文件不存在: {NOVEL_PATH}")
        return

    try:
        novel_text = load_text(NOVEL_PATH)
    except ValueError as e:
        print(f"❌ 读取小说失败: {e}")
        return

    chapters = split_chapters(novel_text)
    print(f"📚 检测到 {len(chapters)} 个章节")

    # 自动获取小说文件名作为书名（例如：末日重启1.txt -> 末日重启1）
    novel_stem = NOVEL_PATH.stem 

    # ==================== 核心：加载并校验 Markdown 规则文件 ====================
    success, result = ensure_rules(RULES_PATH, novel_stem, REMINDER_INTERVAL > 0)
    if not success:
        print(f"\n⚠️ {result}")
        print(f"📂 请打开文件并补充内容: {RULES_PATH}")
        print("💡 提示：现在您可以像写普通文章一样直接编辑，直接回车换行即可！")
        print("💡 补充完成后，请重新运行本脚本。")
        return
        
    rules_data = result
    General_Rules = rules_data.get('General_Rules', '')
    Detailed_Rules = rules_data.get('Detailed_Rules', '')
    REMINDER_TEXT = rules_data.get('REMINDER_TEXT', '') if REMINDER_INTERVAL > 0 else ""
    print(f"✅ 成功加载 [{novel_stem}] 的润色规则\n")

    # ==================== 拆分与生成 Part ====================
    parts = []
    current_part = []
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

    print(f"📦 拆分为 {len(parts)} 个部分（目标每部分约 {TARGET_CHARS} 字符）")

    output_dir = BASE_DIR / "novel" / "for_ai" / f"{novel_stem}"
    output_dir.mkdir(parents=True, exist_ok=True)

    for part_idx, part_chapters in enumerate(parts, start=1):
        first_num = part_chapters[0][0]
        last_num = part_chapters[-1][0]
        range_str = f"{first_num}" if first_num == last_num else f"{first_num}-{last_num}"

        part_text = ""
        part_char_count = 0
        for idx, title, content in part_chapters:
            part_text += title + content
            part_char_count += len(title) + len(content)

            if REMINDER_INTERVAL > 0 and idx % REMINDER_INTERVAL == 0:
                part_text += "\n" + REMINDER_TEXT + "\n"

            part_text += "\n"
            part_char_count += 1

        user_prompt = f"""你是一个严格遵守要求的资深小说润色专家。你要严格遵循下方的【润色总要求】和【润色风格要求】，对【待润色文本】进行润色。

【润色总要求】
{General_Rules}

【润色风格要求】（在遵守上述规则的前提下执行）
{Detailed_Rules}

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
    
    end_time = datetime.datetime.now()
    print(f"\n⏳ 任务结束，当前系统时间: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"⏱️ 总耗时: {end_time - start_time}")

if __name__ == "__main__":
    main()