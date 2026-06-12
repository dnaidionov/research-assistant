# Technical Documentation: Training Workflow

The Train Family workflow provides a structured interface for Generalizing knowledge from a specific research job back to the core Research Family templates.

## API Integration

**GET /api/jobs/[jobId]/train?family=[family]**: Fetches the current fixture defaults and suggested overrides for a given job.
**POST /api/jobs/[jobId]/train**: Saves user-approved overrides to the fixture repository.

### Backend Path Resolution
The API handler (`/api/jobs/[jobId]/train/route.ts`) resolves names and paths consistently with the job runner:

```typescript
const JOBS_DIR = path.resolve(process.cwd(), '../../../jobs');
const FIXTURES_DIR = path.resolve(process.cwd(), '../../fixtures/reference-job/families');
```

## Manual Generalization Logic

1. **Information Extraction**:
   - Current Fixture: Extracted from `fixtures/reference-job/families/<family>/brief.md` and `config.yaml`.
   - Suggested Overrides: Extracted from the active job repository (`jobs/<jobId>/brief.md` and `config.yaml`).

2. **Frontend Comparison**:
   - The `JobDetails` component renders a dual-pane modal.
   - Left Pane: Read-only "Current Fixture Defaults".
   - Right Pane: Editable "Suggested Overrides" pre-populated with job-specific data.

3. **Selective Training**:
   - Users toggle checkboxes to determine which files to include in the update.
   - Deselected files are muted (`opacity-70`) and locked (`readOnly`) in the UI.
   - The POST payload only sends the `brief` and `config` strings when they are explicitly selected.

4. **Persistence**:
   - The backend performs recursive `fs.mkdir` to handle new family identifiers.
   - Files are written atomically using `fs.writeFile`.

## UI Presentation
The "Train <family>" button is only visible for jobs with a non-neutral family classification. It remains disabled until at least one file is selected for training.
