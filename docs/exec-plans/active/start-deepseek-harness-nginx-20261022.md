# 启动 DeepSeek Harness 并配置 NGINX HTTPS 反向代理

## Stage

本机运行时启动与 HTTPS 入口恢复

## Status

completed-with-user-systemd-and-existing-nginx

## Acceptance

- DeepSeek Harness 使用官方 `dsh web` 入口监听 `127.0.0.1:3080`，上游使用 HTTP。
- NGINX 保持 TLS 终止并将 `gyt.tail0007b1.ts.net` HTTPS 请求转发到 3080。
- 本机上游、NGINX HTTPS 入口和 Tailscale HTTPS 入口均返回可用响应。
- 启动命令、进程状态和剩余风险有可审计记录。

## Completion Evidence

- 创建并启用 `/home/gyt/.config/systemd/user/deepseek-harness-web.service`，使用仓库支持的 `pnpm dsh web` 启动，绑定 `127.0.0.1:3080`，设置公开 URL 与受信任域名；服务状态为 `active` 且 `enabled`，开启失败自动重启和用户 linger 下的开机启动。
- `ss` 确认 Node 进程监听 `127.0.0.1:3080`；本机 HTTP 根路径在无凭据时返回预期的 `401`。
- 检查到现有 NGINX `multica.conf` 已监听域名 TLS/本机 HTTPS，并通过 HTTP 反代到 `127.0.0.1:3080`，包含 WebSocket Upgrade 转发；未修改或重载系统 NGINX 配置。
- 通过 NGINX 局域网 HTTPS 地址和 Tailscale HTTPS 域名完成 Harness token 引导；浏览器凭据建立后，两条 HTTPS 路径均返回 HTTP 200 Web UI（37,492 字节）。无 token 的请求返回 HTTP 401，符合应用认证要求。
- 本次无 NGINX 配置写入权限，因此未单独运行 `nginx -t`；活跃 NGINX 经实际 HTTPS 请求验证可用。

## Remaining Gaps

- 无运行阻断项。NGINX 系统配置由 root 管理，本次确认沿用现有配置；若后续修改配置，需由具备权限的管理员执行 `nginx -t` 和 reload。

## Next Step

- 继续使用 `systemctl --user status deepseek-harness-web.service` 检查服务；如需停止或重启，使用对应 `systemctl --user` 命令。
