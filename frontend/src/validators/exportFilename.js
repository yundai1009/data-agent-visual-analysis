// 从导出响应头里取回后端给定的文件名：浏览器只知道「下载了一个 blob」，名字得自己从响应头捞。
// 做了什么：export default parseContentDispositionFilename(contentDisposition, fallback = 'report')，
//   先匹配 RFC 5987 的 filename*=UTF-8''xxx（后端给中文名走这条），再回退 filename="..."，都匹配不到就用 fallback；
//   命中后 decodeURIComponent，遇到非法百分号编码（URIError）时原样返回未解码串而不是抛。
// 为什么必须解析 Content-Disposition：不读这个头就只能给 a.download 一个兜底名，报表名、数据集名这类中文信息会全丢。
// 为什么不干脆由前端自己拼名字（报表名 + 后缀）：命名规则在后端，报表导出、全量导出、看板导出的规则各不相同，
//   前端另起一套必然与后端实际产出的文件对不上，也会漏掉后端为防重名加的后缀。
// 约定：filename* 的正则必须排在 filename= 前面——两者可能同时出现在同一个头里，RFC 5987 的优先。
// 坑：只做字符串解析、不校验来源，安全性靠调用方只把同源后端响应的头传进来（现有调用点都在 api/endpoints.js）。
// 坑：正则不处理引号内的转义与多值 Content-Disposition，遇到非常规头会退化成「整段未解码串」或直接落到 fallback，不报错。
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