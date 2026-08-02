import re

def clean_novel_text(input_file, output_file, verbose=True):
    with open(input_file, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()
    if verbose:
        print(f"共读取 {len(lines)} 行")

    # 匹配分页标记，如 (第1/2页) 或 （第1/2页）
    page_marker_pattern = r'[（(]\s*第\d+/\d+页\s*[）)]'
    # 章节标题正则：第数字章 + 任意标题（允许无空格，标题可选）
    # 分组1: 章节编号（数字），分组2: 完整标题行（不含分页标记）
    chapter_title_re = re.compile(r'^(第(\d+)章)\s*(.*)$')

    cleaned_lines = []
    current_chapter_num = None
    current_chapter_title_line = None
    chapter_content = []

    def is_page_marker_line(line):
        stripped = line.strip()
        return re.fullmatch(page_marker_pattern, stripped) is not None

    def extract_chapter_info(line):
        # 先去掉行尾的分页标记
        clean_line = re.sub(page_marker_pattern, '', line).rstrip()
        m = chapter_title_re.match(clean_line)
        if m:
            full_title = m.group(1)   # 例如 "第3491章"
            chap_num = int(m.group(2))
            # 如果标题部分有内容，保留全行；否则只保留 "第3491章"
            title_rest = m.group(3).strip()
            if title_rest:
                final_title_line = f"{full_title}{title_rest}"
            else:
                final_title_line = full_title
            return chap_num, final_title_line
        return None

    i = 0
    while i < len(lines):
        raw_line = lines[i]
        line = raw_line.rstrip('\n\r')
        stripped = line.strip()

        # 跳过纯分页标记行（单独一行只有分页标记）
        if is_page_marker_line(line):
            i += 1
            continue

        chap_info = extract_chapter_info(line)
        if chap_info:
            chap_num, clean_title = chap_info
            if verbose and current_chapter_num is not None and chap_num > current_chapter_num + 1:
                print(f"警告：章节跳变 {current_chapter_num} -> {chap_num}，可能遗漏中间章节")
            # 如果遇到新章节
            if current_chapter_num != chap_num:
                # 保存上一章
                if current_chapter_num is not None:
                    cleaned_lines.append(current_chapter_title_line)
                    cleaned_lines.extend(chapter_content)
                    if cleaned_lines and cleaned_lines[-1] != '':
                        cleaned_lines.append('')
                # 重置为新章节
                current_chapter_num = chap_num
                current_chapter_title_line = clean_title
                chapter_content = []
            # 同一章节内重复出现的标题行，直接忽略（不添加任何内容）
        else:
            # 正文行
            if current_chapter_num is not None:
                chapter_content.append(line)
            else:
                # 尚未遇到任何章节（如前言、楔子）
                cleaned_lines.append(line)

        i += 1

    # 保存最后一章
    if current_chapter_num is not None:
        cleaned_lines.append(current_chapter_title_line)
        cleaned_lines.extend(chapter_content)

    if verbose:
        print(f"最后处理的章节号: {current_chapter_num}")
        print(f"输出行数: {len(cleaned_lines)}")

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(cleaned_lines))

    if verbose:
        print(f"处理完成，输出文件: {output_file}")

if __name__ == '__main__':
    clean_novel_text('./Python_Code/novel/重生之都市仙尊.txt', './Python_Code/novel/重生之都市仙尊_bookszw.txt', verbose=True)