# VAEN Agent Setup Packages

Portable `.agent` archives for popular, reputable public agent setups.

Each archive preserves the upstream setup's main instruction file, skills, attribution, and license metadata so it can be imported with VAEN.

## Packages

| File | Source | Contents | Use when |
| --- | --- | --- |
| `mattpocock-skills.agent` | `mattpocock/skills` | All promoted skills from `engineering`, `productivity`, and `misc` | Complete one-command install. |
| `mattpocock-engineering.agent` | `mattpocock/skills` | `skills/engineering` | Daily code-work skills. |
| `mattpocock-productivity.agent` | `mattpocock/skills` | `skills/productivity` | General workflow skills. |
| `mattpocock-misc.agent` | `mattpocock/skills` | `skills/misc` | Extra utility skills. |

## Import

```bash
vaen import mattpocock-skills.agent
vaen doctor
```

For client-specific output:

```bash
vaen import mattpocock-skills.agent --client codex
```

## Attribution

These are unofficial VAEN packages of upstream open-source agent setup files. They are not official releases from the upstream authors. Keep bundled license and attribution files with redistributed copies.
