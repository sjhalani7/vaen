# Matt Pocock VAEN Packages

Unofficial VAEN packages built from Matt Pocock's open-source `mattpocock/skills` repository.

Source: https://github.com/mattpocock/skills

Each `.agent` archive uses Matt's upstream `CLAUDE.md` as the main instruction file. VAEN package notes, upstream metadata, and license information are stored as additional bundled instruction files.

## Packages

| File | Contents | Use when |
| --- | --- | --- |
| `mattpocock-skills.agent` | All promoted skills from `engineering`, `productivity`, and `misc` | You want the complete one-command install. |
| `mattpocock-engineering.agent` | `skills/engineering` | You only want daily code-work skills. |
| `mattpocock-productivity.agent` | `skills/productivity` | You only want general workflow skills. |
| `mattpocock-misc.agent` | `skills/misc` | You want the extra utility skills Matt keeps around. |

## Import

```bash
vaen import mattpocock-skills.agent
vaen doctor
```

For client-specific output:

```bash
vaen import mattpocock-skills.agent --client codex
```

## Verification

The four archives were rebuilt from local manifests, imported into fresh temporary directories, and verified:

- `vaen validate` passed for every manifest.
- `vaen build` produced all four archives.
- `vaen import` succeeded for every archive.
- `vaen doctor` passed for every default import.
- Imported root `AGENTS.md` and `CLAUDE.md` matched Matt's upstream `CLAUDE.md`.
- Extracted skill directories matched the upstream skill directories recursively.

## Attribution

These packages are not official Matt Pocock releases. They package the upstream open-source skill files into VAEN archives for portability. Keep the bundled upstream license and attribution with redistributed copies.
