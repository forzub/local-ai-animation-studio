# PROJECT STATE

Updated: 2026-08-30

## Mission

Подготовить от начала до конца локальный AI-production stack для будущих анимационных проектов.

Нужные функции:

1. генерация/редактирование изображений;
2. image-to-video и text-to-video;
3. сохранение постоянства персонажей;
4. TTS / narration;
5. sound effects;
6. генерация оригинальной музыки;
7. upscale / interpolation при необходимости;
8. сборка и кодирование финальных shots;
9. сохранение provenance, версии модели, workflow, seed и лицензии.

## Hardware contract

Target workstation:

- Intel Core i7-9850H, 6C/12T
- 64 GB RAM
- NVIDIA Quadro RTX 3000
- 6 GB VRAM
- Windows 10

Hard constraint: production stack должен иметь рабочий low-VRAM режим. Модели, практически требующие 12-24+ GB VRAM, не являются базовым dependency.

## Architecture decisions

- Orchestrator: ComfyUI.
- FFmpeg используется как обычный deterministic media tool.
- AI-model weights не коммитятся в Git.
- Каждый используемый checkpoint получает запись в `registry/models.yaml`.
- Для каждого production asset сохраняются model/version/workflow/seed/reference metadata.
- Experimental и production-approved модели различаются.
- Non-commercial weights могут использоваться только в экспериментах и не должны попадать в production master.
- Конкретный shot должен существовать независимо от конкретной AI-модели.

## Candidate stack

### Video
- Wan 2.2 TI2V-5B: primary candidate.
- LTX-Video 2B distilled/FP8: previz / low-VRAM candidate.
- CogVideoX-2B: secondary candidate.

### Music
- ACE-Step 1.5: primary candidate.

### TTS
- Kokoro: candidate; качество русского языка ещё должно быть проверено.

### Excluded from production for now
- MMAudio pretrained weights: non-commercial licensing concern.
- Wav2Lip public checkpoint: non-commercial restriction.

## Current phase

PHASE 0 — repository/bootstrap.

### Done
- project skeleton defined;
- Git policy defined;
- initial state file created;
- model registry schema created.

### Next
1. Создать локальный Git repository.
2. Создать пустой GitHub repository и подключить remote.
3. Проверить NVIDIA driver / CUDA capability / Python environment.
4. Установить FFmpeg.
5. Установить ComfyUI.
6. Выполнить первый clean acceptance test ComfyUI.
7. Добавлять модели строго по одной с отдельным acceptance test.

## Acceptance principle

Новая модель считается установленной только после того, как:

- checkpoint зарегистрирован;
- лицензия зафиксирована;
- SHA-256 зафиксирован;
- workflow запускается;
- sample output создаётся;
- VRAM/RAM/time отмечены;
- известные ограничения записаны в STATE.md или model manifest.

## Open questions

- Какой Python/CUDA/PyTorch набор наиболее стабилен на Quadro RTX 3000.
- Какая quantization Wan 2.2 оптимальна при 6 GB VRAM.
- Какая TTS-модель даст достаточно хороший русский narration.
- Какой commercial-safe video-to-SFX backend выбрать.
