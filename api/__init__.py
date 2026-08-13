"""api 包：FastAPI 接口层。

对外暴露 HTTP API（认证、数据集、报表、分享、管理、健康检查等），
由 main.py 组装路由，dependencies.py 提供鉴权依赖，middleware.py
提供横切拦截，error_handlers.py 统一异常转 JSON 响应。
"""