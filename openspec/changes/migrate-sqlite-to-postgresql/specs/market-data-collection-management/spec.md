## ADDED Requirements

### Requirement: Provider-free PostgreSQL status reads
Collection management status and task history SHALL read from PostgreSQL without invoking providers and SHALL remain available while another connection performs collection writes.

#### Scenario: Status is read during collection
- **WHEN** a CronJob is collecting one or more datasets
- **THEN** the status API reads the latest committed PostgreSQL state without waiting for provider work or acquiring the active dataset/date lease

#### Scenario: Collection write fails
- **WHEN** a PostgreSQL transaction fails while committing one task
- **THEN** successful sibling task commits and retained snapshots remain visible, and the failed task exposes an auditable warning

