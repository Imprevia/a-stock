# TrueNAS SCALE 24.04：在 VM 中用 Podman 构建并部署到 k3s

本文档适用于以下部署边界：

```text
Ubuntu VM
  ├─ git clone a-stock
  ├─ Podman 读取仓库 Dockerfile 构建 OCI 镜像
  ├─ Helm / kubectl 作为发布客户端
  └─ scp 镜像归档到 TrueNAS

TrueNAS SCALE 24.04 宿主机
  ├─ 不安装 Docker、Podman 或 BuildKit
  ├─ k3s ctr 将镜像导入 containerd 的 k8s.io namespace
  └─ k3s 运行 Helm release 创建的 Pod、Service、Ingress 和 PVC
```

`Dockerfile` 只是镜像构建说明，不要求安装 Docker。Podman/Buildah 可以直接使用仓库根目录的同一份 `Dockerfile`。

## 1. 前提和约束

- TrueNAS SCALE 版本为 24.04，k3s、containerd 和 Apps 服务已经正常运行。
- TrueNAS 至少预留 2 核 CPU、4 GiB 内存和 32 GiB VM 磁盘空间；首次 Python/Node 构建建议 VM 使用 4 核、8 GiB 内存。
- VM 能访问互联网、Git 仓库和 TrueNAS 管理 IP。
- TrueNAS 与 VM 的系统架构通常都是 `amd64`；如果不是，构建时必须改为目标节点架构。
- 本教程按单节点 k3s 编写。本地导入的镜像只存在于导入它的节点；多节点环境必须向每个可能调度 Pod 的节点导入相同镜像，或使用镜像仓库。
- 使用不可变镜像 tag，例如 `2026.09.02-1`。不要重复覆盖 `latest` 或已经发布过的 tag，否则 containerd 可能继续运行旧镜像。
- TrueNAS 的内部 k3s 和 Apps 状态属于平台管理边界。升级 TrueNAS 前应备份 Helm values、SQLite 和必要的镜像归档。

文档中的占位符需要替换：

| 占位符 | 示例 | 说明 |
|---|---|---|
| `<TRUENAS_IP>` | `192.168.1.20` | TrueNAS 管理/节点 IP |
| `<TRUENAS_USER>` | `admin` | 可 SSH 且能执行受控 sudo 的管理用户 |
| `<POOL>` | `tank` | TrueNAS 存储池名称 |
| `<REPOSITORY_URL>` | `https://example.com/a-stock.git` | 项目 Git 地址 |
| `<APP_HOST>` | `stock.example.lan` | 指向 TrueNAS IP 的内部 DNS 名称 |

## 2. 在 TrueNAS 准备数据集和 SSH

在 TrueNAS Web UI 创建专用数据集，例如：

```text
<POOL>/app-builds/a-stock
```

对应路径为：

```text
/mnt/<POOL>/app-builds/a-stock
```

该目录只保存待导入的镜像 tar、SHA-256 和临时 kubeconfig，不要把它放在 TrueNAS 系统盘或 `/tmp`。授予 `<TRUENAS_USER>` 对该数据集的读写权限。

在 **System Settings → Services → SSH** 中配置并启动 SSH。建议只允许 SSH key，不启用 root 密码登录。确认 VM 可以连接：

```bash
ssh <TRUENAS_USER>@<TRUENAS_IP> 'hostname'
```

## 3. 创建 Ubuntu 构建 VM

在 TrueNAS Web UI 的 **Virtualization** 中创建 VM：

- 系统：Ubuntu Server 24.04 LTS 或 22.04 LTS。
- CPU：至少 2 vCPU，建议 4 vCPU。
- 内存：至少 4 GiB，建议 8 GiB。
- 磁盘：至少 32 GiB。
- 网络：使用能同时访问互联网和 TrueNAS 管理 IP 的 NIC/bridge。
- 启动顺序：安装完成后移除 ISO 或把系统磁盘放在首位。

