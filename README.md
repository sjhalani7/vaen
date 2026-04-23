# VAEN

VAEN is a portable CLI for packaging and importing agentic coding setups.

It takes an `agent.yaml` manifest, bundles instructions, skills, and project-scoped MCP declarations into an OCI-backed `.agent` archive, and imports that setup into another repository without transporting secrets.

## What VAEN Packages

VAEN packages configuration and authoring files, not runtime environments.

- Main instructions and optional instruction includes
- Skill directories and their files
- Project-scoped MCP declarations
- Bundle metadata used for import, inspection, and validation

VAEN never packages credential values, `.env` files, private keys, OAuth state, or MCP server implementations.

## Install

Install from GitHub with `pipx`:

```bash
pipx install git+https://github.com/sjhalani7/vaen.git
```

Or install from a local clone:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

The CLI provides:

```bash
vaen validate
vaen build
vaen inspect
vaen import
vaen doctor
vaen cleanup
```

## Manifest

`agent.yaml` is the source of truth for a bundle.

```yaml
version: "0.1"
publisher: "Shiv Jhalani"

instructions:
  main: "~/.codex/AGENTS.md"
  includes:
    - "./style.md"

artifacts:
  - type: skills
    path: "~/.codex/skills/code-review"
  - type: skills
    path: "~/.codex/skills/refactor"

requiredVars:
  - OPENAI_API_KEY

mcp:
  servers:
    - name: context7
      transport: stdio
      command: npx
      args: ["-y", "@upstash/context7-mcp"]
      env_vars:
        - CONTEXT7_API_KEY

    - name: docs
      transport: http
      url: https://example.com/mcp
      http_headers:
        X-Region: us-east-1
      bearer_token_env_var: DOCS_MCP_TOKEN
      header_env_vars:
        X-API-Key: DOCS_MCP_TOKEN
```

Manifest rules:

- `version`, `publisher`, and `instructions.main` are required.
- `instructions.includes` is optional.
- `artifacts` is a list and may be empty for instructions-only bundles.
- `skills` is the supported artifact type.
- `requiredVars` stores environment variable names only, never values.
- `http_headers` stores non-secret static HTTP headers for MCP servers.
- `mcp` is optional and lives at the top level of the manifest.
- Source paths may point inside or outside the repo.

MCP support is host-neutral in the manifest. During import, VAEN writes the selected client format for Codex, Claude Code, or Copilot.

## Typical Flow

### 1. Validate

```bash
vaen validate -f examples/synthetic-fixture/agent.yaml
```

### 2. Build

```bash
vaen build -f examples/synthetic-fixture/agent.yaml
```

If `-o` is omitted, VAEN writes `<manifest-directory-name>.agent` in the working directory:

```text
examples/synthetic-fixture/agent.yaml -> synthetic-fixture.agent
```

You can choose the archive name:

```bash
vaen build -f examples/synthetic-fixture/agent.yaml -o shiv-setup.agent
```

### 3. Inspect

```bash
vaen inspect synthetic-fixture.agent
```

`inspect` reads the OCI archive and prints bundle metadata, normalized bundle paths, instructions, skills, MCP declarations, and required variable names.

### 4. Import

In the target repo:

```bash
vaen import /path/to/synthetic-fixture.agent
```

If the bundle contains MCP declarations, select the client config to write:

```bash
vaen import /path/to/synthetic-fixture.agent --client codex
vaen import /path/to/synthetic-fixture.agent --client claude
vaen import /path/to/synthetic-fixture.agent --client copilot
```

Default import writes root instructions to `AGENTS.md` and `CLAUDE.md`, and mirrors skills to `.agent/skills/...` and `.claude/skills/...`.

To target another agent directory:

```bash
vaen import /path/to/synthetic-fixture.agent --target copilot
```

This writes `COPILOT.md` and `.copilot/skills/...`.

Optional import overrides:

```bash
vaen import /path/to/synthetic-fixture.agent --target copilot --target-instructions-file-name copilot-instructions
vaen import /path/to/synthetic-fixture.agent --target copilot --target-skills-directory vscode
```

These write `copilot-instructions.md` and `.vscode/skills/...`.

### 5. Verify

```bash
vaen doctor
```

Use the same targeting and MCP client flags that were used during import:

```bash
vaen doctor --client codex
vaen doctor --target copilot --client copilot
vaen doctor --target copilot --target-instructions-file-name copilot-instructions
vaen doctor --target copilot --target-skills-directory vscode
```

`doctor` validates the imported structure and reports required environment variable names as warnings.

### 6. Cleanup

After confirming the activated files look right, remove the canonical stored copy:

```bash
vaen cleanup /path/to/synthetic-fixture.agent
```

Cleanup deletes `.agent/<bundle-name>` only. It does not delete root instruction files, skill mirrors, or MCP client config.

## Archive Layout

A `.agent` file is an OCI-style archive:

```text
bundle.agent
├── oci-layout
├── index.json
└── blobs/sha256/
    ├── <manifest blob>
    ├── <config blob>
    └── <layer blob>
```

The layer blob is a tar payload:

```text
vaen/metadata.json
instructions/...
skills/...
mcp/...
```

Path terminology:

- `source path`: where a file lives on the builder's machine
- `bundle path`: where that file is stored inside the `.agent`
- `materialized path`: where that file is written during import

This lets a builder reference files from places like `~/.codex/AGENTS.md` while keeping the bundle layout stable and machine-independent.

## Import Layout

Import writes a canonical stored copy first:

```text
.agent/<bundle-name>/
├── instructions/
├── mcp/
├── skills/
└── vaen/metadata.json
```

Then it writes activated files for the target repo:

- Root instruction files: `AGENTS.md` and `CLAUDE.md`, or the configured target filename.
- Skill mirrors: `.agent/skills/...` and `.claude/skills/...`, or the configured target skill directory.
- MCP client config: `.codex/config.toml`, `.mcp.json`, or `.github/mcp.json` when `--client` is used.

Included instruction files remain in `.agent/<bundle-name>/instructions/...`; they are not concatenated into the root instruction file.

## Safety Rules

VAEN fails before overwriting existing setup files.

- Existing root instruction files block import.
- Existing `.agent/<bundle-name>` directories block import.
- Existing mirrored skill names block import.
- Existing MCP client config files block import.

Build also rejects obvious secret file paths such as `.env`, `.env.*`, `*.pem`, `*.key`, and `id_rsa`. Detected secret values are never printed.

Credential handling is metadata-only:

- `requiredVars` and MCP env fields store variable names only.
- `doctor` does not read `.env` files.
- `doctor` does not inspect shell environment variables, keychains, or other credential stores.
- MCP validation checks local config syntax and expected file placement; it does not connect to MCP servers or validate auth.

## Examples

The test fixture is a compact reference manifest:

- [examples/synthetic-fixture/agent.yaml](examples/synthetic-fixture/agent.yaml)

The project-specific example is here:

- [examples/shiv-codex-setup/agent.yaml](examples/shiv-codex-setup/agent.yaml)

## License

VAEN is released under the MIT License.

The software is provided as-is, without warranty of any kind. The authors and copyright holders are not liable for claims, damages, or other liability arising from use of the software. See [LICENSE](LICENSE) for the full license text.
