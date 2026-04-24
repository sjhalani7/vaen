# Quick Start

Install VAEN:

```bash
pipx install git+https://github.com/sjhalani7/vaen.git
```

Create a minimal instruction file:

```bash
mkdir my-agent
cd my-agent
printf "# Agent Instructions\n\nUse concise, direct answers.\n" > AGENTS.md
```

Create `agent.yaml`:

```yaml
version: "0.1"
publisher: "Your Name"

instructions:
  main: "./AGENTS.md"

artifacts: []
```

Validate and build the archive:

```bash
vaen validate -f agent.yaml
vaen build -f agent.yaml -o my-agent.agent
```

Inspect the archive:

```bash
vaen inspect my-agent.agent
```

Import it into another repo:

```bash
mkdir ../target-repo
cd ../target-repo
vaen import ../my-agent/my-agent.agent
vaen doctor
```

The imported repo now has root instruction files, activated skill mirror
directories, and a canonical stored copy:

```text
target-repo/
├── AGENTS.md
├── CLAUDE.md
├── .agent/
│   ├── my-agent/
│   │   ├── instructions/
│   │   └── vaen/metadata.json
│   └── skills/
└── .claude/
    └── skills/
```