在 Ubuntu 安装时创建普通管理用户，并安装 OpenSSH Server。进入 VM 后更新系统：

```bash
sudo apt-get update
sudo apt-get upgrade -y
```

## 4. 在 VM 安装 Podman、Git、Helm 和 kubectl

Podman 负责构建；Helm 和 kubectl 只作为 k3s 的远程客户端：

```bash
sudo apt-get install -y podman git curl ca-certificates snapd
sudo snap install helm --classic
sudo snap install kubectl --classic
```

验证：

```bash
podman --version
helm version --short
kubectl version --client
podman info
```

执行一次最小容器测试：

```bash
podman run --rm docker.io/library/alpine:3.20 uname -m
```

预期为 `x86_64`。若 TrueNAS k3s 节点是其他架构，后续 `--platform` 必须与节点一致。

## 5. 获取项目并检查 Chart

在 VM 中执行：

```bash
mkdir -p "$HOME/src"
cd "$HOME/src"
git clone <REPOSITORY_URL> a-stock
cd a-stock
git status
helm lint --strict deploy/helm/a-stock
helm template a-stock deploy/helm/a-stock --namespace a-stock >/dev/null
```

生产发布应 checkout 明确的 commit 或 tag，不要从来源不明的工作区构建：

```bash
git fetch --all --tags
git checkout <COMMIT_OR_TAG>
git rev-parse HEAD
```

## 6. 使用 Podman 构建镜像

在 VM 的仓库根目录设置本次不可变版本：

```bash
export IMAGE_TAG=2026.09.02-1
export IMAGE_REPOSITORY=localhost/a-stock-market-environment
export IMAGE="${IMAGE_REPOSITORY}:${IMAGE_TAG}"
```

`localhost/` 前缀是有意保留的。Podman 会规范化未限定的镜像名；显式使用该前缀可以确保导入 containerd 后，Helm 引用与实际镜像名一致。

构建：

```bash
podman build \
  --platform linux/amd64 \
  --format docker \
  --tag "$IMAGE" \
  .
```

检查镜像：

```bash
podman images "$IMAGE"
podman image inspect "$IMAGE" --format '{{.Id}} {{.Architecture}} {{.Os}}'
```

如果构建机或 TrueNAS 节点不是 `amd64`，将 `linux/amd64` 改为 `linux/arm64` 等实际目标平台。不要在没有检查节点架构时盲目交叉构建。

## 7. 在 VM 进行镜像烟测

启动临时容器：

```bash
podman run --rm --detach \
  --name a-stock-smoke \
  --publish 18000:8000 \
  "$IMAGE"
```

检查健康接口和首页：

```bash
curl --fail --show-error http://127.0.0.1:18000/api/health
curl --fail --show-error --output /dev/null http://127.0.0.1:18000/
podman logs a-stock-smoke
```

停止容器：

```bash
podman stop a-stock-smoke
```

健康接口应返回：

```json
{"status":"ok"}
```

## 8. 导出并传输镜像

在 VM 中：

```bash
export ARCHIVE="a-stock-market-environment-${IMAGE_TAG}.tar"
podman save --format docker-archive --output "$ARCHIVE" "$IMAGE"
sha256sum "$ARCHIVE" >"${ARCHIVE}.sha256"
ls -lh "$ARCHIVE" "${ARCHIVE}.sha256"
```

传到 TrueNAS 专用数据集：

```bash
scp "$ARCHIVE" "${ARCHIVE}.sha256" \
  <TRUENAS_USER>@<TRUENAS_IP>:/mnt/<POOL>/app-builds/a-stock/
```

## 9. 导入 TrueNAS k3s 的 containerd

通过 TrueNAS Web Shell 或 SSH 登录宿主机：

```bash
cd /mnt/<POOL>/app-builds/a-stock
sha256sum --check "a-stock-market-environment-${IMAGE_TAG}.tar.sha256"
```

