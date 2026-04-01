# Research Assistant UI Specification

## Overview

The Research Assistant UI is a web-based dashboard designed to manage research jobs, agent configurations, and workflow execution. It acts as a visual orchestration layer over the existing CLI tools, preserving the strict isolation between the assistant logic and the individual research job repositories.

## Guiding Principles

- **Card-Based Hierarchy**: Information flows from general (job list) to specific (run inspection) through interactive cards and modals.
- **Explicit Editing Mode**: All configurations and briefs default to a secure, read-only view. The user must explicitly enter edit mode to make changes, protecting against accidental modifications.
- **Git-Backed Traceability**: The UI does not use an independent database. The filesystem and local git repositories remain the absolute source of truth. Every configuration save or automated run triggers native git commits and pushes.
- **Premium Aesthetics**: The application uses a rich, dark-mode styling paradigm focusing on clarity, animations, and modern typography to provide an engaging interface.

## Core Capabilities

### 1. Job Directory (Home)
- Populated directly from `jobs-index/`.
- Displays critical metadata including **Status** (Active/Archived), **Visibility** (Private/Public based on repository config), and **Tags**.
- Provides a centralized view of all active research fronts without exposing their detailed contents until requested.

### 2. Workspace Initialization (New Job)
- Captures Display Name, Research Family, Visibility, Tags, and an optional Initial Brief.
- Automatically generates sluggified job IDs.
- Clones default templates (`config.yaml`) based on the selected Research Family.
- Creates full structure in `../../../jobs/<job_id>`, initializes a Git repository, performs the initial commit, and registers the job back to `jobs-index`.

### 3. Configuration Management
- When a job is selected, opens the **Job Details** view.
- Presents side-by-side cards for the Research Brief (`brief.md`) and Configuration (`config.yaml`).
- Implements **Unsaved Changes Protection**: Intercepts navigational state to warn users if they try to close or interact with other tools before committing dirty fields.
- Saving immediately writes to the filesystem and performs a `git add . && git commit` routine in the background.

### 4. Execution & Monitoring
- **Launch Run**: Initiates the Python backend (`execute_workflow.py`) via async `child_process` spawning.
- **Run Console**: A dedicated modal captures real-time `stdout` and `stderr` streams directly from the executed pipeline, rendering it visually.
- **Automated Post-Run Integrations**: Whether successful or failed, the backend automatically performs git commits and pushes to origin upon termination.
- **Train Family**: An action visible after an initial run, reserved for utilizing job knowledge to populate the fixtures of an underlying Research Family.

### 5. Run Inspection
- **Hierarchical Artifact Viewer**: Inspect structured JSON prompt packets, intermediate stage outputs, and running logs through a file navigator.
- **Embedded Reports**: Parses and injects the standalone `final_report.html` into a secure iFrame `srcDoc` for immediate consumption.
- **Export Paths**: Buttons allow researchers to easily copy HTML content to their keyboards or open raw API data directly.

## Technology Stack

- **Framework**: Next.js (App Router API endpoints)
- **Styling**: Tailwind CSS V4, Lucide Icons, Framer Motion
- **Runtime Environment**: Node.js backend executing shell commands interacting with Python scripts
- **Host Location**: `dashboards/ui`
