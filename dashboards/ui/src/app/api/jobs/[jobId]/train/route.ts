import { NextResponse } from 'next/server';
import fs from 'fs/promises';
import path from 'path';
import { loadRepoPaths } from '@/lib/repoPaths';

const { jobsRoot: JOBS_DIR, fixturesDir: FIXTURES_DIR } = loadRepoPaths();

export async function GET(req: Request, context: { params: Promise<{ jobId: string }> }) {
  try {
    const { jobId } = await context.params;
    const url = new URL(req.url);
    const family = url.searchParams.get('family');

    if (!family) {
      return NextResponse.json({ error: 'Family is required' }, { status: 400 });
    }

    const jobPath = path.join(JOBS_DIR, jobId);
    const fixturePath = path.join(FIXTURES_DIR, family);

    const jobBrief = await fs.readFile(path.join(jobPath, 'brief.md'), 'utf8').catch(() => '');
    const jobConfig = await fs.readFile(path.join(jobPath, 'config.yaml'), 'utf8').catch(() => '');

    const fixtureBrief = await fs.readFile(path.join(fixturePath, 'brief.md'), 'utf8').catch(() => '');
    const fixtureConfig = await fs.readFile(path.join(fixturePath, 'config.yaml'), 'utf8').catch(() => '');

    return NextResponse.json({
       current: {
         brief: fixtureBrief,
         config: fixtureConfig
       },
       suggested: {
         brief: jobBrief,
         config: jobConfig
       }
    });
  } catch (error) {
    console.error('Failed to get train suggestions:', error);
    return NextResponse.json({ error: String(error) }, { status: 500 });
  }
}

export async function POST(req: Request, context: { params: Promise<{ jobId: string }> }) {
  try {
    const { jobId } = await context.params; // jobId is kept for log tracking
    const { family, brief, config } = await req.json();

    if (!family) {
      return NextResponse.json({ error: 'Family is required' }, { status: 400 });
    }

    const fixturePath = path.join(FIXTURES_DIR, family);
    
    // Ensure dir exists if training a brand new family alias
    await fs.mkdir(fixturePath, { recursive: true });
    
    if (brief !== undefined) {
      await fs.writeFile(path.join(fixturePath, 'brief.md'), brief, 'utf8');
    }
    
    if (config !== undefined) {
      await fs.writeFile(path.join(fixturePath, 'config.yaml'), config, 'utf8');
    }

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error('Failed to save train suggestions:', error);
    return NextResponse.json({ error: String(error) }, { status: 500 });
  }
}
