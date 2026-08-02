import re
import random
import os

# ==================== 配置（可直接修改） ====================
INPUT_FILE = r'.\Python_Code\novel\for_merge\末日重启_polish\ALL.txt'  # 输入文件路径
OUTPUT_DIR = r'.\Python_Code\novel\for_merge\末日重启_polish'          # 输出目录（留空则与输入同目录）

# ---------- 破折号处理配置 ----------
KEEP_RATIO = 0.05          # 随机保留破折号的比例（0~1）
PAIR_MAX_LEN = 50          # 成对破折号之间的最大字符数
NEW_SENTENCE_STARTS = {'他', '她', '它', '这', '那', '只见', '突然', '忽然', '可是', '但是',
                       '然而', '于是', '接着', '然后', '最后', '不过', '没想到', '谁知',
                       '哪知', '不料', '结果', '很快', '马上', '瞬间', '此时', '这时',
                       '现在', '之前', '之后', '从此', '果然', '难道', '居然', '竟然',
                       '总算', '终于', '其实', '只是', '或许', '也许'}

# ---------- 逗号插入精细控制配置 ----------
ENABLE_INSERT_COMMAS = False          # 是否启用逗号插入
USE_FINE_GRAINED = True              # 是否启用精细分组控制（若False则使用统一比例）

# 统一比例（当 USE_FINE_GRAINED = False 时使用）
UNIFIED_INSERT_RATIO = 0.3           # 统一插入比例（0~1）

# 精细分组配置：每组包含关键词列表和该组的插入比例
COMMA_GROUPS = [
    {
        'name': '时间顺序',
        'keywords': {'这时', '现在', '此时', '紧接着', '而后', '之后', '然后', '于是'},
        'ratio': 0.7                  # 该组关键词后插入逗号的比例
    },
    {
        'name': '转折因果',
        'keywords': {'可是', '但是', '然而', '不过', '其实', '因此', '所以', '那么', '而且', '并且', '只是', '结果', '总之'},
        'ratio': 0.7
    },
    {
        'name': '描述引出',
        'keywords': {'只见', '突然', '忽然', '瞬间', '顿时'},
        'ratio': 0.7
    },
    {
        'name': '其他常用',
        'keywords': {'换句话说', '此外', '也就是说', '既然如此'},
        'ratio': 0.8
    }
]

# 从分组中提取所有关键词（用于快速匹配），并构建关键词→比例映射
if USE_FINE_GRAINED:
    COMMA_KEYWORD_RATIO_MAP = {}
    for group in COMMA_GROUPS:
        for kw in group['keywords']:
            COMMA_KEYWORD_RATIO_MAP[kw] = group['ratio']
    COMMA_INSERT_KEYWORDS = set(COMMA_KEYWORD_RATIO_MAP.keys())
else:
    COMMA_INSERT_KEYWORDS = set()
    for group in COMMA_GROUPS:
        COMMA_INSERT_KEYWORDS.update(group['keywords'])
    # 统一比例将用在函数中

# ==========================================================


def find_paired_dashes(matches, text):
    """识别成对破折号，返回配对信息"""
    n = len(matches)
    pair_id = [None] * n
    used = [False] * n
    pair_counter = 0
    for i in range(n):
        if used[i]:
            continue
        for j in range(i+1, n):
            if used[j]:
                continue
            start = matches[i].end()
            end = matches[j].start()
            between = text[start:end]
            if '——' not in between and len(between) <= PAIR_MAX_LEN:
                pair_id[i] = (pair_counter, 'left')
                pair_id[j] = (pair_counter, 'right')
                used[i] = used[j] = True
                pair_counter += 1
                break
            else:
                if '——' in between:
                    break
    return pair_id


def should_keep(probability):
    return random.random() < probability


