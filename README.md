# Afterhours

**Apps, tools, and experiments built after hours.**

A personal collection of projects developed at home, from AI agents to everyday
tools. Each project has its own setup guide, dependencies, tests, and release notes.
Start with one tool; install only what it needs.

## Explore the tools

| Tool | What it does | Category | Status |
| --- | --- | --- | --- |
| [AgentDock](tools/agentdock/README.md) | Plan with Codex or Claude, implement with a local model, then return for review. | Coding workflow | Experimental |

### AgentDock

<p align="center">
  <a href="tools/agentdock/README.md">
    <img src="tools/agentdock/docs/assets/agentdock-title.png" alt="AgentDock: cloud planning, local coding and repairs, cloud review, then final verification." width="1100" />
  </a>
</p>

A terminal workspace with named agents, configurable models, local repair loops,
and clear handoffs between planning, coding, and review. Paid agents exit while
the local model works.

From your local checkout:

```bash
cd tools/agentdock
python3 scripts/install.py
agentdock
```

The installer requires `uv`. See the [complete setup guide](tools/agentdock/README.md#quick-start)
for provider CLIs, authentication and local models, and read AgentDock's
[current security limitations](tools/agentdock/SECURITY.md) before use.

## Repository layout

```text
Afterhours/
├── README.md
├── CONTRIBUTING.md
├── LICENSE
├── .github/workflows/
└── tools/
    └── agentdock/
        ├── README.md
        ├── pyproject.toml
        ├── src/agentdock/
        ├── tests/
        ├── scripts/
        └── docs/
```

| Preview | Project | Type | What it does |
| :---: | --- | --- | --- |
| <a href="apps/AiMail/palan.md"><img src="apps/AiMail/docs/interface-reference.png" alt="AiMail interface reference" width="160" /></a> | [AiMail](apps/AiMail/README.md) | App · Planned | Native macOS Gmail client with AI thread summaries and email drafting. |
| <a href="apps/Gp%20Notes/README.md"><img src="apps/Gp%20Notes/docs/workspace.png" alt="Gp Notes workspace" width="160" /></a> | [Gp Notes](apps/Gp%20Notes/README.md) | App | **From conversation to a considered draft.** Turn synthetic consultations into editable SOAP notes, then review and export. |
| <a href="tools/agentdock/README.md"><img src="tools/agentdock/docs/assets/working-screenshot.png" alt="AgentDock terminal workspace" width="160" /></a> | [AgentDock](tools/agentdock/README.md) | Tool | **Your coding agents, one workspace.** Plan with cloud models, build with local models, and keep the handoffs in view. |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the project structure and testing
expectations. Keep local configuration, model files, credentials and session logs
out of published changes.

## License

[MIT](LICENSE), unless a project explicitly specifies otherwise. Third-party
models, providers and dependencies retain their own licenses and terms.
