import os
import re

# ================= 配置区域 =================
INPUT_DIR = './Python_Code/novel/for_merge/末日重启_polish'
OUTPUT_FILE = 'ALL.txt'
ENABLE_QUOTE_NEWLINE = True  # True开启，False关闭引号换行处理

# 统计配置
DEVIATION_THRESHOLD = 0.30   # 偏离平均数的阈值 (0.30 代表 30%)
# ============================================

def get_sorted_files(directory):
    """获取并排序文件，检测缺失的part"""
    if not os.path.exists(directory):
        print(f"❌ 错误：目录 {directory} 不存在！")
        return [], []
    
    files = os.listdir(directory)
    valid_files = []
    pattern = re.compile(r'^part(\d+)')
    
    for filename in files:
        if filename == OUTPUT_FILE:
            continue
        match = pattern.match(filename)
        if match and filename.endswith('.txt'):
            part_num = int(match.group(1))
            valid_files.append((part_num, filename))
    
    if not valid_files:
        return [], []
    
    valid_files.sort(key=lambda x: x[0])
    
    # 找出缺失的part编号
    all_nums = [f[0] for f in valid_files]
    min_num, max_num = min(all_nums), max(all_nums)
    expected_nums = set(range(min_num, max_num + 1))
    actual_nums = set(all_nums)
    missing_nums = sorted(expected_nums - actual_nums)
    
    return [f[1] for f in valid_files], missing_nums

def process_text(text, enable_newline):
    """
    处理文本：标点引号换行 & 连续对话引号换行（优化版）
    重点解决 “你好。”“你好。” 中间插入换行，且不重复添加空行。
    """
    if not enable_newline:
        return text

    # 定义右引号（中文右引号 ” 和英文单引号 ' ）、左引号（中文左引号 “）
    # 注意：此处仅处理中文引号，可根据需要扩展英文双引号
    right_quote = '”'   # 中文右引号
    left_quote = '“'    # 中文左引号

    # 规则①：句号/问号/感叹号 + 右引号 后插入换行（如果后面不是空白+换行）
    # 允许右引号后跟着空格或制表符，但不会跨换行匹配
    # 使用负向前瞻确保不重复添加
    text = re.sub(
        rf'([。？！]{re.escape(right_quote)})(?![ \t]*\n)',
        r'\1\n',
        text
    )

    # 规则②：右引号 与 左引号 之间（允许空格/制表符，不含换行）插入换行
    # 使用 [ \t]* 替代 \s*，避免匹配到已有的换行符，防止重复
    text = re.sub(
        rf'({re.escape(right_quote)})[ \t]*({re.escape(left_quote)})(?![ \t]*\n)',
        r'\1\n\2',
        text
    )

    # 再执行一轮，处理嵌套或连续出现的引号对（最多两轮足够，避免过度循环）
    text = re.sub(
        rf'([。？！]{re.escape(right_quote)})(?![ \t]*\n)',
        r'\1\n',
        text
    )
    text = re.sub(
        rf'({re.escape(right_quote)})[ \t]*({re.escape(left_quote)})(?![ \t]*\n)',
        r'\1\n\2',
        text
    )

    return text

def detect_encoding(filepath):
    """尝试检测文件编码"""
    encodings = ['utf-8', 'gbk', 'gb2312', 'utf-8-sig']
    for encoding in encodings:
        try:
            with open(filepath, 'r', encoding=encoding) as f:
                f.read(1024)
            return encoding
        except (UnicodeDecodeError, LookupError):
            continue
    return 'utf-8'

