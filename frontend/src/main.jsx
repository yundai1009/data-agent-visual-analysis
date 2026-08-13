// 前端入口文件：把 React 应用挂载到 index.html 的 #root 节点。
//
// 做了什么：创建 React 根实例，用 StrictMode 包裹 <App/> 渲染整棵组件树。
// 为什么放在这里：main.jsx 是 Vite 约定的打包入口，浏览器最先执行它；
//   先 import 样式与根组件，再渲染，保证首屏样式与路由都就绪。
// 删除它会怎样：页面空白，没有任何组件被渲染。
// 替代方案：也可从 index.html 直接引打包产物，但会失去 HMR 与模块化开发。
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
