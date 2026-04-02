import { NextResponse } from 'next/server';
import { spawn, exec } from 'child_process';
import path from 'path';
import util from 'util';
import { loadRepoPaths } from '@/lib/repoPaths';

const execAsync = util.promisify(exec);
const { jobsRoot: JOBS_DIR } = loadRepoPaths();
const SCRIPTS_DIR = path.resolve(process.cwd(), '../../scripts');

export const dynamic = 'force-dynamic';

export async function POST(req: Request, context: { params: Promise<{ jobId: string }> }) {
  try {
    const { jobId } = await context.params;
    const jobPath = path.join(JOBS_DIR, jobId);

    const encoder = new TextEncoder();
    
    const stream = new ReadableStream({
      start(controller) {
        // We first commit any unsaved changes if the frontend didn't already
        // But the frontend explicitly fires a save beforehand as per requirements.
        
        const url = new URL(req.url);
        const mode = url.searchParams.get('mode') || 'auto';
        const scriptFile = mode === 'scaffold' ? 'run_workflow.py' : 'execute_workflow.py';
        const scriptPath = path.join(SCRIPTS_DIR, scriptFile);
        
        controller.enqueue(encoder.encode(`Starting run for job: ${jobId} (${mode} mode)\n`));
        controller.enqueue(encoder.encode(`Executing: python3 ${scriptPath} --job-path ${jobPath}\n\n`));

        const child = spawn('python3', [scriptPath, '--job-path', jobPath], {
          cwd: process.cwd()
        });

        child.stdout.on('data', (data) => {
          controller.enqueue(encoder.encode(data.toString()));
        });

        child.stderr.on('data', (data) => {
          controller.enqueue(encoder.encode(data.toString()));
        });

        child.on('close', async (code) => {
          controller.enqueue(encoder.encode(`\n=== Run process exited with code ${code} ===\n`));
          
          try {
            controller.enqueue(encoder.encode(`Running post-run Git operations...\n`));
            await execAsync(`git add .`, { cwd: jobPath });
            await execAsync(`git commit -m "Automated Run Complete (Code: ${code})"`, { cwd: jobPath });
            
            // Push to origin
            try {
              await execAsync(`git push origin main`, { cwd: jobPath });
              controller.enqueue(encoder.encode(`Git commit and push successful.\n`));
            } catch (pushErr) {
              controller.enqueue(encoder.encode(`Could not push to origin (check remote configuration).\n`));
            }
          } catch(e) {
            controller.enqueue(encoder.encode(`Git integration error: ${String(e)}\n`));
          }
          
          controller.close();
        });

        child.on('error', (err) => {
          controller.enqueue(encoder.encode(`Failed to start process: ${err.message}\n`));
          controller.close();
        });
      }
    });

    return new Response(stream, {
      headers: {
        'Content-Type': 'text/plain; charset=utf-8',
        'Transfer-Encoding': 'chunked',
        'Cache-Control': 'no-cache, no-transform',
      },
    });
  } catch (error) {
    console.error('Run failed:', error);
    return NextResponse.json({ error: String(error) }, { status: 500 });
  }
}
