# Repository Structure

## Root

Default local layout:

~/Projects/research-hub/

├── research-assistant/
└── jobs/

These paths are defaults, not hard requirements. `jobs_root` is configurable through `config/paths.yaml`.
`jobs-index/` is not. It remains inside the assistant repo.

---

## Assistant Repo

Contains:
- system logic
- templates
- prompts
- schemas

Does NOT contain:
- research data

---

## Jobs Folder

Each subfolder is:
- an independent Git repo
- a single research case

Example:

jobs/
  my-project-1/
  my-project-2/

---

## Linking

Assistant references jobs via:

jobs-index/

No embedding, no submodules.

---

## Rule

Assistant = engine  
Jobs = cases
