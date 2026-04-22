# private/

Drop anything that shouldn't be public in here. The whole directory is
git-ignored except for this README, so nothing you put here will ship to
GitHub or leak into the public repo.

Typical contents:

- **Briefing context files** for your own projects or clients.
  Example: `private/my-project-context.md`, then run
  `distill research-brief -t tkg --context-file private/my-project-context.md --name my-project`
- **Custom site-batch seed files** with client or employer URLs.
  Example: `private/acme_seeds.json`, then run
  `distill site-batch private/acme_seeds.json --topic acme --seed-only`
- **Personal scratch notes**, draft prompts, intermediate research artifacts,
  anything you're experimenting with but don't want public yet.

The CLI's `--context-file` and seed-file arguments take any path, so
putting things under `private/` is just a convention — it's not magic.
What makes it safe is the entry in `.gitignore` that covers this folder.

For shippable examples, see:

- [`../docs/briefing-contexts/TEMPLATE.md`](../docs/briefing-contexts/TEMPLATE.md) — shape of a briefing context file
- [`../configs/example_seeds.json`](../configs/example_seeds.json) — shape of a site-batch seed file

If you write something you later decide should be public, move the file out
of `private/` into `docs/briefing-contexts/` or `configs/` and it becomes
part of the tracked tree.
