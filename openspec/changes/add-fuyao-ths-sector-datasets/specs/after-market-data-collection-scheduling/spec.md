## MODIFIED Requirements

### Requirement: Complete dataset coverage and failure isolation
Each explicitly enabled scheduled run SHALL request `core`, `breadth`, `limits`, `industry-ranking`, `sector-turnover`, `sector-breadth`, and `activeDirection` through the collection coordinator. It SHALL execute sector tasks in the order `industry-ranking -> sector-turnover -> sector-breadth`; a failure in one task MUST NOT stop, roll back, or invalidate successful unrelated tasks.

#### Scenario: All scheduled datasets succeed
- **WHEN** all seven scheduled tasks complete successfully
- **THEN** the run finishes as `success`, every snapshot is committed, and the selected date's materialized aggregate is rebuilt from compatible exact-date data

#### Scenario: One scheduled dataset fails
- **WHEN** one task fails while at least one other task succeeds
- **THEN** successful snapshots remain committed, dependent tasks are blocked only when their prerequisites are incompatible, and the parent run finishes as `partial`

#### Scenario: Every scheduled dataset fails
- **WHEN** none of the seven tasks can produce or retain a valid exact-date result
- **THEN** the parent run finishes as `failed` and no prior successful snapshot is deleted or overwritten

## ADDED Requirements

### Requirement: Schedule defaults remain disabled and suspended after migration
Replacing `sectors` with three sector tasks MUST NOT implicitly activate scheduled collection. Repository defaults SHALL remain `enabled=false` and `suspend=true`, and an existing reviewed schedule requires a new explicit review before it may include the new provider-backed tasks.

#### Scenario: Default chart is rendered
- **WHEN** deployment manifests are rendered without an explicit schedule activation
- **THEN** no provider-backed CronJob can run and the new sector tasks remain inactive