def reduce_dashes(text, keep_ratio=KEEP_RATIO):
    """处理破折号，替换为括号、删除或转换为其他标点"""
    dash_pattern = re.compile(r'——')
    matches = list(dash_pattern.finditer(text))
    if not matches:
        return text

    pair_info = find_paired_dashes(matches, text)
    keep_flags = [False] * len(matches)
    paired_groups = {}
    for i, info in enumerate(pair_info):
        if info is not None:
            pid, role = info
            if pid not in paired_groups:
                paired_groups[pid] = should_keep(keep_ratio)
            keep_flags[i] = paired_groups[pid]
        else:
            keep_flags[i] = should_keep(keep_ratio)

    result = []
    last_idx = 0
    for i, match in enumerate(matches):
        start, end = match.start(), match.end()
        result.append(text[last_idx:start])
        if keep_flags[i]:
            result.append('——')
        else:
            info = pair_info[i]
            if info is not None:
                role = info[1]
                if role == 'left':
                    result.append('（')
                else:
                    result.append('）')
            else:
                # 单个破折号替换规则
                if start == 0:
                    prev_char = '\n'
                else:
                    prev_char = text[start - 1]
                if end < len(text) and text[end] == '”':
                    result.append('……')
                elif prev_char in '。！？…' or prev_char == '\n' or start == 0:
                    result.append('')  # 删除
                else:
                    after_text = text[end:end+10]
                    match_word = re.match(r'[\u4e00-\u9fff]{1,2}', after_text)
                    if match_word:
                        word = match_word.group()
                        if word in NEW_SENTENCE_STARTS:
                            result.append('。')
                        else:
                            result.append('，')
                    else:
                        result.append('，')
        last_idx = end
    result.append(text[last_idx:])
    return ''.join(result)


def insert_commas(text, enable, unified_ratio, use_fine, ratio_map, keywords_set):
    """在关键词后插入逗号（支持精细分组控制）"""
    if not enable or not keywords_set:
        return text

    # 构建正则：匹配独立关键词（前后非汉字）
    pattern = re.compile(r'(?<![一-龥])(?:' + '|'.join(re.escape(kw) for kw in keywords_set) + r')(?![一-龥])')
    matches = list(pattern.finditer(text))
    if not matches:
        return text

    # 收集候选位置及对应的关键词
    candidates = []
    for m in matches:
        pos = m.end()
        keyword = text[m.start():m.end()]
        # 跳过不合理的插入位置
        if pos >= len(text):
            continue
        after = text[pos]
        if after in '。，！？、；：':
            continue
        if pos > 0 and text[pos-1] in '。，！？、；：':
            continue
        # 对于精细模式，获取该关键词的插入比例
        if use_fine:
            ratio = ratio_map.get(keyword, unified_ratio)  # 若未定义则使用统一比例
        else:
            ratio = unified_ratio
        candidates.append((pos, ratio))

    if not candidates:
        return text

    # 按比例随机选择插入位置
    selected_positions = []
    for pos, ratio in candidates:
        if random.random() < ratio:
            selected_positions.append(pos)

    if not selected_positions:
        return text

    # 从后往前插入，避免偏移
    selected_positions.sort(reverse=True)
    result = list(text)
    for pos in selected_positions:
        result.insert(pos, '，')
    return ''.join(result)


def main():
    if not os.path.exists(INPUT_FILE):
        print(f'错误：找不到文件 {INPUT_FILE}')
        return

    # 确定输出路径
    if OUTPUT_DIR:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        output_path = os.path.join(OUTPUT_DIR, 'ALL_reduced_dash_and_comma.txt')
    else:
        output_dir = os.path.dirname(INPUT_FILE)
        output_path = os.path.join(output_dir, 'ALL_reduced_dash_and_comma.txt')

    print('正在读取文件...')
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        text = f.read()

    random.seed(42)  # 固定种子以复现结果（可删除）

    # 第一步：处理破折号
    print(f'处理破折号，保留比例：{KEEP_RATIO*100}%')
    text = reduce_dashes(text, KEEP_RATIO)

    # 第二步：插入逗号
    if ENABLE_INSERT_COMMAS:
        if USE_FINE_GRAINED:
            print('启用精细控制，各组关键词及比例：')
            for group in COMMA_GROUPS:
                print(f"  [{group['name']}] 关键词数：{len(group['keywords'])}，比例：{group['ratio']*100}%")
        else:
            print(f'使用统一比例，比例：{UNIFIED_INSERT_RATIO*100}%')
        text = insert_commas(
            text,
            ENABLE_INSERT_COMMAS,
            UNIFIED_INSERT_RATIO,
            USE_FINE_GRAINED,
            COMMA_KEYWORD_RATIO_MAP if USE_FINE_GRAINED else {},
            COMMA_INSERT_KEYWORDS
        )
    else:
        print('逗号插入功能已关闭')

    print('正在写入新文件...')
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(text)

    print(f'处理完成！结果保存至：{output_path}')


if __name__ == '__main__':
    main()