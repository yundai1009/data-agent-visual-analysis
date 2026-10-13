// electron/核心/托盘逻辑.js
/**
 * 计算托盘菜单结构与退出行为（纯逻辑，便于单测；不直接依赖 electron API）。
 * @param {{是否主窗口可见: boolean}} state
 * @returns {Array<{id: string, label: string, type: 'normal'|'separator'}>}
 */
function 托盘菜单(state) {
  // 菜单 label 当前固定为「显示主窗口」（点击时总是 show+focus，见 main.js 映射）；
  // state 保留入参以描述菜单结构可随窗口可见性演化的契约
  return [
    { id: 'show', label: '显示主窗口', type: 'normal' },
    { id: 'separator', type: 'separator' },
    { id: 'quit', label: '退出', type: 'normal' },
  ];
}

module.exports = { 托盘菜单 };
