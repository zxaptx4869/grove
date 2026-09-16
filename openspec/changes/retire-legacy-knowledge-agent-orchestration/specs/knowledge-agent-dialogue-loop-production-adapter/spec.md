## ADDED Requirements

### Requirement: Unified production orchestration SHALL be independent from legacy executors

正式 Worker、`production_adapter`、Candidate、Entry Revision 与只读搜索 SHALL NOT import or invoke the retired Knowledge Agent runner or its planning graph. Shared cancellation control SHALL remain available from a module without answer-orchestration responsibilities.

#### Scenario: Formal answer Run executes after retirement

- **WHEN** Worker claims an ordinary answer Run
- **THEN** it invokes `production_adapter` and the unified dialogue loop without importing the retired runner
- **AND** cancellation at an existing safe boundary still produces the same cancelled terminal state

#### Scenario: Operation Run keeps cancellation behavior

- **WHEN** a Candidate or Entry Revision Run observes a committed cancellation request
- **THEN** the operation raises the shared cancellation signal and Worker finalizes it as cancelled
- **AND** no legacy answer executor is loaded

### Requirement: Legacy execution snapshots SHALL NOT enter the unified loop

The Worker MUST distinguish current unified-loop recovery state from retired execution checkpoints. A stale answer Run with a legacy or unknown execution step SHALL fail with an explicit recovery reason and MUST NOT be requeued into `production_adapter`; historical data SHALL remain readable.

#### Scenario: Legacy processing snapshot expires

- **WHEN** an answer Run exceeds its lease with a legacy planner, investigation, composite, coverage, or shared-graph step
- **THEN** Worker marks the Run failed and releases its active slot
- **AND** it does not invoke the unified loop or mutate historical execution records

#### Scenario: Current operation Run expires

- **WHEN** a Candidate or Entry Revision Run exceeds its lease within the existing retry limit
- **THEN** Worker retains the existing idempotent operation recovery behavior

