import fs from 'fs';
import path from 'path';
import yaml from 'yaml';

const DEFAULT_ASSISTANT_ROOT = '~/Projects/research-hub/research-assistant';
const DEFAULT_JOBS_ROOT = '~/Projects/research-hub/jobs';

function expandHome(input: string): string {
  if (!input.startsWith('~/')) return input;
  const home = process.env.HOME;
  return home ? path.join(home, input.slice(2)) : input;
}

export function loadRepoPaths() {
  const assistantRepoRoot = path.resolve(process.cwd(), '../..');
  const configPath = path.join(assistantRepoRoot, 'config', 'paths.yaml');
  let assistantRoot = DEFAULT_ASSISTANT_ROOT;
  let jobsRoot = DEFAULT_JOBS_ROOT;

  if (fs.existsSync(configPath)) {
    const parsed = yaml.parse(fs.readFileSync(configPath, 'utf8')) || {};
    if (typeof parsed.assistant_root === 'string' && parsed.assistant_root.trim()) {
      assistantRoot = parsed.assistant_root;
    }
    if (typeof parsed.jobs_root === 'string' && parsed.jobs_root.trim()) {
      jobsRoot = parsed.jobs_root;
    }
  }

  const resolvedAssistantRoot = path.resolve(expandHome(assistantRoot));
  const resolvedDefaultAssistantRoot = path.resolve(expandHome(DEFAULT_ASSISTANT_ROOT));
  if (resolvedAssistantRoot !== assistantRepoRoot && resolvedAssistantRoot !== resolvedDefaultAssistantRoot) {
    throw new Error(`Configured assistant_root ${resolvedAssistantRoot} does not match actual repo root ${assistantRepoRoot}.`);
  }

  return {
    assistantRepoRoot,
    jobsRoot: path.resolve(expandHome(jobsRoot)),
    jobsIndexDir: path.join(assistantRepoRoot, 'jobs-index'),
    templateDir: path.join(assistantRepoRoot, 'templates', 'job-template'),
    fixturesDir: path.join(assistantRepoRoot, 'fixtures', 'reference-job', 'families'),
  };
}
