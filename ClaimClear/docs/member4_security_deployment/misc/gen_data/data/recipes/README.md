# Recipes

One JSON file per story: `dev/D1.json` … `dev/D8.json` (20 dev cases) and `heldout/H1.json` … `heldout/H16.json`
(40 held-out cases). Each holds the story facts, the few numbers it depends on, and 2-3 variants with the
insurer's mistake. Python computes all money from them.

> **Held-out recipes describe the planted mistakes in the held-out cases.** They are evaluation material: do not
> read them while building or tuning agents, and never give them to an agent.

- Stories in plain English: [STORIES_dev.md](STORIES_dev.md), [heldout/STORIES_heldout.md](heldout/STORIES_heldout.md)
- Field reference and every insurer-error kind: [../../generator/prompts/story_to_recipe.md](../../generator/prompts/story_to_recipe.md)
- How to build and validate: [../../generator/HOWTO.md](../../generator/HOWTO.md)

Tags: `MD` = D1-D4, `SK` = D5-D8, `Holdout` = H1-H16. The tag is copied into every case's answer file.
