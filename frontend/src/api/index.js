// 前端 API 的唯一入口（barrel / re-export 汇总口）：组件一律从 '@/api' 取函数，不去记具体端点文件。
// 做了什么：从 ./upload 再导出 3 个传输层接口（上传、带进度上传、SSE 流式报告），
//   从 ./endpoints 一次性再导出全部 REST 业务函数（认证 / 数据集 / 模板 / 计划任务 / 报表 / 分享 / 看板 / 统计 / 管理员 / 反馈 / 合规）。
// 为什么要有这一层：端点已经按职责拆成 upload 与 endpoints 两个文件，再让几十个组件各自记住该去哪个文件 import，
//   等于把目录结构当成 API 契约；一个 barrel 把「平台有哪些能力」收成一份可搜索、可一次看完的清单。
// 为什么这里只做 re-export、不做统一 baseURL / 拦截器封装：令牌注入、超时、401 与错误解析已经在 api/request.js 里，
//   再套一层只会多一层转手；而且 request.js 的 BASE 是空串（走相对路径），请求基址由运行时 origin 决定——
//   桌面版是 http://127.0.0.1:<随机端口>、网页版是部署域名，写死基址会让两端失配。
// 坑：删除或重命名任何端点函数都会让这个文件编译期报错——它同时充当「接口清单」，用 import 报错替代了运行期的 undefined 检查。
// 坑：barrel 会让引用它的 chunk 带上整个 ./endpoints；当前端点模块只是 fetch 封装、体积很小，不值得做按需加载，等真膨胀再拆。
export { uploadFile, uploadFileWithProgress, generateReportStream } from './upload';
export {
  login, changePassword, changeUsername, sendCode, sendResetCode, resetPassword, register, fetchMe, getMyUsage,
  getAccountLLMKey, fetchLLMProviders, saveCustomProvider, deleteCustomProvider, testCustomProvider,
  saveAccountLLMKey, clearAccountLLMKey,
  loadExample, getDataset, getDatasetRows, listDatasets, deleteDataset, renameDataset, mergeDatasets, cleanDataset,
  generateReport, previewCompare, compareReport,
  listTemplates, saveTemplate, deleteTemplate, runTemplate,
  listSchedules, createSchedule, deleteSchedule, globalSearch, fetchFailedSchedules,
  listReports, getReport, exportReport, exportFullReport, exportAllReports, deleteReport,
  createShare, toggleFavorite, listShares, revokeShare, getSharedReport, replayReport, refineReport,
  listDashboards, getDashboard, createDashboard, updateDashboard, deleteDashboard, shareDashboard,
  fetchStatistics, fetchAdminUsers, fetchAuditLog, fetchUsage, fetchMetrics, exportEvents,
  banUser, unbanUser, healthCheck, submitFeedback, exportUserData, deleteAccount,
} from './endpoints';