导入 `k8s.io` namespace：

```bash
sudo k3s ctr --namespace k8s.io images import \
  "a-stock-market-environment-${IMAGE_TAG}.tar"
```

确认 containerd 中的完整镜像名：

```bash
sudo k3s ctr --namespace k8s.io images list | \
  grep "localhost/a-stock-market-environment:${IMAGE_TAG}"
```

必须看到与 Helm 将使用的名称完全一致的：

```text
localhost/a-stock-market-environment:<IMAGE_TAG>
```

如果实际名称不同，以 `images list` 输出为准，并同步修改 Helm 的 `image.repository` 和 `image.tag`。不要通过把 `imagePullPolicy` 改成 `Always` 解决名称不一致；本地镜像没有远程仓库可供拉取。

## 10. 检查 k3s 集群能力

在 TrueNAS 宿主机执行：

```bash
sudo k3s kubectl get nodes -o wide
sudo k3s kubectl get storageclass
sudo k3s kubectl get ingressclass
sudo k3s kubectl get pods --all-namespaces
```

记录：

- Ready 节点名称和架构。
- 实际默认 StorageClass。TrueNAS 环境可能是 `ix-storage-class`，通用 k3s 常见为 `local-path`；必须使用命令输出，不能猜测。
- IngressClass 是否为 `traefik`。
- Traefik 和存储 provisioner 是否健康。

后续示例假设：

```bash
export STORAGE_CLASS=ix-storage-class
export INGRESS_CLASS=traefik
```

如果命令显示的是其他名称，替换以上变量。

## 11. 安全地取得 k3s kubeconfig

Helm 和 kubectl 在 VM 中运行，需要访问 TrueNAS k3s API。`/etc/rancher/k3s/k3s.yaml` 通常具有集群管理员权限，必须按密钥保护。

先在 TrueNAS 宿主机创建临时副本：

```bash
sudo cp /etc/rancher/k3s/k3s.yaml \
  /mnt/<POOL>/app-builds/a-stock/truenas-k3s.yaml
sudo chown <TRUENAS_USER> \
  /mnt/<POOL>/app-builds/a-stock/truenas-k3s.yaml
sudo chmod 600 \
  /mnt/<POOL>/app-builds/a-stock/truenas-k3s.yaml
```

在 VM 中复制并限制权限：

```bash
mkdir -p "$HOME/.kube"
scp <TRUENAS_USER>@<TRUENAS_IP>:/mnt/<POOL>/app-builds/a-stock/truenas-k3s.yaml \
  "$HOME/.kube/truenas-k3s.yaml"
chmod 600 "$HOME/.kube/truenas-k3s.yaml"
```

kubeconfig 中的 API 地址通常是 `127.0.0.1:6443`，在 VM 中改为 TrueNAS 可达地址：

```bash
sed -i 's#https://127.0.0.1:6443#https://<TRUENAS_IP>:6443#' \
  "$HOME/.kube/truenas-k3s.yaml"
export KUBECONFIG="$HOME/.kube/truenas-k3s.yaml"
kubectl get nodes
helm list --all-namespaces
```

验证成功后，立即在 TrueNAS 宿主机删除临时导出副本：

```bash
sudo rm -- "/mnt/<POOL>/app-builds/a-stock/truenas-k3s.yaml"
```

不要删除 VM 中正在使用的 kubeconfig。长期使用时应创建最小权限的独立凭据，而不是持续分发集群管理员 kubeconfig。

如果出现证书错误，不要使用 `--insecure-skip-tls-verify`。应使用证书包含的节点地址，或通过 TrueNAS/k3s 支持的配置为 API 证书加入正确 SAN。如果 6443 无法访问，检查 VM 到 TrueNAS 的路由、防火墙和 k3s API 监听地址。

## 12. 准备 TrueNAS 环境 values

