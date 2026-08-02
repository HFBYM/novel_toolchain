#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import json
import time
import requests
from pathlib import Path

# ==================== 模型选择（二选一） ====================
SELECTED_MODEL = "qwen3.5:4b"   # ← 在这里切换模型

# ==================== 配置区（根据模型自动调整） ====================
OLLAMA_URL = "http://localhost:11434/api/chat"

BASE_DIR = Path("./Python_Code")
NOVEL_PATH = BASE_DIR / "novel" / "for_polish" / "novel.txt"
RULES_PATH = BASE_DIR / "novel" / "for_polish" /"末日重启" / "polish_rules.txt"
PROGRESS_FILE = BASE_DIR / "novel" / "polished" / f"{NOVEL_PATH.stem}_polish_progress.json"
REQUEST_TIMEOUT = 600
MAX_RETRIES = 3

USE_ADDITIONAL_AS_SYSTEM = True

ADDITIONAL_PROMPT = ("""
【最高优先级死命令！】
绝对禁止在输出开头或任何地方生成超过两句话的大段落！
从你输出的第一个字符开始，每 1 到 2 个句子（以句号、问号、叹号结尾）结束后，必须立即换行！

【其他严格限制】
1. 绝对禁止改变设定、人名、地名、物品名。
2. 严禁使用破折号‘——’，如有请用逗号或句号代替。
3. 语句必须通顺，超过二十字时必须用逗号自然断开，禁止出现连续二十字无标点的情况。
4. 直接输出纯文本润色结果，不要任何解释，保留章节名。

【分行规则与节奏】
- 单句行：语义松散、独立表意的句子，单独成行。
- 双句行：语义紧密、逻辑连贯的句子（如动作连贯、因果递进），合并为两句话后成行。
- 比例要求：除对话外，单句行必须多于双句行，双句行占比至少两成，两者必须交替存在。每行绝对不能超过两句话（严禁三句成行）。

【你必须严格模仿的输出格式示例】
天地间恢复正常后没有一个人有动静，除了正在为武舞治疗的文远南。吴峰已经止住了血，但断臂被武舞刺穿，几乎没有再接回去的可能。
就算吴蝶的大天使职业再厉害，现在这种情况也使不出来。
武舞从昏迷中醒了过来，脸色苍白，一说话就感到口腔中浓浓的血腥味。她看见倒在地上的吴九笛，眼中交织着对叶言的感激、对自己的失望，以及对即将到来的凉城之行的恐惧。
照这样下去，她真的能将凉城的家人救出来吗？

【结尾特殊警告】
润色到全文后四分之一时，必须更严格地执行每行两句上限；严禁结尾剩余内容合并为一行，必须拆解为多个不超过两句的独立行。
""")

THINK_MODE = False
if SELECTED_MODEL == "qwen3.5:9b":
    MODEL = "qwen3.5:9b"
    NUM_CTX = 16384
    MAX_CHUNK_CHARS = 4000
    OVERLAP_CHARS = 150
    TEMPERATURE = 0.2
    TOP_P = 0.9
    TOP_K = None
    REPEAT_PENALTY = 1.05
    NUM_PREDICT = 4500
elif SELECTED_MODEL == "qwen3.5:4b":
    MODEL = "qwen3.5:4b"
    NUM_CTX = 20000
    MAX_CHUNK_CHARS = 1200       # 4B 模型的黄金注意力区间
    OVERLAP_CHARS = 150          # 仅用于提取背景上下文，不混入待润色文本
    TEMPERATURE = 0.2
    TOP_P = 0.9
    TOP_K = None
    REPEAT_PENALTY = 1.1
    NUM_PREDICT = 1800
else:
    raise ValueError(f"不支持的模型: {SELECTED_MODEL}")


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


def split_into_chapters(text):
    chapter_keywords = (
        r"第\s*[\d\u4e00-\u9fa5]+\s*章"
        r"|序章|终章|番外章"
        r"|楔子|引子|前言|序言|开篇"
        r"|尾声|后记|结语|结局"
        r"|番外|外传|特别篇|番外篇"
    )
    pattern = rf"(?=(?:^|\n)\s*(?:{chapter_keywords}))"
    chapters = re.split(pattern, text)
    return [ch.strip() for ch in chapters if ch.strip()]


