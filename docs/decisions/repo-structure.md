# Repository Structure

## Root

~/Projects/research-hub/

├── research-assistant/
└── jobs/

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