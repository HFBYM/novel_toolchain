#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import json
import time
import requests
from pathlib import Path

# ==================== 模型选择（二选一） ====================
# 可选值: "qwen3.5:9b" 或 "qwen3.5:4b"
SELECTED_MODEL = "qwen3.5:4b"   # ← 在这里切换模型

# ==================== 配置区（根据模型自动调整） ====================
OLLAMA_URL = "http://localhost:11434/api/chat"

# 路径（小说路径可任意指定，输出自动生成）
BASE_DIR = Path("./Python_Code")
NOVEL_PATH = BASE_DIR / "novel" /"for_polish" /"novel.txt"
RULES_DIR = BASE_DIR / "polish_novel_toolchain"
RULES_PATH = RULES_DIR / "polish_rules.txt"     # 润色规则文件（UTF-8 保存）
PROGRESS_FILE = RULES_DIR / "progress.json"

# 请求超时与重试
REQUEST_TIMEOUT = 600
MAX_RETRIES = 3

# 模型专属参数
if SELECTED_MODEL == "qwen3.5:9b":
    MODEL = "qwen3.5:9b"
    NUM_CTX = 16384
    MAX_CHUNK_CHARS = 4000
    OVERLAP_CHARS = 100
    TEMPERATURE = 0.3
    TOP_P = None
    TOP_K = None
    REPEAT_PENALTY = None
    NUM_PREDICT = None
    THINK_MODE = False
    
    SYSTEM_PROMPT = (
    "你是一个严格听从命令的小说润色工具。"
    "绝对禁止：改变设定、人名、地名、物品名；修改主要剧情；每段使用超过一个破折号。"
    "必须输出纯文本，直接给出润色后的内容，不要任何解释。"
    "必须保留章节名和原文的段落结构。"
    "必须保持标点自然，语句通顺，段落长度适中。"
)
elif SELECTED_MODEL == "qwen3.5:4b":
    MODEL = "qwen3.5:4b"
    NUM_CTX = 20000
    THINK_MODE = False
    
    TEMPERATURE = 0.2        # 略微降低温度，增加稳定性
    TOP_P = 0.9
    TOP_K = None             # 不用 top_k
    REPEAT_PENALTY = 1.05    # 轻微防止重复
    MAX_CHUNK_CHARS = 2000   # 缩小片段，提高注意力
    OVERLAP_CHARS = 200
    NUM_PREDICT = 2500       # 对应 2000 字输出
    
    SYSTEM_PROMPT = (
        "你是一个严格的小说润色工具。"
        "绝对禁止：改变剧情、设定、人名、地名、物品名；每段使用超过一个破折号。"
        "直接输出纯文本润色结果，不要任何解释，保留章节名。"
        "格式风格：像正常出版小说一样自然分段。语义紧密的相邻短句应合并成一个段落，避免连续多句独立成段。段落长度灵活，以叙事节奏为准。"
        "每句话尽量在15~25字之间，长短句搭配，读起来流畅。超过25字时请自然地在适当位置用逗号断开，不要出现连续25字无标点的情况。"
    )
#     SYSTEM_PROMPT = (
#     "你是一个严格听从命令的小说润色工具。"
#     "绝对禁止：改变设定、人名、地名、物品名；修改主要剧情。"
#     "必须输出纯文本，直接给出润色后的内容，不要任何解释。"
#     "必须保留原文的段落结构。"
# )
else:
    raise ValueError(f"不支持的模型: {SELECTED_MODEL}")

# ==================== 系统级指令（最高优先级） ====================
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
    pattern = r'(?=第[\u4e00-\u9fff\d]+章)'
    chapters = re.split(pattern, text)
    return [ch.strip() for ch in chapters if ch.strip()]

def chunk_text(text, max_chars=MAX_CHUNK_CHARS, overlap=OVERLAP_CHARS):
    if len(text) <= max_chars:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars
        chunk = text[start:end]
        chunks.append(chunk)
        if end >= len(text):
            break
        start = end - overlap
    return chunks

def call_ollama(prompt):
    """调用 Ollama，自动包含 system 消息"""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt}
    ]
    options = {
        "temperature": TEMPERATURE,
        "num_ctx": NUM_CTX
    }
    if TOP_P is not None:
        options["top_p"] = TOP_P
    if TOP_K is not None:
        options["top_k"] = TOP_K
    if REPEAT_PENALTY is not None:
        options["repeat_penalty"] = REPEAT_PENALTY
    if NUM_PREDICT is not None:
        options["num_predict"] = NUM_PREDICT

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
            return data["message"]["content"].strip()
        except Exception as e:
            last_exception = e
            print(f"⚠️ 生成失败 (第 {attempt}/{MAX_RETRIES} 次): {e}")
            time.sleep(5)
    raise RuntimeError(f"多次重试后仍然失败: {last_exception}")

def load_progress():
    if not PROGRESS_FILE.exists():
        return []
    if PROGRESS_FILE.stat().st_size == 0:
        print("⚠️ 进度文件为空，视为新任务开始")
        return []
    try:
        with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get("processed_chapters", [])
    except (json.JSONDecodeError, Exception) as e:
        print(f"⚠️ 进度文件损坏 ({e})，将备份并重置进度")
        backup_path = PROGRESS_FILE.with_suffix(".json.bak")
        PROGRESS_FILE.rename(backup_path)
        return []

def save_progress(processed_list):
    RULES_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = PROGRESS_FILE.with_suffix(".json.tmp")
    # 按章节序号排序后再保存
    sorted_list = sorted(processed_list, key=lambda x: int(x.split('_')[1]))
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump({"processed_chapters": sorted_list}, f, ensure_ascii=False, indent=2)
        tmp_path.replace(PROGRESS_FILE)
    except Exception as e:
        print(f"⚠️ 保存进度失败: {e}")
        if tmp_path.exists():
            tmp_path.unlink()

