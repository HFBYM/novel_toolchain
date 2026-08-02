#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import os
from collections import defaultdict

def count_effective_chars(text):
    """统计去除空白字符（空格、换行、制表符等）后的字符数"""
    return len(re.sub(r'\s+', '', text))

def parse_chapters(file_path):
    """
    解析小说文件，返回章节列表，每个元素为 (章节标题, 内容文本)
    章节标题匹配模式：第[数字或中文数字]章
    """
    # 使用 gb18030 编码，兼容中文 Windows 常见编码
    with open(file_path, 'r', encoding='gb18030') as f:
        content = f.read()

    pattern = re.compile(r'第(?:[零一二三四五六七八九十百千万亿\d]+)章')
    matches = list(pattern.finditer(content))
    if not matches:
        return [("全文", content)]
    
    chapters = []
    for i, match in enumerate(matches):
        title = match.group()
        start = match.end()
        end = matches[i+1].start() if i+1 < len(matches) else len(content)
        chapter_text = content[start:end]
        chapters.append((title, chapter_text))
    
    return chapters

def main():
    novel_path = './Python_Code/novel/末日重启.txt'
    if not os.path.exists(novel_path):
        print(f"错误：文件 {novel_path} 不存在，请检查路径。")
        return

    chapters = parse_chapters(novel_path)
    total_chapters = len(chapters)
    if total_chapters == 0:
        print("文件为空或无法解析章节。")
        return

    stats = []  # (标题, 长度)
    max_len = 0
    max_chapter = ""
    for title, text in chapters:
        length = count_effective_chars(text)
        stats.append((title, length))
        if length > max_len:
            max_len = length
            max_chapter = title

    # 分组（每1000为单位）
    bins = defaultdict(int)
    for _, length in stats:
        bin_idx = length // 1000
        bins[bin_idx] += 1

    # 输出结果
    print("=" * 60)
    print("统计方式：有效字符数（去除空格、换行等空白字符）")
    print(f"总章节数：{total_chapters}")
    print(f"最长章节：{max_chapter}，字数：{max_len}")
    print("\n字数分布（每1000字为一组）：")
    print("区间\t\t章节数\t占比")
    for idx in sorted(bins.keys()):
        lower = idx * 1000
        upper = lower + 1000
        count = bins[idx]
        ratio = count / total_chapters * 100
        print(f"{lower}-{upper}\t{count}\t{ratio:.2f}%")

if __name__ == "__main__":
    main()