在 VM 仓库根目录创建不含密码的环境 values，例如 `values-truenas.yaml`：

```yaml
replicaCount: 1

image:
  repository: localhost/a-stock-market-environment
  tag: "2026.09.02-1"
  pullPolicy: IfNotPresent

ingress:
  enabled: true
  className: traefik
  host: stock.example.lan

persistence:
  enabled: true
  storageClass: ix-storage-class
  size: 2Gi
  keep: true

marketEnvironment:
  timezone: Asia/Shanghai
  snapshotPath: /data/snapshots.sqlite3
  persistentCache: true
  scheduledCollection:
    enabled: false
    suspend: true
```

按第 10 节的实际输出替换 `storageClass` 和 `className`，按本次构建替换 tag。为 `<APP_HOST>` 创建指向 `<TRUENAS_IP>` 的 DNS A/AAAA 记录；没有内部 DNS 时，可先在访问电脑的 hosts 文件中添加映射。

检查最终渲染：

```bash
helm lint --strict deploy/helm/a-stock
helm template a-stock deploy/helm/a-stock \
  --namespace a-stock \
  --values values-truenas.yaml \
  > /tmp/a-stock-rendered.yaml
```

确认渲染文件中没有密码、token 或错误镜像名后再发布。

## 13. 首次部署到 k3s

在 VM 仓库根目录创建私有部署环境文件，将 `HELM_VALUES_FILE` 指向上一节已审阅的完整 `values-truenas.yaml`，并保持 `SCHEDULED_COLLECTION_ENABLED=false`、`SCHEDULED_COLLECTION_SUSPEND=true`。生产写操作只使用仓库的 fail-closed 入口，不直接执行 Helm write：

```bash
cp deploy/truenas/deploy.env.example deploy/truenas/deploy.env
editor deploy/truenas/deploy.env
bash scripts/deploy-truenas-k3s.sh --env-file deploy/truenas/deploy.env
```

入口必须在 build/import/release write 前证明 Helm stored manifest 与 live state 均无 application CronJob，并在成功写入后再次验证 live CronJob 仍不存在。若这是对既有 release 的幂等部署，先执行只读 discovery；stored 或 live 状态发现 active/suspended CronJob 时不得继续普通发布，必须先按第 15 节完成受审 `--disable-schedule`。

检查 release 和 Kubernetes 资源：

```bash
helm status a-stock --namespace a-stock
kubectl --namespace a-stock get deployment,pods,service,ingress,pvc
kubectl --namespace a-stock rollout status deployment/a-stock --timeout=180s
kubectl --namespace a-stock describe pod -l app.kubernetes.io/instance=a-stock
```

检查日志：

```bash
kubectl --namespace a-stock logs deployment/a-stock --tail=200
```

通过 DNS 验证：

```bash
curl --fail --show-error "http://<APP_HOST>/api/health"
curl --fail --show-error --output /dev/null "http://<APP_HOST>/"
```

DNS 尚未配置时，可以显式发送 Host header：

```bash
curl --fail --show-error \
  --header 'Host: <APP_HOST>' \
  "http://<TRUENAS_IP>/api/health"
```

## 14. 后续发布新版本

每次更新都在 VM 仓库根目录检出已审阅的 clean commit，并在 `deploy/truenas/deploy.env` 中设置新的不可变 tag。普通入口负责构建、烟测、SHA-256、SCP、containerd 导入和 release write：

```bash
git fetch --all --tags
git checkout <NEW_COMMIT_OR_TAG>
editor deploy/truenas/deploy.env
bash scripts/deploy-truenas-k3s.sh --env-file deploy/truenas/deploy.env
```

即使只更新镜像，也必须重新提交完整 baseline values；不得设置 scheduling overlay、继承 release 中无法审阅的历史值或直接执行 Helm write。任何 precondition、write、rollout 或写后调度查询失败都不能报告成功；失败恢复必须把意外 active CronJob 精确暂停并证明状态至少为 absent/suspended，无法证明时保持 uncertain/NO-GO。失败后转入受审 `--disable-schedule`，不得直接重试普通入口。