def chunk_text(text, max_chars=MAX_CHUNK_CHARS):
    """
    核心修复：干净切分。确保每个 chunk 都是完整句子的结尾，
    下一个 chunk 必然是全新的开头，绝不包含上一块的尾巴，从根本上杜绝重复和半句幻觉。
    """
    if len(text) <= max_chars:
        return [text]
    
    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars
        if end >= len(text):
            chunks.append(text[start:])
            break
        
        # 在 end 附近（往前退 200 个字符）寻找最佳切分点
        search_start = max(start, end - 200)
        search_area = text[search_start:end]
        
        best_split = -1
        # 优先找换行，其次找句末标点
        for char in ['\n', '。', '！', '？']:
            idx = search_area.rfind(char)
            if idx > best_split:
                best_split = idx
        
        if best_split != -1:
            actual_end = search_start + best_split + 1
            chunks.append(text[start:actual_end])
            start = actual_end  # ⚠️ 关键：不重叠切分，保证新 chunk 是干净的新开头
        else:
            # 极端情况：没找到，硬切
            chunks.append(text[start:end])
            start = end
            
    return chunks


def call_ollama(prompt):
    messages = []
    if USE_ADDITIONAL_AS_SYSTEM:
        messages.append({"role": "system", "content": ADDITIONAL_PROMPT})
    messages.append({"role": "user", "content": prompt})
    
    options = {
        "temperature": TEMPERATURE,
        "num_ctx": NUM_CTX
    }
    if TOP_P is not None: options["top_p"] = TOP_P
    if TOP_K is not None: options["top_k"] = TOP_K
    if REPEAT_PENALTY is not None: options["repeat_penalty"] = REPEAT_PENALTY
    if NUM_PREDICT is not None: options["num_predict"] = NUM_PREDICT

    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "think": THINK_MODE,
        "options": options
    }

    last_exception = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(OLLAMA_URL, json=payload, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            content = data["message"]["content"].strip()
            if not content:
                print("⚠️ 模型返回了空内容，正在重试...")
                raise ValueError("Empty response")
            return content
        except Exception as e:
            last_exception = e
            print(f"⚠️ 生成失败 (第 {attempt}/{MAX_RETRIES} 次): {e}")
            time.sleep(5)
    raise RuntimeError(f"多次重试后仍然失败: {last_exception}")


def load_progress():
    if not PROGRESS_FILE.exists():
        return []
    if PROGRESS_FILE.stat().st_size == 0:
        return []
    try:
        with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get("processed_chapters", [])
    except Exception as e:
        print(f"⚠️ 进度文件损坏 ({e})，将备份并重置进度")
        PROGRESS_FILE.rename(PROGRESS_FILE.with_suffix(".json.bak"))
        return []


def save_progress(processed_list):
    RULES_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = PROGRESS_FILE.with_suffix(".json.tmp")
    def sort_key(x):
        parts = x.split('_')
        return int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    sorted_list = sorted(processed_list, key=sort_key)
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump({"processed_chapters": sorted_list}, f, ensure_ascii=False, indent=2)
        tmp_path.replace(PROGRESS_FILE)
    except Exception as e:
        print(f"⚠️ 保存进度失败: {e}")
        if tmp_path.exists(): tmp_path.unlink()


def format_time(seconds):
    if seconds < 60: return f"{seconds:.1f}秒"
    elif seconds < 3600: return f"{int(seconds // 60)}分{seconds % 60:.1f}秒"
    else: return f"{int(seconds // 3600)}小时{int((seconds % 3600) // 60)}分"


# ==================== 主流程 ====================
def main():
    print(f"🤖 当前模型: {MODEL} | USE_ADDITIONAL_AS_SYSTEM: {USE_ADDITIONAL_AS_SYSTEM}")
    
    if not NOVEL_PATH.exists():
        print(f"❌ 小说文件不存在: {NOVEL_PATH}"); return
    if not RULES_PATH.exists():
        print(f"❌ 润色规则文件不存在: {RULES_PATH}"); return

    output_dir = BASE_DIR / "novel" / "polished"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{NOVEL_PATH.stem}_polish{NOVEL_PATH.suffix}"
    
    try:
        novel_text = load_text(NOVEL_PATH)
    except ValueError as e:
        print(f"❌ {e}"); return

    polish_rules = load_text(RULES_PATH)
    chapters = split_into_chapters(novel_text)
    total_chapters = len(chapters)
    
    if total_chapters == 0:
        print("❌ 未检测到章节，请检查文本格式。"); return

    processed_set = set(load_progress())
    write_mode = 'a' if processed_set else 'w'
    print(f"📚 检测到 {total_chapters} 个章节 | 🔄 已完成 {len(processed_set)} 章\n")

    total_start_time = time.time()
    chapter_times = []

    with open(output_path, write_mode, encoding='utf-8') as out_f:
        for idx, chapter in enumerate(chapters, start=1):
            chapter_id = f"chapter_{idx}"
            if chapter_id in processed_set:
                print(f"⏭️  第 {idx}/{total_chapters} 章 已处理，跳过"); continue

            chapter_title = chapter.split('\n')[0][:20].strip()
            print(f"📖 正在处理 [{idx}/{total_chapters}] {chapter_title}...")
            chapter_start = time.time()

            sub_chunks = chunk_text(chapter)
            if len(sub_chunks) > 1:
                print(f"   ↳ 章节过长，分为 {len(sub_chunks)} 段处理")

            polished_parts = []
            prev_overlap = ""

            for ci, new_text in enumerate(sub_chunks, start=1):
                # ⚠️ 核心修复：隔离背景前文，严禁模型重复输出
                overlap_section = ""
                if OVERLAP_CHARS > 0 and prev_overlap:
                    overlap_section = f"""【前文最后两句】（仅供理解上下文，绝对禁止在你的输出中重复或续写这部分内容）：
{prev_overlap}

"""

                if USE_ADDITIONAL_AS_SYSTEM:
                    prompt = f"""你是一个严格遵守要求的资深小说润色专家。
【最高指令】如果【待润色新文本】的开头包含章节名（如“第一章 XXX”），必须将其原样保留在输出的第一行，绝对禁止删除、修改或合并章节名！
请严格遵循下方的【润色规则】，只润色【待润色新文本】。

【润色规则】
{polish_rules}

【强制警告】
1. 必须从输出的第一句话开始就严格执行换行。
2. 绝对禁止重复输出【前文最后两句】中的任何内容！只润色【待润色新文本】。

{overlap_section}【待润色新文本】
{new_text}

润色后的文本（从第一句开始严格换行）："""
                else:
                    prompt = f"""你是一个严格遵守要求的资深小说润色专家。
【最高指令】如果【待润色新文本】的开头包含章节名（如“第一章 XXX”），必须将其原样保留在输出的第一行，绝对禁止删除、修改或合并章节名！

【润色总规则】
{ADDITIONAL_PROMPT}

【润色规则】
{polish_rules}

【强制警告】绝对禁止重复输出【前文最后两句】中的任何内容！只润色【待润色新文本】。

{overlap_section}【待润色新文本】
{new_text}

润色后的文本（从第一句开始严格换行）："""

                try:
                    result = call_ollama(prompt)
                    # 清理 Markdown
                    result = re.sub(r'^#{1,6}\s+', '', result, flags=re.MULTILINE)
                    result = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', result)
                    result = re.sub(r'`([^`]+)`', r'\1', result)
                    polished_parts.append(result)

                    # ⚠️ 核心修复：智能提取最后两句话作为下一次的 overlap，确保是完整句子
                    sentences = re.split(r'([。！？\n])', result)
                    sentences = [s for s in sentences if s.strip()]
                    if len(sentences) >= 4:
                        prev_overlap = "".join(sentences[-4:]) # 取最后两个句子及其标点
                    else:
                        prev_overlap = result[-150:] if len(result) > 150 else result

                    print(f"   ✓ 段 {ci}/{len(sub_chunks)} 完成", end='', flush=True)
                except Exception as e:
                    print(f"\n❌ 第 {idx} 章 第 {ci} 段 处理失败: {e}"); raise

            full_polished_chapter = "\n".join(polished_parts)
            out_f.write(full_polished_chapter + "\n\n")
            out_f.flush()

            processed_set.add(chapter_id)
            save_progress(list(processed_set))

            chapter_elapsed = time.time() - chapter_start
            chapter_times.append((chapter_id, chapter_elapsed))
            print(f"\n   ✅ 第 {idx}/{total_chapters} 章已写入 | ⏱️ 用时: {format_time(chapter_elapsed)}")

    total_elapsed = time.time() - total_start_time
    print("\n" + "=" * 60)
    print("🎉 全部章节润色完成！")
    print(f"输出文件: {output_path} | 总用时: {format_time(total_elapsed)}")
    print("=" * 60)


if __name__ == "__main__":
    main()