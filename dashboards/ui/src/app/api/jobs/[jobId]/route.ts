import { NextResponse } from 'next/server';
import fs from 'fs/promises';
import path from 'path';
import { exec } from 'child_process';
import util from 'util';
import { loadRepoPaths } from '@/lib/repoPaths';

const execAsync = util.promisify(exec);
const { jobsRoot: JOBS_DIR } = loadRepoPaths();

export async function GET(req: Request, context: { params: Promise<{ jobId: string }> }) {
  try {
    const { jobId } = await context.params;
    const jobPath = path.join(JOBS_DIR, jobId);
    
    if (!await fs.stat(jobPath).catch(() => false)) {
      return NextResponse.json({ error: 'Job not found' }, { status: 404 });
    }

    let config = '';
    let brief = '';
    let runsPath = path.join(jobPath, 'runs');
    let runsData: any[] = [];

    try { config = await fs.readFile(path.join(jobPath, 'config.yaml'), 'utf8'); } catch (e) {}
    try { brief = await fs.readFile(path.join(jobPath, 'brief.md'), 'utf8'); } catch (e) {}
    try {
      const runDirs = await fs.readdir(runsPath, { withFileTypes: true });
      const runFolders = runDirs.filter(d => d.isDirectory()).map(d => d.name);
      
      for (const runId of runFolders) {
        let runStatus = 'unknown';
        let workflowState = null;
        try {
          const wsPath = path.join(runsPath, runId, 'workflow-state.json');
          const wsContent = await fs.readFile(wsPath, 'utf8');
          workflowState = JSON.parse(wsContent);
          runStatus = workflowState.status || 'unknown';
        } catch (e) {}
        
        runsData.push({
          id: runId,
          status: runStatus,
          state: workflowState
        });
      }
      // Sort runs descending by id (assuming run-XXX format)
      runsData.sort((a, b) => b.id.localeCompare(a.id));
    } catch (e) {}

    return NextResponse.json({
      jobId,
      config,
      brief,
      runs: runsData
    });
  } catch (error) {
    console.error('Failed to get job:', error);
    return NextResponse.json({ error: String(error) }, { status: 500 });
  }
}

export async function PUT(req: Request, context: { params: Promise<{ jobId: string }> }) {
  try {
    const { jobId } = await context.params;
    const jobPath = path.join(JOBS_DIR, jobId);
    const body = await req.json();
    const { config, brief } = body;

    if (!await fs.stat(jobPath).catch(() => false)) {
      return NextResponse.json({ error: 'Job not found' }, { status: 404 });
    }

    let changed = false;

    if (config !== undefined) {
      await fs.writeFile(path.join(jobPath, 'config.yaml'), config);
      changed = true;
    }
    
    if (brief !== undefined) {
      await fs.writeFile(path.join(jobPath, 'brief.md'), brief);
      changed = true;
    }

    if (changed) {
      try {
        await execAsync(`git add config.yaml brief.md`, { cwd: jobPath });
        await execAsync(`git commit -m "UI: Update config and brief"`, { cwd: jobPath });
      } catch (gitErr) {
        console.warn('Git commit failed (maybe no changes or no git repo yet)', gitErr);
      }
    }

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error('Failed to update job:', error);
    return NextResponse.json({ error: String(error) }, { status: 500 });
  }
}
