import os
import re
import time
import random
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from fake_useragent import UserAgent
    ua = UserAgent()
except ImportError:
    ua = None

# ================= 配置项 =================
BASE_URL = "http://m.bookszw.com"
CATALOG_PAGES = ["http://m.bookszw.com/137/137401/"] + [
    f"http://m.bookszw.com/137/137401_{i}/" for i in range(2, 48)
]

OUTPUT_FILE = "./Python_Code/novel/getted_from_internet/吞噬星空之虫族主宰/吞噬星空之虫族主宰.txt"
LOG_FILE = "./Python_Code/novel/getted_from_internet/吞噬星空之虫族主宰/done_bookszw_137401.log"
os.makedirs("./Python_Code/novel/getted_from_internet/吞噬星空之虫族主宰", exist_ok=True)

# 会话（不自动重试状态码，由 safe_request 处理）
session = requests.Session()
retry = Retry(
    total=0,
    backoff_factor=0.5,
    status_forcelist=[],
    allowed_methods=["GET"]
)
adapter = HTTPAdapter(max_retries=retry)
session.mount("http://", adapter)
session.mount("https://", adapter)

def get_headers():
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "max-age=0",
    }
    if ua:
        headers["User-Agent"] = ua.random
    else:
        headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    return headers

session.headers.update(get_headers())

# 已完成章节 ID
if os.path.exists(LOG_FILE):
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        DONE_IDS = set(line.strip() for line in f if line.strip())
else:
    DONE_IDS = set()

# 广告词（按需调整）
AD_TEXTS = [
    "一秒记住【笔趣阁小说网】",
    "biquge345.com",
    "更新快，无弹窗！",
    "零点看书",
    "www.bookszw.com",
    "m.bookszw.com"
]
# =========================================


def safe_request(url, referer=None, max_retries=3):
    """带重试和随机延时的请求"""
    for attempt in range(max_retries):
        try:
            headers = get_headers()
            if referer:
                headers["Referer"] = referer
            resp = session.get(url, headers=headers, timeout=30)
            if resp.status_code == 200:
                return resp
            else:
                print(f"⚠️ 状态码 {resp.status_code}，重试 {attempt+1}/{max_retries}：{url}")
        except Exception as e:
            print(f"⚠️ 请求异常：{e}，重试 {attempt+1}/{max_retries}：{url}")
        time.sleep(random.uniform(2, 4))
    return None


def download_catalog_page(url):
    """下载目录页，带随机延迟"""
    time.sleep(random.uniform(0.5, 1.5))
    resp = safe_request(url, referer=BASE_URL)
    if resp:
        resp.encoding = resp.apparent_encoding or "utf-8"
        return (url, resp.text)
    else:
        print(f"❌ 目录页下载失败：{url}")
        return (url, None)


def get_chapter_list():
    """下载所有目录页并解析正文部分的章节链接"""
    print("🚀 开始下载目录页...")
    pages_data = {}

    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_url = {executor.submit(download_catalog_page, url): url for url in CATALOG_PAGES}
        for future in as_completed(future_to_url):
            url, text = future.result()
            if text:
                pages_data[url] = text
                print(f"  ✅ 下载完成：{url}")

    # 慢速重试失败的页面
    failed_urls = [url for url in CATALOG_PAGES if url not in pages_data]
    if failed_urls:
        print(f"⚠️ 有 {len(failed_urls)} 个目录页失败，开始慢速重试...")
        for url in failed_urls:
            time.sleep(random.uniform(5, 8))
            resp = safe_request(url, referer=BASE_URL, max_retries=2)
            if resp and resp.status_code == 200:
                resp.encoding = resp.apparent_encoding or "utf-8"
                pages_data[url] = resp.text
                print(f"  🔄 重试成功：{url}")
            else:
                print(f"  ❌ 重试仍失败：{url}")

    print("📘 解析目录页...")
    chapters = []
    for url in CATALOG_PAGES:
        text = pages_data.get(url)
        if not text:
            continue

        soup = BeautifulSoup(text, "html.parser")

        # 定位“正文”区域
        section = None
        for h2 in soup.find_all("h2", class_="layout-tit"):
            if "正文" in h2.get_text():
                section = h2.find_next("div", class_="section-box")
                break
        if not section:
            print(f"  ⚠️ 未找到正文章节区域：{url}")
            continue

        ul = section.find("ul", class_="section-list")
        if not ul:
            continue

        for a in ul.find_all("a"):
            href = a.get("href")
            title = a.get_text(strip=True)
            if not href:
                continue

            full_url = urljoin(BASE_URL, href)
            cid = href.split("/")[-1].replace(".html", "")
            chapters.append((cid, title, full_url))

    # 去重
    seen = set()
    unique_chapters = []
    for cid, title, url in chapters:
        if cid not in seen:
            seen.add(cid)
            unique_chapters.append((cid, title, url))
    chapters = unique_chapters

    print(f"📚 共解析到 {len(chapters)} 个正文章节链接")
    return chapters


