# Contributing to Afterhours

Each app or tool is an independent project. Put apps in `apps/<app-name>/` and
developer tools in `tools/<tool-name>/`, each with:

- A README explaining the purpose, prerequisites, installation and example usage.
- A dependency manifest and reproducible setup instructions.
- Tests for meaningful behavior and a documented verification command.
- Clear licensing and any project-specific security limitations.

Add the project to the root README catalog. Add its CI jobs under the collection's
root `.github/workflows/`; workflows nested inside tool directories do not run on
GitHub. Scope job working directories to the relevant project.

For AgentDock development, follow [its contribution guide](tools/agentdock/CONTRIBUTING.md).
From the collection root, you can run the local tests without installing providers:

```bash
cd tools/agentdock
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Do not commit `.agentdock/`, virtual environments, generated packages, private
chat history or credentials. Inspect staged files before publishing; ignore rules
do not remove files that are already tracked.

The collection has no automatic publishing workflow. Release each project using its
documented process and keep its own version and changelog.
