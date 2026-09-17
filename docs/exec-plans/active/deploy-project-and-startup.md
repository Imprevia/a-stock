# 部署项目并配置开机启动

## Stage

部署前修复与 TrueNAS k3s 发布

## Status

completed

## Acceptance

- 修复部署入口的本地预检阻断后，通过离线校验并成功发布 Dashboard 到配置的 TrueNAS k3s 集群。
- 保持生产定时采集 `enabled=false`、`suspend=true`，不创建或激活 CronJob。
- 验证 Deployment、Service、PVC、健康接口和 k3s 节点开机自启状态。

## Completion Evidence

- 修复 `scripts/deploy-truenas-k3s.sh` 基线解析遗漏的 `security`、`scheduling` 和 `storageClass` 字段。
- 将组件基线 PVC StorageClass 与现场只读证据对齐为 `local-path`；Helm lint 与 docs-contract fast 通过。
- 已执行镜像构建、传输和 Helm revision 10 尝试；PVC 未删除或替换。
- 已执行 `systemctl enable k3s`，远端回读为 `enabled` 且服务 `active`。
- 远端节点曾为 `NotReady`，CNI 配置目录为空，导致 Deployment Pod Pending 和 rollout 超时回滚；通过 TrueNAS `kubernetes.update` 校正实际 `node_ip=192.168.1.20`、`route_v4_interface=br0`、网关 `192.168.1.1` 后，CNI 已重新生成。
- 节点恢复 `Ready` 后重新执行 `--component service` 成功：Helm revision 13、Deployment `1/1`、Pod `Running`。
- `http://192.168.1.20:32001/api/health` 返回 HTTP 200 `{"status":"ok"}`，首页返回 HTTP 200。
- `systemctl is-enabled k3s=enabled` 且 `systemctl is-active k3s=active`。

## Remaining Gaps

- 无部署阻断项。后续如节点再次出现 `NetworkPluginNotReady`，应先按 runbook 恢复 TrueNAS CNI，再执行 service 发布。

## Next Step

保持 k3s systemd 自启和当前安全基线；后续版本继续使用受控 service 发布入口。
