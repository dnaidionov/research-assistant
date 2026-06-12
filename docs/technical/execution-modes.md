# Technical Documentation: Dashboard Execution Modes

The Research Assistant dashboard supports multiple execution modes to balance automated research with manual intervention and scaffolding.

## API Integration

**Endpoint**: `POST /api/jobs/[jobId]/run`

### Query Parameters
- `mode` (string): Execution behavior.
  - `auto` (default): Executes the full research pipeline via `execute_workflow.py`.
  - `scaffold`: Only prepares the run directory structure via `run_workflow.py`.

### Backend Implementation
The API handler (`/api/jobs/[jobId]/run/route.ts`) dynamically resolves the target Python script based on the `mode` parameter:

```typescript
const mode = url.searchParams.get('mode') || 'auto';
const scriptFile = mode === 'scaffold' ? 'run_workflow.py' : 'execute_workflow.py';
const scriptPath = path.join(SCRIPTS_DIR, scriptFile);
```

## Execution Logic

1. **Automated Mode (`auto`)**:
   - Spawns `execute_workflow.py`.
   - Streams live `stdout`/`stderr` back to the dashboard console.
   - Automatically handles post-run git commits and pushes.
   - Transitions job status from `idle` to `completed` or `failed`.

2. **Scaffolding Mode (`scaffold`)**:
   - Spawns `run_workflow.py`.
   - Creates the necessary directory structure (`runs/run-XXX/`) and initial metadata.
   - Does NOT launch agents.
   - Useful for researchers who want to manually inspect or modify prompt packets before execution.
   - **Status**: The run is tagged as `scaffolded` in the dashboard sidebar history.
   - **Git Persistence**: The runner still performs a commit/push after successful directory creation to ensure the scaffold is preserved.

## UI Presentation
The "Launch Run" button in `JobDetails.tsx` is implemented as a split-dropdown:
- Main action: Triggers the default `auto` mode.
- Dropdown options:
  - **Run everything (auto)**
  - **Just scaffold (manual run)**
