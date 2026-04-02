import { NextResponse } from 'next/server';
import fs from 'fs/promises';
import path from 'path';
import { loadRepoPaths } from '@/lib/repoPaths';

const { jobsRoot: JOBS_DIR } = loadRepoPaths();

async function getFiles(dir: string, baseDir: string = ''): Promise<{path: string, content: string, type: string}[]> {
  try {
    const entries = await fs.readdir(dir, { withFileTypes: true });
    let files: any[] = [];
    for (let entry of entries) {
      if (entry.name.startsWith('.')) continue; // ignore hidden
      
      const res = path.resolve(dir, entry.name);
      if (entry.isDirectory()) {
         files = files.concat(await getFiles(res, baseDir || dir));
      } else {
         const relPath = path.relative(baseDir || dir, res);
         const ext = path.extname(entry.name).toLowerCase();
         let content = "";
         if (['.md', '.json', '.html', '.txt', '.yaml', '.yml'].includes(ext)) {
            content = await fs.readFile(res, 'utf8');
         }
         files.push({
           path: relPath,
           name: entry.name,
           type: ext.substring(1) || 'txt',
           content
         });
      }
    }
    return files;
  } catch(e) {
    return [];
  }
}

export async function GET(req: Request, context: { params: Promise<{ jobId: string, runId: string }> }) {
  try {
    const { jobId, runId } = await context.params;
    const runPath = path.join(JOBS_DIR, jobId, 'runs', runId);
    
    if (!await fs.stat(runPath).catch(() => false)) {
      return NextResponse.json({ error: 'Run not found' }, { status: 404 });
    }

    const stageOutputsPath = path.join(runPath, 'stage-outputs');
    const promptPacketsPath = path.join(runPath, 'prompt-packets');
    
    const stageOutputs = await getFiles(stageOutputsPath);
    const promptPackets = await getFiles(promptPacketsPath);
    
    let htmlReport = null;
    try {
      htmlReport = await fs.readFile(path.join(runPath, 'final_report.html'), 'utf8');
    } catch(e) {}

    let log = await fs.readFile(path.join(runPath, 'run.log'), 'utf8').catch(() => null);

    let workflowState = null;
    try {
       const ws = await fs.readFile(path.join(runPath, 'workflow-state.json'), 'utf8');
       workflowState = JSON.parse(ws);
    } catch(e) {}

    let executionConfig = null;
    try {
       const ec = await fs.readFile(path.join(runPath, 'audit', 'execution-config.json'), 'utf8');
       executionConfig = JSON.parse(ec);
    } catch(e) {}

    return NextResponse.json({
       runId,
       stageOutputs,
       promptPackets,
       htmlReport,
       log,
       workflowState,
       executionConfig
    });
  } catch (error) {
    console.error('Failed to get run details:', error);
    return NextResponse.json({ error: String(error) }, { status: 500 });
  }
}
