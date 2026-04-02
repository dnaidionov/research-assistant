import { NextResponse } from 'next/server';
import fs from 'fs/promises';
import path from 'path';
import yaml from 'yaml';
import { loadRepoPaths } from '@/lib/repoPaths';

const { jobsIndexDir: JOBS_INDEX_DIR, jobsRoot: JOBS_DIR, templateDir: TEMPLATE_DIR } = loadRepoPaths();

export async function GET() {
  try {
    const activeDir = path.join(JOBS_INDEX_DIR, 'active');
    const archivedDir = path.join(JOBS_INDEX_DIR, 'archived');
    
    // Helper to read yaml files from a directory
    async function readJobsFromDir(dir: string, defaultStatus: string) {
      if (!await fs.stat(dir).catch(() => false)) return [];
      
      const files = await fs.readdir(dir);
      const jobs = [];
      
      for (const file of files) {
        if (!file.endsWith('.yaml')) continue;
        
        try {
          const content = await fs.readFile(path.join(dir, file), 'utf-8');
          const parsed = yaml.parse(content);
          
          jobs.push({
            ...parsed,
            status: parsed.status || defaultStatus,
            // Ensure visibility fallback
            visibility: parsed.visibility || 'private'
          });
        } catch (err) {
          console.error(`Failed to parse ${file}`, err);
        }
      }
      return jobs;
    }

    const activeJobs = await readJobsFromDir(activeDir, 'active');
    const archivedJobs = await readJobsFromDir(archivedDir, 'archived');

    const allJobs = [...activeJobs, ...archivedJobs];

    // Extract tags and families for UI autocomplete
    const allTags = Array.from(new Set(allJobs.flatMap(j => j.tags || []))).filter(Boolean);
    const allFamilies = Array.from(new Set(allJobs.map(j => j.family || 'neutral'))).filter(Boolean);

    // Sort active first, then alphabetically by name
    allJobs.sort((a, b) => {
      if (a.status === 'active' && b.status !== 'active') return -1;
      if (a.status !== 'active' && b.status === 'active') return 1;
      return (a.display_name || '').localeCompare(b.display_name || '');
    });

    return NextResponse.json({ jobs: allJobs, metadata: { tags: allTags, families: allFamilies } });
  } catch (error) {
    console.error('Failed to load jobs:', error);
    return NextResponse.json({ error: 'Failed to load jobs' }, { status: 500 });
  }
}

import { exec } from 'child_process';
import util from 'util';
const execAsync = util.promisify(exec);

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const { name, family, visibility, tags, brief_excerpt } = body;
    
    if (!name) return NextResponse.json({ error: 'Name is required' }, { status: 400 });

    const job_id = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
    const jobPath = path.join(JOBS_DIR, job_id);
    
    if (await fs.stat(jobPath).catch(() => false)) {
      return NextResponse.json({ error: `Job directory ${job_id} already exists` }, { status: 400 });
    }

    // 1. Copy Template
    await fs.cp(TEMPLATE_DIR, jobPath, { recursive: true });

    // 2. Write brief.md
    if (brief_excerpt) {
      await fs.writeFile(path.join(jobPath, 'brief.md'), brief_excerpt);
    }

    // 3. Update config.yaml with the job_id topic
    const configPath = path.join(jobPath, 'config.yaml');
    if (await fs.stat(configPath).catch(() => false)) {
      const configStr = await fs.readFile(configPath, 'utf8');
      const parsedConfig = yaml.parse(configStr);
      if (parsedConfig && typeof parsedConfig === 'object') {
        parsedConfig.topic = job_id;
        await fs.writeFile(configPath, yaml.stringify(parsedConfig));
      }
    }

    // 4. Git init and first commit
    await execAsync(`git init`, { cwd: jobPath });
    await execAsync(`git add .`, { cwd: jobPath });
    await execAsync(`git commit -m "Initial commit for job ${job_id}"`, { cwd: jobPath });

    // 5. Create jobs-index entry
    const indexData = {
      job_id,
      display_name: name,
      local_path: path.relative(path.join(JOBS_INDEX_DIR, 'active'), jobPath),
      visibility: visibility || 'private',
      status: 'active',
      tags: tags || [],
      family: family || 'neutral'
    };
    
    const indexFilePath = path.join(JOBS_INDEX_DIR, 'active', `${job_id}.yaml`);
    await fs.writeFile(indexFilePath, yaml.stringify(indexData));

    return NextResponse.json({ success: true, job: indexData });
  } catch (error) {
    console.error('Failed to create job:', error);
    return NextResponse.json({ error: String(error) }, { status: 500 });
  }
}
