# Research Assistant Dashboard

A high-fidelity React/Next.js dashboard for orchestrating structured multi-agent research workflows.

## Key Features

- **Job Management**: Browse, create, and initialize isolated research repositories.
- **Workflow Orchestration**: Launch background Python workers and stream real-time logs through a dedicated console.
- **Interactive Training**: Generalize job knowledge back to family fixtures for reusable research presets.
- **Git Integration**: Native filesystem and Git-backed persistence for all edits and execution artifacts.

## Technology Stack

- **Framework**: [Next.js 15 (App Router)](https://nextjs.org/)
- **Styling**: [Tailwind CSS 4](https://tailwindcss.com/)
- **Icons**: [Lucide React](https://lucide.dev/)
- **Animations**: [Framer Motion](https://www.framer.com/motion/)

## API Endpoints

### Jobs
- `GET /api/jobs`: List active and archived jobs.
- `POST /api/jobs`: Create and initialize a new research job repo.
- `GET /api/jobs/[jobId]`: Get full metadata and file contents for a job.

### Execution
- `POST /api/jobs/[jobId]/run`: Start a research run.
  - Query param `mode=auto`: Full automated execution (uses `execute_workflow.py`).
  - Query param `mode=scaffold`: Structural preparation only (uses `run_workflow.py`).

### Training
- `GET /api/jobs/[jobId]/train?family=[name]`: Fetch current fixtures and suggested job overrides.
- `POST /api/jobs/[jobId]/train`: Save approved generalizations back to the fixture backend.

## Development

Install dependencies and start the dev server:

```bash
npm install
npm run dev
```

Visit `http://localhost:3000` to access the dashboard.
