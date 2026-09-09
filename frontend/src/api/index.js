/**
 * api/index.js - re-export entry
 */
export { uploadFile, uploadFileWithProgress, generateReportStream } from './upload';
export {
  login, changePassword, changeUsername, sendCode, sendResetCode, resetPassword, register, fetchMe,
  getAccountLLMKey, fetchLLMProviders, saveCustomProvider, deleteCustomProvider, testCustomProvider,
  saveAccountLLMKey, clearAccountLLMKey,
  loadExample, getDataset, getDatasetRows, listDatasets, deleteDataset, renameDataset, mergeDatasets, cleanDataset,
  generateReport,
  listTemplates, saveTemplate, deleteTemplate, runTemplate,
  listSchedules, createSchedule, deleteSchedule, globalSearch, fetchFailedSchedules,
  listReports, getReport, exportReport, exportFullReport, deleteReport,
  createShare, toggleFavorite, listShares, revokeShare, getSharedReport, replayReport,
  listDashboards, getDashboard, createDashboard, updateDashboard, deleteDashboard, shareDashboard,
  fetchStatistics, fetchAdminUsers, fetchAuditLog, fetchUsage, fetchMetrics, exportEvents,
  banUser, unbanUser, healthCheck, submitFeedback, exportUserData, deleteAccount,
} from './endpoints';