## 15. 回滚

先用只读 discovery 捕获实际 release/version/stored values/live resources。历史 revision 只用于审计，不能直接恢复：

```bash
bash scripts/deploy-truenas-k3s.sh --env-file deploy/truenas/deploy.env --read-only-discovery \
  --release-name a-stock --namespace a-stock
```

若发现 active 或 suspended application CronJob，应用回退必须先停止。冻结并审阅 baseline + off overlay、实际 Kubernetes version 和全部 hashes，取得 exact rollback authorization 后执行：

```bash
bash scripts/deploy-truenas-k3s.sh --env-file deploy/truenas/deploy.env --disable-schedule \
  --baseline-values deploy/truenas/values-secure-manual-collection.yaml \
  --scheduling-overlay deploy/truenas/values-scheduled-off.yaml \
  --kube-version <ACTUAL_KUBERNETES_VERSION> --release-name a-stock --namespace a-stock
```

只有 `--disable-schedule` 的 server-observed postcondition 证明 exact CronJob 已删除后，才可检出已审阅的回退 commit，设置新的不可变 rollback image tag，并运行同一普通入口重建应用：

```bash
git checkout <REVIEWED_ROLLBACK_COMMIT_OR_TAG>
editor deploy/truenas/deploy.env
bash scripts/deploy-truenas-k3s.sh --env-file deploy/truenas/deploy.env
```

至少保留当前版本和上一个稳定版本。确认不再需要回退后，才删除旧镜像：

```bash
sudo k3s ctr --namespace k8s.io images remove \
  "localhost/a-stock-market-environment:<OLD_TAG>"
```

删除前核对受审回退包，确认不再需要该 tag。

## 16. SQLite 备份与恢复

Chart 默认把数据库放在 `/data/snapshots.sqlite3`，PVC 默认带 `helm.sh/resource-policy: keep`。卸载 release 不等于已经完成备份。

创建 SQLite 在线一致性备份：

```bash
kubectl --namespace a-stock exec deployment/a-stock -- \
  python -c "import sqlite3; src=sqlite3.connect('/data/snapshots.sqlite3'); dst=sqlite3.connect('/data/snapshots.backup.sqlite3'); src.backup(dst); dst.close(); src.close()"
```

下载备份到 VM：

```bash
kubectl --namespace a-stock exec deployment/a-stock -- \
  cat /data/snapshots.backup.sqlite3 \
  > "a-stock-snapshots-$(date +%Y%m%d-%H%M%S).sqlite3"
```

检查文件非空并生成校验和：

```bash
ls -lh a-stock-snapshots-*.sqlite3
sha256sum a-stock-snapshots-*.sqlite3
```

恢复前先停止 Deployment，避免覆盖正在使用的数据库：

```bash
kubectl --namespace a-stock scale deployment/a-stock --replicas=0
```

恢复属于破坏性操作。确认 namespace、release、PVC 和备份文件无误后，使用挂载同一 PVC 的临时维护 Pod 写回，完成后再把 Deployment 恢复为 1。不要直接编辑 SQLite 二进制文件，也不要在 Pod 运行时用普通文件复制覆盖数据库。

## 17. 退役

仓库当前不提供通用 release 退役入口。不得直接执行原始 `helm uninstall`：它会绕过 release lock、stored/live CronJob 前置检查和失败补偿。退役必须另建受审操作包，先冻结 namespace、release、exact CronJob、完整 Helm values、PVC/PV 身份及恢复路径，再由覆盖精确动作的授权执行。

默认 `persistence.keep=true`，受审退役流程应先检查 Chart 创建的 PVC：

```bash
kubectl --namespace a-stock get pvc
```

只有在完成备份、明确不再需要数据并确认目标名称后，才手动删除 PVC：

