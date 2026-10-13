// 主窗口渲染进程与主进程之间唯一的桥：把 desktop:* IPC 包成 window.desktopAPI 暴露给网页。
// 做了什么：contextBridge 暴露 3 个方法——取文件真实路径(File→磁盘路径)、检查更新、取应用版本；
//   每个方法都是一次 ipcRenderer.invoke，参数与返回值原样透传，不做校验也不缓存。
// 为什么只放这 3 个：配置类 IPC 在 配置页/preload.js，渲染页拿不到「改后端配置」的入口，
//   否则桌面专属能力会混进网页版共用的 frontend/dist；也不用白名单 API 一次性放权，那等于绕过 contextIsolation 自己造后门。
// 约定：暴露的方法名一律中文（与前端 utils 风格一致）；新增能力要先在 main.js 注册一个 handle 通道，再在这里透出，两边必须同步。
// 坑：File 对象过不了 IPC，真实磁盘路径只能靠主进程 webUtils.getPathForFile 取（对应 main.js 的 desktop:get-file-path）。
// 坑：前端一律 window.desktopAPI?.取文件真实路径?.(...) 可选链调用——网页版没有这个 preload，直接访问会 ReferenceError。
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('desktopAPI', {
  // 渲染进程拖拽拿到 File 后取真实磁盘路径（主进程 webUtils.getPathForFile）
  取文件真实路径: (file) => ipcRenderer.invoke('desktop:get-file-path', file),
  // 检查更新（一期：拉取 GitHub Releases 最新版本号）
  检查更新: () => ipcRenderer.invoke('desktop:check-update'),
  // 版本信息（供前端展示）
  获取版本: () => ipcRenderer.invoke('desktop:get-version'),
});