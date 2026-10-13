// electron/preload.js
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('desktopAPI', {
  // 渲染进程拖拽拿到 File 后取真实磁盘路径（主进程 webUtils.getPathForFile）
  取文件真实路径: (file) => ipcRenderer.invoke('desktop:get-file-path', file),
  // 检查更新（一期：拉取 GitHub Releases 最新版本号）
  检查更新: () => ipcRenderer.invoke('desktop:check-update'),
  // 版本信息（供前端展示）
  获取版本: () => ipcRenderer.invoke('desktop:get-version'),
});