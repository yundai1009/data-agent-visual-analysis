/**
 * api/upload.js — 传输层：文件上传 + SSE 流式分析
 *
 * 从 api.js 拆分，职责：两类不走 request() 封装的特殊请求——
 * 1. 文件上传（fetch AbortController 变体 + XMLHttpRequest 进度变体）
 * 2. generateReportStream（SSE 长连接，fetch + ReadableStream 解析）
 * 依赖 api/request.js 的头构建/401 处理/错误解析。
 */

import { BASE, getLLMHeaders, getAuthHeaders, UPLOAD_TIMEOUT_MS, handleAuthExpired, parseError } from './request';

/**
 * 多文件上传（fetch 版，无进度事件）。
 * 传 File 或 File[]，POST /datasets/upload；返回后端解析后的 JSON。
 */
export async function uploadFile(files) {
  const form = new FormData();
  const fileArr = files instanceof File ? [files] : Array.from(files);
  for (const f of fileArr) {
    form.append('file', f);
  }
  const llmHeaders = getLLMHeaders();
  const authHeaders = getAuthHeaders();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), UPLOAD_TIMEOUT_MS);
  try {
    const res = await fetch(`${BASE}/datasets/upload`, {
      method: 'POST', body: form, headers: { ...authHeaders, ...llmHeaders }, signal: controller.signal,
    });
    if (!res.ok) {
      if (res.status === 401) handleAuthExpired('/datasets/upload');
      throw await parseError(res);
    }
    return res.json();
  } finally {
    clearTimeout(timer);
  }
}

/**
 * 带上传进度的多文件上传（XMLHttpRequest 支持 upload.onprogress；fetch 无进度事件）。
 * onProgress(percent 0-100) 回调；返回 { promise, abort }——
 * abort 供组件卸载/切页时取消上传（Bug18 修复）。
 */
export function uploadFileWithProgress(files, onProgress) {
  const form = new FormData();
  const fileArr = files instanceof File ? [files] : Array.from(files);
  for (const f of fileArr) {
    form.append('file', f);
  }
  const llmHeaders = getLLMHeaders();
  const authHeaders = getAuthHeaders();
  const controller = { aborted: false, xhr: null };
  const abort = () => {
    controller.aborted = true;
    if (controller.xhr) controller.xhr.abort();
  };
  const promise = new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    controller.xhr = xhr;
    xhr.open('POST', `${BASE}/datasets/upload`);
    Object.entries({ ...authHeaders, ...llmHeaders }).forEach(([k, v]) => xhr.setRequestHeader(k, v));
    if (onProgress) {
      xhr.upload.onprogress = (e) => {
        if (controller.aborted) return;
        if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
      };
    }
    xhr.onload = () => {
      if (controller.aborted) return;
      if (xhr.status >= 200 && xhr.status < 300) {
        try { resolve(JSON.parse(xhr.responseText)); } catch { reject(new Error('响应解析失败')); }
      } else {
        if (xhr.status === 401) handleAuthExpired('/datasets/upload');
        let message = `上传失败（HTTP ${xhr.status}）`;
        try {
          const body = JSON.parse(xhr.responseText);
          if (body && body.message) message = body.message;
        } catch { /* 非 JSON */ }
        const err = new Error(message);
        err.status = xhr.status;
        reject(err);
      }
    };
    xhr.onerror = () => { if (!controller.aborted) reject(new Error('上传中断，请检查网络后重试')); };
    xhr.ontimeout = () => { if (!controller.aborted) reject(new Error('上传超时，请重试')); };
    xhr.onabort = () => reject(new Error('上传已取消'));
    xhr.timeout = UPLOAD_TIMEOUT_MS;
    xhr.send(form);
  });
  return { promise, abort };
}

/**
 * SSE 流式分析：fetch + ReadableStream 解析 Agent 决策事件。
 * options.onEvent(ev)：每个 "data: {json}" 事件回调；返回 'stop' 可中断消费。
 * options.signal：AbortController（用户取消）。
 */
export async function generateReportStream(payload, { onEvent, signal } = {}) {
  const llmHeaders = getLLMHeaders();
  const authHeaders = getAuthHeaders();
  const res = await fetch(`${BASE}/reports/generate-stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', ...authHeaders, ...llmHeaders },
    body: JSON.stringify(payload),
    signal,
  });
  if (!res.ok) {
    if (res.status === 401) handleAuthExpired('/reports/generate-stream');
    throw await parseError(res);
  }
  if (!res.body) throw new Error('SSE 响应体为空，无法读取分析流');
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  const SSE_TIMEOUT_MS = 180000;
  const sseTimer = setTimeout(async () => {
    try { await reader.cancel(); } catch { /* ignore */ }
    if (onEvent) onEvent({ type: 'error', message: '分析超时，请稍后重试' });
  }, SSE_TIMEOUT_MS);
  try {
  for (;;) {
    const { done, value } = await reader.read();
    if (done) {
      // P0 修复（Bug32）：流结束时处理 buf 中残留的最后一段未以 \n\n 结尾的帧。
      if (buf.trim()) {
        for (const raw of buf.split('\n')) {
          if (raw.startsWith('data: ')) {
            try {
              const ev = JSON.parse(raw.slice(6));
              if (onEvent && onEvent(ev) === 'stop') {
                try { await reader.cancel(); } catch { /* ignore */ }
                return;
              }
            } catch { /* 畸形尾帧：忽略 */ }
          }
        }
      }
      break;
    }
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      for (const raw of chunk.split('\n')) {
        if (raw.startsWith('data: ')) {
          let ev;
          try {
            ev = JSON.parse(raw.slice(6));
          } catch { continue; }
          try {
            if (onEvent && onEvent(ev) === 'stop') {
              await reader.cancel();
              return;
            }
          } catch (e) {
            console.error('SSE onEvent 处理异常:', e);
          }
        }
      }
    }
  }
  } finally {
    clearTimeout(sseTimer);
  }
}