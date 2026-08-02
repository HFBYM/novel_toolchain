// ==UserScript==
// @name         DeepSeek 自动润色助手 v7.5（附件上传 + 回车发送）
// @namespace    http://tampermonkey.net/
// @version      7.5
// @description  批量上传文件（附件形式）并润色，自动下载；后台实时检测回复；上传后等待1秒，使用回车键发送
// @author       You
// @match        https://chat.deepseek.com/*
// @match        https://deepseek.com/*
// @grant        GM_download
// ==/UserScript==

(function () {
    'use strict';

    // ---------- 选择器 ----------
    const SELECTORS = {
        fileInput: [
            'input[type="file"]',
            '.ds-file-input',
            '[data-testid="file-input"]',
            'input[accept*="image/*"], input[accept*=".pdf"], input[accept*=".txt"]'
        ],
        textarea: [
            'textarea[placeholder*="消息"]',
            'textarea[placeholder*="输入"]',
            'textarea[placeholder*="提问"]',
            'textarea[placeholder*="Send a message"]',
            'textarea',
            'div[contenteditable="true"]',
            'div[role="textbox"]',
            '[contenteditable="true"]'
        ],
        sendButton: [
            'button[aria-label="发送"]',
            'button[aria-label="Send"]',
            'button[type="submit"]',
            'button[data-testid="send-button"]',
            '.ds-send-button',
            '.chat-input-send-btn',
            'button'
        ]
    };

    const delay = ms => new Promise(r => setTimeout(r, ms));

    // 全局取消标志
    let cancelRequested = false;
    let lastDownloadedContent = null;
    const downloadCache = new Map();
    const CACHE_DURATION = 10000;

    // ---------- 工具函数 ----------
    async function findElementAsync(selectors, context = document, maxRetries = 10, retryInterval = 500) {
        for (let i = 0; i < maxRetries; i++) {
            const el = findElement(selectors, context);
            if (el) return el;
            await delay(retryInterval);
        }
        return null;
    }

    function findElement(selectors, context = document) {
        for (const sel of selectors) {
            try {
                const el = context.querySelector(sel);
                if (el) return el;
            } catch (e) { }
        }
        if (selectors === SELECTORS.sendButton) {
            const allBtns = context.querySelectorAll('button');
            for (const btn of allBtns) {
                const text = btn.innerText.trim();
                if (text.includes('发送') || text.includes('Send') || text === '停止') {
                    return btn;
                }
            }
        }
        return null;
    }

    function getFileInput() {
        for (const sel of SELECTORS.fileInput) {
            const el = document.querySelector(sel);
            if (el) return el;
        }
        const allInputs = document.querySelectorAll('input[type="file"]');
        return allInputs.length ? allInputs[0] : null;
    }

    function setFileInput(file) {
        const fileInput = getFileInput();
        if (!fileInput) return false;
        const dataTransfer = new DataTransfer();
        dataTransfer.items.add(file);
        fileInput.files = dataTransfer.files;
        fileInput.dispatchEvent(new Event('change', { bubbles: true }));
        return true;
    }

    // ---------- 回车发送函数 ----------
    function sendWithEnter(textarea) {
        textarea.focus();
        // 触发 keydown 事件（Enter）
        const keydownEvent = new KeyboardEvent('keydown', {
            key: 'Enter',
            code: 'Enter',
            keyCode: 13,
            which: 13,
            bubbles: true,
            cancelable: true,
            composed: true
        });
        textarea.dispatchEvent(keydownEvent);

        // 触发 keypress 事件（有些监听用 keypress）
        const keypressEvent = new KeyboardEvent('keypress', {
            key: 'Enter',
            code: 'Enter',
            keyCode: 13,
            which: 13,
            bubbles: true,
            cancelable: true,
            composed: true
        });
        textarea.dispatchEvent(keypressEvent);

        // 触发 keyup 事件（有些监听在 keyup 时提交）
        const keyupEvent = new KeyboardEvent('keyup', {
            key: 'Enter',
            code: 'Enter',
            keyCode: 13,
            which: 13,
            bubbles: true,
            cancelable: true,
            composed: true
        });
        textarea.dispatchEvent(keyupEvent);

        // 额外触发 input 和 change，确保状态更新
        textarea.dispatchEvent(new Event('input', { bubbles: true }));
        textarea.dispatchEvent(new Event('change', { bubbles: true }));
    }

    // ---------- 文本提取与思考过滤 ----------
    const BLOCK_TAGS = new Set([
        'P', 'DIV', 'SECTION', 'ARTICLE', 'MAIN', 'ASIDE',
        'H1', 'H2', 'H3', 'H4', 'H5', 'H6',
        'LI', 'UL', 'OL', 'DL', 'DT', 'DD',
        'TABLE', 'TR', 'BLOCKQUOTE', 'PRE', 'HR',
        'HEADER', 'FOOTER', 'NAV', 'FIGCAPTION', 'FIGURE'
    ]);

    function extractTextWithNewlines(node) {
        let text = '';
        node.childNodes.forEach(child => {
            if (child.nodeType === Node.TEXT_NODE) {
                text += child.textContent;
            } else if (child.nodeType === Node.ELEMENT_NODE) {
                const tagName = child.tagName;
                if (tagName === 'BR') {
                    text += '\n';
                } else if (tagName === 'PRE' || tagName === 'CODE') {
                    text += '\n' + child.textContent + '\n';
                } else if (BLOCK_TAGS.has(tagName)) {
                    text += '\n' + extractTextWithNewlines(child) + '\n';
                } else {
                    text += extractTextWithNewlines(child);
                }
            }
        });
        return text;
    }

    function filterAndExtractText(element) {
        const clone = element.cloneNode(true);
        clone.querySelectorAll('details, .ds-thinking, [data-thinking]').forEach(el => el.remove());
        clone.querySelectorAll('[class*="think"]').forEach(el => {
            if (el.textContent.trim().length >= 50) el.remove();
        });
        let text = extractTextWithNewlines(clone).trim();
        text = text.replace(/\n{3,}/g, '\n\n');
        return text;
    }

    function getLatestAssistantElement() {
        const selectors = [
            '[data-message-role="assistant"]',
            '[data-role="assistant"]',
            '.ds-message[data-role="assistant"]',
            '.ds-assistant-message',
            '[class*="assistant"][class*="message"]'
        ];
        let lastDiv = null;
        for (const sel of selectors) {
            const divs = document.querySelectorAll(sel);
            if (divs.length > 0) {
                lastDiv = divs[divs.length - 1];
                break;
            }
        }
        return lastDiv;
    }

    function getLatestAssistantReply() {
        const el = getLatestAssistantElement();
        if (!el) return null;
        const text = filterAndExtractText(el);
        return text.length >= 50 ? text : null;
    }

    function clickContinueButtonIfExists() {
        const selectors = [
            'button:has(svg):not([disabled])',
            '.ds-continue-button',
            '[data-testid="continue-generation"]',
            'div[role="button"]',
            'button'
        ];
        for (const sel of selectors) {
            const btns = document.querySelectorAll(sel);
            for (const btn of btns) {
                if (btn.innerText.includes('继续生成') ||
                    btn.innerText.includes('Continue') ||
                    btn.getAttribute('aria-label')?.includes('继续')) {
                    btn.click();
                    return true;
                }
            }
        }
        return false;
    }

    // ---------- 回复完成检测 ----------
    function waitForReplyComplete(timeoutMs = 600000) {
        return new Promise(resolve => {
            const INITIAL_DELAY = 25000;
            const STABLE_DURATION = 7000;
            let lastChangeTime = 0;
            let stableCheckTimer = null;
            let observer = null;
            let resolved = false;

            const finish = () => {
                if (resolved) return;
                resolved = true;
                if (observer) observer.disconnect();
                if (stableCheckTimer) clearTimeout(stableCheckTimer);
                resolve();
            };

            const scheduleStableCheck = () => {
                if (stableCheckTimer) clearTimeout(stableCheckTimer);
                stableCheckTimer = setTimeout(() => {
                    const now = Date.now();
                    if (now - lastChangeTime >= STABLE_DURATION) {
                        finish();
                    } else {
                        scheduleStableCheck();
                    }
                }, 1000);
            };

            const startObserving = () => {
                const container = document.querySelector('.ds-chat') || document.body;
                if (!container) {
                    const fallbackTimer = setInterval(() => {
                        const reply = getLatestAssistantReply();
                        if (reply && lastChangeTime && Date.now() - lastChangeTime >= STABLE_DURATION) {
                            clearInterval(fallbackTimer);
                            finish();
                        }
                    }, 2000);
                    return;
                }

                observer = new MutationObserver(() => {
                    lastChangeTime = Date.now();
                    clickContinueButtonIfExists();
                });

                observer.observe(container, {
                    childList: true,
                    subtree: true,
                    characterData: true,
                });

                lastChangeTime = Date.now();
                scheduleStableCheck();
            };

            setTimeout(() => finish(), timeoutMs);
            setTimeout(() => {
                startObserving();
            }, INITIAL_DELAY);
        });
    }

    // ---------- 下载与去重 ----------
    function downloadFile(filename, content, statusCallback) {
        if (!content) {
            statusCallback('⚠️ 保存失败：内容为空');
            return false;
        }

        const now = Date.now();
        const lastDownloadTime = downloadCache.get(filename);
        if (lastDownloadTime && (now - lastDownloadTime < CACHE_DURATION)) {
            statusCallback(`ℹ️ 跳过重复下载（文件名重复）: ${filename}`);
            return false;
        }
        downloadCache.set(filename, now);

        const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        try {
            if (typeof GM_download !== 'undefined') {
                GM_download({
                    url: url,
                    name: filename,
                    saveAs: false
                });
                statusCallback(`✅ 已下载: ${filename}`);
                setTimeout(() => URL.revokeObjectURL(url), 3000);
                return true;
            }
        } catch (e) {
            console.warn('GM_download 失败，回退到传统下载:', e);
        }
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.style.display = 'none';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        statusCallback(`✅ 已下载 (传统): ${filename}`);
        return true;
    }

    async function getEnhancedAssistantReply() {
        await delay(1000);
        await waitForReplyComplete(300000);
        return getLatestAssistantReply();
    }

    // ---------- 处理单个文件（附件上传 + 回车发送） ----------
    async function processOneFile(file, statusCallback) {
        // 读取文件内容（用于去重）
        const reader = new FileReader();
        const readPromise = new Promise((resolve, reject) => {
            reader.onload = ev => resolve(ev.target.result);
            reader.onerror = () => reject(new Error('文件读取失败'));
        });
        reader.readAsText(file, 'UTF-8');
        let content;
        try {
            content = await readPromise;
        } catch (err) {
            statusCallback(`❌ ${file.name} 读取失败`);
            return false;
        }

        // 上传附件
        statusCallback(`正在上传 ${file.name} ...`);
        const uploaded = setFileInput(file);
        if (!uploaded) {
            statusCallback(`❌ 未找到文件上传控件`);
            return false;
        }

        // 等待 2 秒让 DeepSeek 处理上传
        await delay(2000);

        // ---------- 获取输入框（用于发送） ----------
        statusCallback(`查找输入框...`);
        const textarea = await findElementAsync(SELECTORS.textarea);
        if (!textarea) {
            statusCallback(`❌ 未找到输入框`);
            return false;
        }

        // ---------- 使用回车键发送 ----------
        statusCallback(`发送 ${file.name} ...`);
        sendWithEnter(textarea);

        // 等待回复
        statusCallback(`等待25秒后开始检测回复...`);
        await waitForReplyComplete();

        if (cancelRequested) {
            statusCallback(`⏹ 已取消`);
            return false;
        }

        statusCallback(`正在检查回复内容...`);
        let reply = getLatestAssistantReply();
        const normalizedInput = content.trim();
        const normalizedReply = reply ? reply.trim() : '';

        if (reply && normalizedReply === normalizedInput) {
            statusCallback(`⚠️ 回复与输入相同，等待20秒后重试...`);
            await delay(20000);
            if (cancelRequested) {
                statusCallback(`⏹ 已取消`);
                return false;
            }
            reply = getLatestAssistantReply();
            const secondReply = reply ? reply.trim() : '';
            if (!reply || secondReply === normalizedInput) {
                statusCallback(`❌ 回复与输入完全相同（重试后仍一致）`);
                return 'input_duplicate';
            }
        }

        if (reply && lastDownloadedContent) {
            const cmpLength = 1000;
            const replyPrefix = normalizedReply.substring(0, cmpLength);
            const lastPrefix = lastDownloadedContent.substring(0, cmpLength);
            if (replyPrefix === lastPrefix) {
                statusCallback(`❌ 回复内容与上一次下载内容重复`);
                return 'prev_duplicate';
            }
        }

        if (reply) {
            statusCallback(`正在保存 ${file.name} ...`);
            const baseName = file.name.replace(/\.[^.]+$/, '');
            const outputName = baseName + '_polish.txt';
            downloadFile(outputName, reply, (msg) => statusCallback(msg));
            lastDownloadedContent = normalizedReply;
            return true;
        } else {
            statusCallback(`❌ ${file.name} 无有效回复`);
            return false;
        }
    }

    // ---------- 批量处理 ----------
    function naturalSort(files) {
        return files.sort((a, b) => {
            const aNum = a.name.match(/(\d+)/g)?.map(Number) || [0];
            const bNum = b.name.match(/(\d+)/g)?.map(Number) || [0];
            for (let i = 0; i < Math.max(aNum.length, bNum.length); i++) {
                const av = aNum[i] || 0;
                const bv = bNum[i] || 0;
                if (av !== bv) return av - bv;
            }
            return a.name.localeCompare(b.name);
        });
    }

    async function processFilesSequentially(files, statusCallback) {
        const sorted = naturalSort(Array.from(files));
        const total = sorted.length;
        let completed = 0;
        lastDownloadedContent = null;

        for (let i = 0; i < total; i++) {
            if (cancelRequested) {
                statusCallback(`⏹ 任务已取消 (已完成 ${completed}/${total})`);
                return;
            }

            const file = sorted[i];
            const progressCallback = (msg) => {
                statusCallback(`[${completed}/${total}] ${msg}`);
            };

            const result = await processOneFile(file, progressCallback);

            if (result === 'input_duplicate' || result === 'prev_duplicate') {
                statusCallback(`🛑 因重复内容终止任务 (已完成 ${completed}/${total})`);
                return;
            }

            if (result === true) {
                completed++;
            } else {
                completed++;
            }

            if (i < total - 1 && !cancelRequested) {
                const waitSeconds = Math.floor(Math.random() * 6) + 5;
                statusCallback(`[${completed}/${total}] ⏳ 等待 ${waitSeconds} 秒后继续...`);
                await delay(waitSeconds * 1000);
            }
        }

        if (!cancelRequested) {
            statusCallback(`✅ 全部完成 (${completed}/${total})`);
        }
    }

    // ---------- UI 创建 ----------
    function createUI() {
        const container = document.createElement('div');
        container.id = 'ds-auto-helper-v7';
        container.style.cssText = `
            position: fixed;
            bottom: 100px;
            right: 20px;
            z-index: 9999;
            display: flex;
            flex-direction: column;
            gap: 8px;
            background: rgba(30, 30, 40, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 12px;
            padding: 12px;
            box-shadow: 0 8px 20px rgba(0,0,0,0.3);
            border: 1px solid rgba(255,255,255,0.1);
            user-select: none;
            min-width: 240px;
        `;

        const dragHandle = document.createElement('div');
        dragHandle.textContent = '↕ 拖动移动';
        dragHandle.style.cssText = `
            cursor: move;
            color: #ccc;
            font-size: 12px;
            text-align: center;
            padding: 4px;
            border-radius: 6px;
            background: rgba(255,255,255,0.05);
            margin-bottom: 4px;
        `;
        container.appendChild(dragHandle);

        const mainBtn = document.createElement('button');
        mainBtn.textContent = '📂 批量上传并润色';
        mainBtn.style.cssText = `
            padding: 10px 16px;
            background: #4CAF50;
            color: white;
            border: none;
            border-radius: 6px;
            font-size: 14px;
            cursor: pointer;
            font-weight: bold;
            transition: opacity 0.2s;
        `;
        mainBtn.onmouseover = () => mainBtn.style.opacity = '0.8';
        mainBtn.onmouseout = () => mainBtn.style.opacity = '1';

        const exportBtn = document.createElement('button');
        exportBtn.textContent = '💾 手动导出回复 (增强)';
        exportBtn.style.cssText = `
            padding: 8px 14px;
            background: #2196F3;
            color: white;
            border: none;
            border-radius: 6px;
            font-size: 13px;
            cursor: pointer;
            transition: opacity 0.2s;
        `;
        exportBtn.onmouseover = () => exportBtn.style.opacity = '0.8';
        exportBtn.onmouseout = () => exportBtn.style.opacity = '1';

        const cancelBtn = document.createElement('button');
        cancelBtn.textContent = '⏹ 取消任务';
        cancelBtn.style.cssText = `
            padding: 8px 14px;
            background: #f44336;
            color: white;
            border: none;
            border-radius: 6px;
            font-size: 13px;
            cursor: pointer;
            transition: opacity 0.2s;
        `;
        cancelBtn.onmouseover = () => cancelBtn.style.opacity = '0.8';
        cancelBtn.onmouseout = () => cancelBtn.style.opacity = '1';

        const statusText = document.createElement('div');
        statusText.style.cssText = `
            color: #ccc;
            font-size: 12px;
            text-align: center;
            margin-top: 2px;
            min-height: 36px;
            word-break: break-word;
            white-space: pre-wrap;
        `;

        container.appendChild(mainBtn);
        container.appendChild(exportBtn);
        container.appendChild(cancelBtn);
        container.appendChild(statusText);
        document.body.appendChild(container);

        // 拖动功能
        let isDragging = false;
        let startX, startY, initialLeft, initialTop;
        function onMouseDown(e) {
            if (e.target !== dragHandle) return;
            e.preventDefault();
            isDragging = true;
            const rect = container.getBoundingClientRect();
            if (!container.style.left || !container.style.top) {
                container.style.left = rect.left + 'px';
                container.style.top = rect.top + 'px';
                container.style.right = 'auto';
                container.style.bottom = 'auto';
            }
            startX = e.clientX;
            startY = e.clientY;
            initialLeft = parseFloat(container.style.left) || rect.left;
            initialTop = parseFloat(container.style.top) || rect.top;
            document.addEventListener('mousemove', onMouseMove);
            document.addEventListener('mouseup', onMouseUp);
        }
        function onMouseMove(e) {
            if (!isDragging) return;
            const dx = e.clientX - startX;
            const dy = e.clientY - startY;
            container.style.left = (initialLeft + dx) + 'px';
            container.style.top = (initialTop + dy) + 'px';
        }
        function onMouseUp() {
            isDragging = false;
            document.removeEventListener('mousemove', onMouseMove);
            document.removeEventListener('mouseup', onMouseUp);
        }
        dragHandle.addEventListener('mousedown', onMouseDown);

        const setStatus = (msg) => {
            statusText.textContent = msg;
            if (msg.includes('❌') || msg.includes('✅ 全部完成') || msg.includes('⏹') || msg.includes('🛑')) {
                mainBtn.disabled = false;
                mainBtn.textContent = '📂 批量上传并润色';
                cancelBtn.disabled = true;
            } else {
                mainBtn.disabled = true;
                mainBtn.textContent = '⏳ 处理中...';
                cancelBtn.disabled = false;
            }
        };

        cancelBtn.addEventListener('click', () => {
            cancelRequested = true;
            statusText.textContent = '⏹ 正在取消...';
            cancelBtn.disabled = true;
        });

        mainBtn.addEventListener('click', function () {
            if (window._isProcessing) return;
            const input = document.createElement('input');
            input.type = 'file';
            input.accept = '.txt';
            input.multiple = true;
            input.onchange = function (e) {
                const files = e.target.files;
                if (!files || files.length === 0) return;
                window._isProcessing = true;
                cancelRequested = false;
                mainBtn.textContent = '⏳ 处理中...';
                mainBtn.disabled = true;
                cancelBtn.disabled = false;
                processFilesSequentially(files, setStatus).finally(() => {
                    window._isProcessing = false;
                });
            };
            input.click();
        });

        exportBtn.addEventListener('click', async function () {
            exportBtn.disabled = true;
            exportBtn.textContent = '⏳ 获取中...';
            statusText.textContent = '正在展开完整回复...';
            try {
                const reply = await getEnhancedAssistantReply();
                if (!reply) {
                    statusText.textContent = '❌ 没有找到正式回复内容';
                } else {
                    const defaultName = `reply_${new Date().toISOString().slice(0, 10)}.txt`;
                    const name = prompt('请输入导出文件名（不含路径）：', defaultName);
                    if (name) {
                        downloadFile(name, reply, (msg) => statusText.textContent = msg);
                    }
                }
            } catch (err) {
                statusText.textContent = '❌ 导出出错: ' + err.message;
            } finally {
                exportBtn.disabled = false;
                exportBtn.textContent = '💾 手动导出回复 (增强)';
                setTimeout(() => {
                    if (!window._isProcessing) statusText.textContent = '';
                }, 3000);
            }
        });
    }

    window.addEventListener('load', () => setTimeout(createUI, 1500));
})();