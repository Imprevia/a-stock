# 本机开发后端端口切换至 8001

## Stage

Implementation

## Status

completed

## Acceptance

- 本机后端可在 8001 启动，且不停止占用 8000 的打印服务。
- 5173 开发服务器的 `/api` 代理指向 8001。
- 启动和接口检查文档使用正确的本机端口。

## Completion Evidence

- `http://127.0.0.1:8001/api/health` returned `200` with `{"status":"ok"}`.
- `http://127.0.0.1:5173/api/health` returned `200` through the Vite proxy.
- `http://127.0.0.1:5173/` returned `200` and served the Vite application entry.
- Confirmed listeners: CLodop remains on 8000; API is on 8001; Vite is on 5173.

## Remaining Gaps

- None identified.

## Next Step

Use `http://127.0.0.1:5173/` for local dashboard development.