def fetch_chapter(chapter):
    """抓取单章（两页），拼接并清洗"""
    cid, title, url = chapter
    if cid in DONE_IDS:
        print(f"⏩ 跳过：{title}")
        return None

    content_parts = []
    page_urls = [url, url.replace(".html", "_2.html")]

    for idx, page_url in enumerate(page_urls, 1):
        resp = safe_request(page_url, referer=url)
        if not resp:
            print(f"❌ 无响应：{title} 第{idx}页 → {page_url}")
            break
        if resp.status_code != 200:
            print(f"❌ 状态码 {resp.status_code}：{title} 第{idx}页")
            break

        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        content_div = soup.find("div", class_="content", id="content")
        if not content_div:
            print(f"⚠️ 未找到正文容器：{title} 第{idx}页")
            break

        text = content_div.get_text(separator="\n", strip=True)
        lines = text.split('\n')
        cleaned_lines = []
        for line in lines:
            stripped = line.strip()

            # 移除分页提示行（如“第一章 穿越吞噬星空 (第1/2页)”）
            if re.match(r'^第[一二三四五六七八九十百千\d]+章\s+.*\s*\(第\d+/\d+页\)', stripped):
                continue
            # 移除独立的章节标题行（如“第一章 穿越吞噬星空”）
            if re.match(r'^第[一二三四五六七八九十百千\d]+章\s+.+', stripped) and '页' not in stripped:
                continue
            # 移除“本章未完”提示
            if stripped == "（本章未完，请点击下一页继续阅读）":
                continue

            cleaned_lines.append(stripped)

        page_text = '\n'.join(cleaned_lines)
        # 清除广告
        for ad in AD_TEXTS:
            page_text = page_text.replace(ad, "")

        content_parts.append(page_text)
        time.sleep(random.uniform(0.5, 1.0))

    if not content_parts:
        print(f"❌ 未获得任何正文：{title}")
        return None

    full_text = "\n".join(content_parts)

    # 清理多余空行
    lines = full_text.split('\n')
    final_lines = []
    prev_empty = False
    for line in lines:
        stripped = line.strip()
        if stripped:
            final_lines.append(stripped)
            prev_empty = False
        else:
            if not prev_empty:
                final_lines.append('')
                prev_empty = True
    clean_content = '\n'.join(final_lines)

    return cid, title, clean_content


def main():
    chapters = get_chapter_list()
    if not chapters:
        print("❌ 没有解析到章节")
        return

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = executor.map(fetch_chapter, chapters)

        with open(OUTPUT_FILE, "a", encoding="utf-8") as f_out, \
             open(LOG_FILE, "a", encoding="utf-8") as f_log:

            for res in results:
                if not res:
                    continue
                cid, title, content = res
                f_out.write(f"{title}\n{content}\n\n")
                f_out.flush()
                f_log.write(f"{cid}\n")
                f_log.flush()
                print(f"✅ 完成：{title}")

    print("🎉 全部章节抓取完成！")


if __name__ == "__main__":
    main()