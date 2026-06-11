# Trader-Specific Agent Skill Output Contract

Create a trader-specific agent skill only after a reviewed dataset exists.

Minimum files for a generated trader skill:

- `SKILL.md` or equivalent platform entrypoint: trigger description and workflow
- `references/trader_profile.md`: account identity, market, style, data boundary
- `references/research_template.md`: high-quality thesis template
- `references/review_rules.md`: trader-specific semantic review notes

Do not bundle raw X exports, large CSVs, price histories, or cloned source repositories inside the skill package.

The generated agent skill should answer:

- What market does this trader operate in?
- What is their true high-quality thesis pattern?
- What posts should be ignored or deweighted?
- What evidence do they trust?
- How do they define risk?
- How should a new topic be analyzed in their style?

Platform notes:

- Claude Code: keep this as a local skill/workflow folder and expose the workflow through project instructions or slash-command style prompts.
- OpenClaw: import or adapt the folder as an agent skill package with the same scripts and references.
- Codex-style systems: keep `SKILL.md`, `references/`, and `scripts/` as the skill package structure.
