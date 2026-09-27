// Regenerates src/api/schema.d.ts from the backend's OpenAPI schema (works on Windows and Unix).
import { execFileSync } from 'node:child_process'
import { existsSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'

const backend = resolve(import.meta.dirname, '../../backend')
const python = [join(backend, '.venv/Scripts/python.exe'), join(backend, '.venv/bin/python')].find(existsSync)
if (!python) throw new Error('backend/.venv not found: run `uv sync` in backend first')

const spec = execFileSync(python, ['-c', 'import json; from app.main import app; print(json.dumps(app.openapi(), indent=1))'], {
  cwd: backend,
  env: { ...process.env, BUDGET_SCHEDULER_ENABLED: 'false' },
  maxBuffer: 64 * 1024 * 1024,
})
writeFileSync('openapi.json', spec)
execFileSync('npx', ['-y', 'openapi-typescript@7', 'openapi.json', '-o', 'src/api/schema.d.ts'], { stdio: 'inherit', shell: true })
