// 从 Content-Disposition 头解析文件名（纯函数，可单测）
// 优先 RFC 5987 filename*=UTF-8''（中文）；回退 filename="..."；都无 → 用 fallback。
export default function parseContentDispositionFilename(contentDisposition, fallback = 'report') {
  const cd = contentDisposition || '';
  const m = cd.match(/filename\*=UTF-8''([^;]+)/i) || cd.match(/filename="?([^";]+)"?/i);
  if (!m) return fallback;
  try {
    return decodeURIComponent(m[1]);
  } catch {
    return m[1];
  }
}