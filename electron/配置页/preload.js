// electron/配置页/preload.js
// 配置窗口专用 preload：只暴露这 7 个能力，不开 nodeIntegration。
// 与主窗口 preload（electron/preload.js）分开，避免把「改配置/重启后端」这种
// 高权限动作暴露给渲染网页版页面的主窗口。
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('配置API', {
  /** @returns {Promise<{表单: object, 文件路径: string}>} */
  读取配置: () => ipcRenderer.invoke('desktop:config-load'),
  /** @returns {Promise<{ok: boolean, 错误: string[]}>} 不落盘，仅做校验（输入即时提示用） */
  校验表单: (表单) => ipcRenderer.invoke('desktop:config-validate', 表单),
  /** @returns {Promise<{ok: boolean, 错误: string[], 需重启: boolean}>} 校验通过才落盘 */
  保存配置: (表单) => ipcRenderer.invoke('desktop:config-save', 表单),
  /** @returns {Promise<string>} 64 字符 hex 强随机密钥 */
  生成强密钥: () => ipcRenderer.invoke('desktop:config-gen-secret'),
  /** @param {'配置'|'日志'} 目标 @returns {Promise<{ok: boolean, 说明: string}>} */
  打开目录: (目标) => ipcRenderer.invoke('desktop:config-open-dir', 目标),
  /** @returns {Promise<{ok: boolean, 错误: string}>} 按磁盘上的最新配置重启后端 */
  重启后端: () => ipcRenderer.invoke('desktop:restart-backend'),
  关闭配置窗口: () => ipcRenderer.send('desktop:config-close'),
});