def format_time(seconds):
    if seconds < 60:
        return f"{seconds:.1f}秒"
    elif seconds < 3600:
        mins = int(seconds // 60)
        secs = seconds % 60
        return f"{mins}分{secs:.1f}秒"
    else:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        return f"{hours}小时{mins}分"

# ==================== 主流程 ====================
def main():
    print(f"🤖 当前模型: {MODEL}")
    print(f"   Temperature: {TEMPERATURE}", end="")
    if TOP_P: print(f", top_p: {TOP_P}", end="")
    if TOP_K: print(f", top_k: {TOP_K}", end="")
    if REPEAT_PENALTY: print(f", repeat_penalty: {REPEAT_PENALTY}", end="")
    if NUM_PREDICT: print(f", max_tokens: {NUM_PREDICT}", end="")
    print(f", num_ctx: {NUM_CTX}\n")

    if not NOVEL_PATH.exists():
        print(f"❌ 小说文件不存在: {NOVEL_PATH}")
        return
    if not RULES_PATH.exists():
        print(f"❌ 润色规则文件不存在: {RULES_PATH}")
        print("   请创建该文件并写入润色要求（UTF-8 编码），然后重新运行脚本。")
        return

    stem = NOVEL_PATH.stem
    suffix = NOVEL_PATH.suffix
    output_path = BASE_DIR/"novel"/"polished"/ f"{stem}_polish{suffix}"
    print(f"📥 输入文件: {NOVEL_PATH}")
    print(f"📤 输出文件: {output_path}")

    try:
        novel_text = load_text(NOVEL_PATH)
    except ValueError as e:
        print(f"❌ {e}")
        return

    polish_rules = load_text(RULES_PATH)

    chapters = split_into_chapters(novel_text)
    total_chapters = len(chapters)
    print(f"📚 检测到 {total_chapters} 个章节")
    if total_chapters == 0:
        print("❌ 未检测到章节，请检查格式（需包含“第x章”）")
        return

    processed_chapters = load_progress()
    processed_set = set(processed_chapters)
    write_mode = 'a' if processed_set else 'w'
    if processed_set:
        print(f"🔄 断点续传：已完成 {len(processed_set)}/{total_chapters} 章")
    else:
        print("✨ 全新开始，将创建输出文件")

    total_start_time = time.time()
    chapter_times = []

    with open(output_path, write_mode, encoding='utf-8') as out_f:
        for idx, chapter in enumerate(chapters, start=1):
            chapter_id = f"chapter_{idx}"
            if chapter_id in processed_set:
                print(f"⏭️  第 {idx}/{total_chapters} 章 已处理，跳过")
                continue

            print(f"\n📖 正在处理第 {idx}/{total_chapters} 章...")
            chapter_start = time.time()

            if len(chapter) > MAX_CHUNK_CHARS:
                sub_chunks = chunk_text(chapter)
                print(f"   ↳ 章节过长，分为 {len(sub_chunks)} 段处理")
            else:
                sub_chunks = [chapter]

            polished_parts = []
            prev_overlap = ""

            for ci, chunk in enumerate(sub_chunks, start=1):
                overlap_section = ""
                if OVERLAP_CHARS > 0 and prev_overlap:
                    overlap_section = f"\n【前文衔接片段】（仅供上下文参考，无需润色，不要输出）\n{prev_overlap}\n"

                prompt = f"""你是一位资深小说润色专家。请严格遵循下方的【润色规则】，对【待润色文本】进行文笔提升。

【润色规则】
{polish_rules}{overlap_section}

【强制警告】以上规则必须逐条严格遵守，违反任何一条均为不合格输出。
【待润色文本】
{chunk}

润色后的文本："""

                try:
                    result = call_ollama(prompt)
                    # 清理可能残留的 Markdown 符号
                    result = re.sub(r'^#{1,6}\s+', '', result, flags=re.MULTILINE)
                    result = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', result)
                    result = re.sub(r'`([^`]+)`', r'\1', result)
                    polished_parts.append(result)

                    if OVERLAP_CHARS > 0 and len(sub_chunks) > 1 and ci < len(sub_chunks):
                        prev_overlap = result[-OVERLAP_CHARS:] if len(result) > OVERLAP_CHARS else result
                    else:
                        prev_overlap = ""

                    print(f"   ✓ 段 {ci}/{len(sub_chunks)} 完成", end='', flush=True)
                except Exception as e:
                    print(f"\n❌ 第 {idx} 章 第 {ci} 段 处理失败: {e}")
                    raise

            full_polished_chapter = "\n".join(polished_parts)
            out_f.write(full_polished_chapter + "\n\n")
            out_f.flush()

            processed_set.add(chapter_id)
            processed_chapters = list(processed_set)
            save_progress(processed_chapters)

            chapter_elapsed = time.time() - chapter_start
            chapter_times.append((chapter_id, chapter_elapsed))
            print(f"   ✅ 第 {idx}/{total_chapters} 章已写入")
            print(f"   ⏱️  本章用时: {format_time(chapter_elapsed)}")

    total_elapsed = time.time() - total_start_time
    print("\n" + "=" * 50)
    print("🎉 全部章节润色完成！")
    print(f"输出文件: {output_path}")
    print(f"总用时: {format_time(total_elapsed)}")
    if chapter_times:
        print("\n各章用时详情（仅本次处理）:")
        for ch_id, elapsed in chapter_times:
            print(f"  {ch_id}: {format_time(elapsed)}")
    print("=" * 50)

if __name__ == "__main__":
    main()
