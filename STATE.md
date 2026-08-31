# PROJECT STATE

Updated: 2026-08-31

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


## Verified runtime baseline

- NVIDIA driver: 582.16
- NVIDIA-SMI CUDA compatibility: 13.0
- GPU: Quadro RTX 3000, compute capability 7.5, 6144 MiB VRAM
- Conda environment: `ai-studio`
- Python: 3.12.14
- PyTorch: 2.11.0+cu130
- CUDA runtime used by PyTorch: 13.0
- `torch.cuda.is_available()`: True
- real CUDA matrix multiplication acceptance: PASS
- FFmpeg: 9.0.1 full build
- ComfyUI: 0.34.0
- ComfyUI exact revision: `95d755cd8107a72258d452b5d3657273d571f07d`
- ComfyUI describe: `v0.34.0-18-g95d755cd`
- ComfyUI mode: `--lowvram`
- comfy-kitchen CUDA backend: available and enabled
- DynamicVRAM: enabled
- async weight offloading: enabled

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

## Acceptance results

### Image baseline — Stable Diffusion 1.5 FP16

Purpose: diagnostic baseline only; not selected as a production image model.

Checkpoint:
- `v1-5-pruned-emaonly-fp16.safetensors`
- SHA-256: `e9476a13728cd75d8279f6ec8bad753a66a1957ca375a1464dc63b37db6e3916`
- source: Comfy-Org Stable Diffusion v1.5 archive
- license: CreativeML Open RAIL-M

Reproducible test:
- 512x512
- batch 1
- seed `123456789`
- steps 20
- CFG 7.0
- sampler `dpmpp_2m`
- scheduler `karras`
- denoise 1.0

Observed:
- 20/20 sampling completed
- sampling rate: 2.04 it/s
- total prompt execution: 14.32 s
- BaseModel staged: 1639 MB
- SD1ClipModel staged: 235 MB
- AutoencoderKL staged: 318 MB
- CUDA OOM: none
- PNG produced: PASS
- local prompt moderation gate: none observed; a horror/violence prompt executed without refusal
- artistic quality: intentionally not evaluated; SD1.5 is retained only as a diagnostic baseline

Workflow:
- `workflows/image/image-baseline-sd15.json`

## Current phase

PHASE 2 — production image model selection.

### Done
- project skeleton defined;
- Git policy defined;
- initial state file created;
- model registry schema created;
- local Git repository and GitHub remote connected;
- NVIDIA/GPU baseline captured;
- isolated Conda runtime created;
- PyTorch/CUDA GPU compute accepted;
- FFmpeg installed and accepted;
- ComfyUI installed from Git and exact revision recorded;
- ComfyUI clean startup accepted;
- optimized CUDA backend enabled under cu130;
- low-VRAM/DynamicVRAM/offload path accepted;
- SD1.5 checkpoint hash verified;
- first end-to-end image generation accepted;
- absence of an external local prompt moderation gate verified empirically.

### Next
1. Compare current production-capable image models suitable for 6 GB VRAM.
2. Verify exact weights license and provenance before downloading the selected model.
3. Install one selected production image checkpoint/quantization.
4. Run quality, VRAM, speed and reproducibility acceptance.
5. Begin character-consistency/tooling evaluation after the production image baseline is stable.

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

- Какая production image model/quantization даст лучший баланс качества и скорости на 6 GB VRAM.
- Какая quantization Wan 2.2 оптимальна при 6 GB VRAM.
- Какая TTS-модель даст достаточно хороший русский narration.
- Какой commercial-safe video-to-SFX backend выбрать.
