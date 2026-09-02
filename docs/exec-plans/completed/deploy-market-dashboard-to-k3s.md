# 在 k3s 部署市场环境看板

## Stage（阶段）

容器化与 k3s 部署配置实现、验证。

## Status（状态）

`completed`

## Scope（范围）

- 将 Vue 生产构建产物与 FastAPI API 打包为同一个非 root 容器镜像。
- 新增可由 k3s 内置 Kustomize 和 Traefik 直接部署的 Namespace、Deployment、Service、Ingress 与持久卷声明。
- 记录本地镜像导入、私有仓库镜像覆盖、发布检查、日志查看与回滚路径。

## Acceptance（验收）

- `Dockerfile` 同时包含前端生产构建和 FastAPI 运行阶段，运行镜像只启动一个 Uvicorn 进程。
- `kubectl apply -k deploy/k3s` 的资源闭合为 `a-stock` namespace 下的单副本工作负载、持久卷、ClusterIP Service 和 Traefik Ingress。
- 容器使用非 root 用户，并配置资源限制、启动/就绪/存活探针和优雅终止时间。
- 默认镜像名可通过 `deploy/k3s/kustomization.yaml` 的 `images` 字段切换为集群可访问的仓库地址与固定版本。
- 前端生产构建、部署相关 API 测试、静态路由烟测、Kubernetes YAML 解析和本地文档门禁通过；无法在本机执行的 Docker/k3s 验证显式记录。

## Completion Evidence（完成证据）

- 容器：新增根目录 `Dockerfile` 与 `.dockerignore`；mootdx 的用户目录写入落到可写 `/tmp`。
- k3s：`deploy/k3s/` 包含 Kustomization、Namespace、2Gi `local-path` PVC、Deployment、Service 和 Traefik Ingress。
- 前端：`npm run build --prefix apps/market-environment-dashboard` 通过，生成非空 CSS/JS 生产资源。
- API：`tests/test_market_environment_api.py` 为 `5 passed`；TestClient 验证 `/api/health` 与生产 `index.html` 路由通过。
- 清单：PyYAML 成功解析 6 个 YAML 文件，并验证 Deployment selector、Service selector、Ingress backend、镜像和探针连线。
- 文档门禁：隔离临时索引下 `--mode=fast` 通过；`SKIP_PLAN_GATE=1` 后 `--mode=full` 其余规则通过。未带逃生开关的 full 被当前分支既有提交范围的 Gate 3 阻塞。
- 全量测试观察：并行进行的 snapshot provider 改动当前为 `65 passed, 2 failed`，失败位于 `tests/test_market_environment_providers.py`，不涉及本次部署文件。

## Remaining Gaps（剩余缺口）

- 当前工作机未安装 Docker、kubectl 或 k3s，不能在本机完成真实镜像构建、server-side dry-run 和集群 rollout 验证。
- TLS、正式域名、私有仓库凭据和多节点镜像分发依赖目标集群环境，本次仅提供可覆盖入口。
- 当前分支已有其他跨区代码提交但其 active plan 尚未进入该提交范围，导致标准 docs-contract full 的 Gate 3 失败；本任务未修改或重写该历史。

## Next Step（下一步）

在目标环境设置固定镜像仓库与 tag，执行 `kubectl apply -k deploy/k3s`，完成 rollout、`/api/health`、页面加载、PVC 重启保持和行情出口验证。