```bash
kubectl --namespace a-stock delete pvc a-stock-data
```

删除 PVC 可能触发 StorageClass 回收底层数据，通常不可恢复。删除 namespace 前同样要检查其中是否还有其他资源。

## 18. 常见故障

### Pod 显示 ImagePullBackOff

检查：

```bash
kubectl --namespace a-stock get deployment/a-stock \
  -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
sudo k3s ctr --namespace k8s.io images list | grep a-stock-market-environment
```

镜像名和 tag 必须逐字符一致，`image.pullPolicy` 应为 `IfNotPresent`。如果 Pod 被调度到另一节点，需要在该节点重复导入。

### Pod 显示 ErrImageNeverPull

本 Chart 默认不是 `Never`。检查是否有环境 values 覆盖了 pull policy；通常使用 `IfNotPresent` 更便于诊断。

### PVC 一直 Pending

```bash
kubectl --namespace a-stock describe pvc a-stock-data
kubectl get storageclass
```

确认 `persistence.storageClass` 使用 TrueNAS 实际存在的 StorageClass，并检查 provisioner Pod 和事件。

### Ingress 返回 404

```bash
kubectl --namespace a-stock describe ingress a-stock
kubectl get ingressclass
```

检查 `ingress.className`、Host header 和内部 DNS。使用 host 限定的 Ingress 时，直接访问 IP 而不发送 Host header 会得到 404。

### Helm 连接 k3s 报 x509 或 connection refused

- 检查 kubeconfig 的 server 是否仍为 `127.0.0.1`。
- 检查 VM 到 `<TRUENAS_IP>:6443` 的连通性。
- 检查证书 SAN 是否包含使用的 IP/主机名。
- 不要通过关闭 TLS 校验长期绕过。

### 容器启动但行情 API 返回 503

`/api/health` 不访问外部行情源。健康检查成功而行情接口失败时，检查 Pod 到通达信 TCP、腾讯、百度、新浪和东方财富 HTTPS 的出口网络与 DNS：

```bash
kubectl --namespace a-stock logs deployment/a-stock --tail=300
```

provider 失败必须保留 `degraded`、`missing` 或 `insufficient`，不能通过重启 Pod 或填 0 隐藏。

### 构建出现 exec format error

Podman 的 `--platform` 与 k3s 节点架构不一致。比较：

```bash
podman image inspect "$IMAGE" --format '{{.Architecture}}'
sudo k3s kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.nodeInfo.architecture}{"\n"}{end}'
```

重新以节点架构构建并使用新 tag。

## 19. 发布检查清单

- [ ] Git commit/tag 已记录。
- [ ] Podman 构建使用正确目标架构和新 tag。
- [ ] VM 容器烟测通过。
- [ ] tar 的 SHA-256 在 TrueNAS 校验通过。
- [ ] 镜像已进入 containerd `k8s.io` namespace，名称与 Helm values 一致。
- [ ] StorageClass 和 IngressClass 来自目标集群实际输出。
- [ ] `helm lint` 和 `helm template` 通过。
- [ ] 通用写操作只使用 `scripts/deploy-truenas-k3s.sh`，提交完整 baseline values，且未继承历史 values、直接调用 Helm write 或恢复历史 revision。
- [ ] 写前候选 baseline 为 `enabled=false`、`suspend=true`，Helm stored manifest 与 live state 均无 application CronJob；若此前存在，已先完成受审 `--disable-schedule`。
- [ ] 发布后 `kubectl --namespace a-stock get cronjob` 不包含应用 CronJob；只有另行授权的受控调度路径可保留 `suspend=true` 的资源。
- [ ] Deployment rollout、Pod、PVC、Ingress 和 `/api/health` 正常。
- [ ] SQLite 已备份，旧稳定镜像尚未删除。
- [ ] 临时 kubeconfig 导出副本已从 TrueNAS 数据集删除。