def main():
    print("=" * 60)
    print(" 小说文件合并与统计分析工具")
    print("=" * 60)
    print(f" 输入目录: {os.path.abspath(INPUT_DIR)}")
    print(f"📄 输出文件: {OUTPUT_FILE}")
    print(f" 引号换行: {'✅ 开启' if ENABLE_QUOTE_NEWLINE else '❌ 关闭'}")
    print(f"📊 偏离阈值: {DEVIATION_THRESHOLD * 100:.0f}%")
    print("\n 正在扫描文件，请稍候...")
    
    sorted_files, missing_parts = get_sorted_files(INPUT_DIR)
    
    if not sorted_files:
        print("\n❌ 未找到任何 part*.txt 文件！")
        return
    
    print("⏳ 正在静默合并文件，请稍候...")
    
    output_path = os.path.join(INPUT_DIR, OUTPUT_FILE)
    total_chars = 0
    error_files = []
    file_stats = []  # 记录每个文件的字符数
    
    try:
        with open(output_path, 'w', encoding='utf-8') as outfile:
            for filename in sorted_files:
                filepath = os.path.join(INPUT_DIR, filename)
                try:
                    encoding = detect_encoding(filepath)
                    with open(filepath, 'r', encoding=encoding) as infile:
                        content = infile.read()
                    
                    content = process_text(content, ENABLE_QUOTE_NEWLINE)
                    outfile.write(content)
                    
                    if not content.endswith('\n'):
                        outfile.write('\n')
                    
                    char_count = len(content)
                    total_chars += char_count
                    file_stats.append({'name': filename, 'chars': char_count})
                    
                except Exception as e:
                    error_files.append((filename, str(e)))
                    continue
        
        # ================= 统计分析逻辑 =================
        print("\n" + "=" * 60)
        print("📊 统计分析结果")
        print("=" * 60)
        
        n = len(file_stats)
        print(f"• 总字符数: {total_chars:,}")
        
        if n > 4:
            sorted_stats = sorted(file_stats, key=lambda x: x['chars'])
            trimmed_stats = sorted_stats[2:-2]
            trimmed_total = sum(item['chars'] for item in trimmed_stats)
            avg_chars = trimmed_total / len(trimmed_stats)
            print(f"• 剔除极值(去2最高/2最低)后平均字符数: {avg_chars:,.0f}")
        else:
            avg_chars = sum(item['chars'] for item in file_stats) / n
            print(f"• 平均字符数 (文件数≤4，未剔除极值): {avg_chars:,.0f}")
        
        lower_bound = avg_chars * (1 - DEVIATION_THRESHOLD)
        upper_bound = avg_chars * (1 + DEVIATION_THRESHOLD)
        
        outliers = []
        for item in file_stats:
            if item['chars'] < lower_bound or item['chars'] > upper_bound:
                deviation = ((item['chars'] - avg_chars) / avg_chars) * 100
                outliers.append({
                    'name': item['name'],
                    'chars': item['chars'],
                    'deviation': deviation
                })
        
        if outliers:
            print(f"\n⚠️  发现 {len(outliers)} 个字符数偏离平均值 {DEVIATION_THRESHOLD*100:.0f}% 以上的文件:")
            print("-" * 65)
            print(f"{'文件名':<45} | {'字符数':<10} | {'偏离度'}")
            print("-" * 65)
            outliers.sort(key=lambda x: abs(x['deviation']), reverse=True)
            for out in outliers:
                sign = "+" if out['deviation'] > 0 else ""
                print(f"{out['name']:<45} | {out['chars']:<10,} | {sign}{out['deviation']:.1f}%")
            print("-" * 65)
        else:
            print(f"\n✅ 所有文件字符数分布均匀，无偏离平均值 {DEVIATION_THRESHOLD*100:.0f}% 以上的异常文件。")
        # ================= 醒目输出缺失文件 =================
        if missing_parts:
            missing_str = ', '.join([f'part{n}' for n in missing_parts])
            print("️  警告：发现缺失文件！")
            print(f"📉 缺失的 Part 编号: {missing_str}")
            print(f"📉 共缺失 {len(missing_parts)} 个文件")
        else:
            print("\n✅ 文件连续，无缺失。\n")
        # ====================================================

        print(f"\n🎉 合并完成！输出路径: {os.path.abspath(output_path)}")
        
        if error_files:
            print(f"\n❌ 以下 {len(error_files)} 个文件处理失败:")
            for fname, err in error_files:
                print(f"  • {fname}: {err}")
                
    except PermissionError:
        print(f"\n❌ 权限错误：无法写入文件 {output_path}，请确保文件未被其他程序占用。")
    except Exception as e:
        print(f"\n❌ 发生未知错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()