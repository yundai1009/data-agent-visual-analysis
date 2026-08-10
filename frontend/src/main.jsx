import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

// 启动 splash 淡出移除：React 首帧挂载完成后，让 index.html 的加载动画平滑退场
const splash = document.getElementById('app-splash')
if (splash) {
  // 首帧后加 fade-out（transition 0.4s），动画结束再真正移除节点
  requestAnimationFrame(() => {
    splash.classList.add('splash-fade-out')
  })
  window.setTimeout(() => splash.remove(), 600)
}
