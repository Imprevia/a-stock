## Purpose

在 Helm/k3s 中提供单主 PostgreSQL 数据库及应用连接合同，使 Dashboard Deployment 与盘后 CronJob 通过集群内服务并发访问而不共享 SQLite 文件卷。

## ADDED Requirements

### Requirement: Chart-managed PostgreSQL workload
The Helm chart SHALL render a single-replica PostgreSQL StatefulSet, an internal ClusterIP Service, and an independent retained RWO PVC when the database component is enabled.

#### Scenario: PostgreSQL component is rendered
- **WHEN** the chart is rendered with valid database values
- **THEN** it contains one PostgreSQL StatefulSet, one ClusterIP Service, and one database PVC with no NodePort or Ingress for PostgreSQL

#### Scenario: Application workloads are rendered
- **WHEN** Dashboard Deployment and scheduled CronJob are rendered
- **THEN** neither workload mounts the PostgreSQL PVC or any SQLite PVC; both reference the PostgreSQL Service and configured Secret

### Requirement: Secret-only database credentials
The chart SHALL require an existing Kubernetes Secret for PostgreSQL credentials and SHALL not render plaintext credentials into values, manifests, or container arguments.

#### Scenario: Existing Secret is absent
- **WHEN** PostgreSQL is enabled without the required existing Secret
- **THEN** Helm validation fails before rendering deployable application workloads

#### Scenario: PostgreSQL Service is internal
- **WHEN** the chart renders the PostgreSQL Service
- **THEN** the Service type is ClusterIP and no external listener is created

### Requirement: Database readiness dependency
The deployment workflow SHALL make schema migration and application rollout depend on PostgreSQL readiness.

#### Scenario: PostgreSQL is not ready
- **WHEN** the database readiness check fails
- **THEN** migration/service/schedule deployment does not report success and no scheduled collector is activated

