# Architecture

## Principle

Git repository содержит control plane, а не тяжелые данные.

### Control plane
- source configuration;
- workflows;
- prompts;
- manifests;
- scripts;
- license/provenance records;
- shot metadata.

### Data plane
- model weights;
- caches;
- source footage;
- rendered frames;
- audio stems;
- final masters.

Data plane хранится локально вне Git либо в каталогах, исключённых через `.gitignore`.

## Suggested local layout

```text
local-ai-animation-studio/
  README.md
  STATE.md
  docs/
  registry/
    models.yaml
    licenses/
    manifests/
  workflows/
    image/
    video/
    audio/
    music/
    tts/
  scripts/
  projects/
  models/
  cache/
  outputs/
  vendor/
```

## Project layout

Каждый конкретный фильм/ролик создаётся в `projects/<project-id>/`.

Рекомендуемая структура:

```text
projects/<project-id>/
  script/
  storyboard/
  characters/
  references/
  shots/
  audio/
  music/
  master/
```

`shots/<shot-id>/` должен содержать metadata, достаточные для восстановления результата:
- prompt;
- negative prompt;
- model id;
- model version/hash;
- workflow version;
- seed;
- references;
- generation parameters;
- manual postprocess notes.
