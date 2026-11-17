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

## Аудит 2026-11-17 (Этап А переработки в студию)

Новая цель: локальная студия с веб-интерфейсом (режим → модель → референсы → промпт → результат), без ручной работы с графами.

### Фактически установлено (vendor/ComfyUI/models)
| Модель | Файлы | Статус на 6 GB |
|---|---|---|
| FLUX.2 Klein 4B distilled fp8 | 3.9 GB + Qwen3-4B 7.7 GB + VAE | **работает быстро** |
| FLUX.2 Klein 4B base fp8 | 3.9 GB | не проверялась (для LoRA/CFG) |
| Wan 2.2 TI2V-5B Q4_K_M GGUF | 3.3 GB + UMT5 fp8 6.4 GB + VAE 1.3 GB | работает, медленно на 720p |
| Qwen-Image-Edit-2509 fp8 + Lightning 4-step | 19.5 GB + Qwen2.5-VL 8.9 GB | работает, ~40–50 мин/кадр — непрактично |
| Chroma1-HD fp8mixed | 8.8 GB + T5XXL fp8 4.9 GB | работает, ~20–40 мин/кадр — непрактично |
| SD 1.5 fp16 | 2 GB | только диагностика |

### Замеры через API ComfyUI (2026-11-17, --lowvram)
- Klein 4B T2I 1024×768, 4 шага: 46 с (холодный и тёплый старт одинаково), пик VRAM ~2.7 GB.
- Klein 4B edit, 2 референса (персонаж + сцена), 1024×1024: 207 с; персонаж корректно перенесён в сцену (лицо, плащ, обувь сохранены).
- Wan 2.2 TI2V-5B Q4 (по истории output, 2026-08-31): 512×288 1–3 с — минуты; 1280×704 3–5 с — около часа.

### Выводы
- ComfyUI годится как скрытый вычислительный движок: low-VRAM offload, fp8, GGUF, нативные ReferenceLatent (Klein) и Wan 2.2 уже работают. Замена на Diffusers потребовала бы перекачки весов и даёт худший low-VRAM режим.
- Ошибочно/избыточно: workflows хранились в UI-формате и правились вручную; `workflows/video/wan22-ti2v-5b-q4-smoke.json` пустой; тяжёлые Qwen-Edit 20B и Chroma 8.9B непригодны как модели по умолчанию.
- Предложенная архитектура: одно FastAPI-приложение, которое само запускает ComfyUI как дочерний процесс на localhost и программно строит API-графы из Python-«рецептов» моделей; SQLite-очередь и история; веб-UI без сборки.

## Этап Б + В — студия и референсы (2026-11-17) — ГОТОВО

Запуск: `studio.bat` → http://127.0.0.1:8800 (браузер открывается сам).

Устройство (`studio/`):
- `app.py` — FastAPI: API + статика веб-интерфейса; слушает только 127.0.0.1.
- `comfy.py` — сам запускает ComfyUI дочерним процессом (порт 8189, `--lowvram --disable-api-nodes`), отправляет API-графы, читает прогресс по WebSocket, отмена через `/interrupt`, понятные сообщения об OOM.
- `recipes/` — модели как Python-рецепты, графы строятся программно. Сейчас: `flux2-klein-4b` (t2i / edit / i2i, до 6 референсов с ролями).
- `jobs.py` — очередь (SQLite `outputs/studio.sqlite3`), один GPU-воркер, история, избранное.
- Результаты: `outputs/studio/<дата>/<job>/NN.png` + `job.json` (параметры, seed, файлы модели, отправленный промпт, графы) — для воспроизводимости.
- Вход/выход движка: `cache/comfy_input`, `cache/comfy_output`; загрузки референсов: `cache/uploads/<sha>.png`.

Референсы: роли (исходник, персонаж, внешность/одежда, окружение, стиль, композиция/поза) передаются Klein через ReferenceLatent + инструкцию «image N …» (отключается в расширенных настройках).

Приёмка на Quadro RTX 3000 (через API студии):
| Режим | Параметры | Время |
|---|---|---|
| t2i | 16:9, 0.5 Мп, 2 варианта | 111 с (оба) |
| edit (ночь, луна, снег) | 1 исходник, 1024×768 | 125 с, композиция сохранена |
| t2i + персонаж + окружение | 16:9, 0.75 Мп | 182 с, персонаж узнаваем |
| i2i (акварель, сила 0.6) | 1024×768 | 49 с |

GPU: CUDA видит только Quadro RTX 3000 (вторая карта — встроенная Intel UHD 630, CUDA недоступна).

Исправлено в ходе приёмки: в i2i исходник больше не подаётся как ReferenceLatent (иначе результат почти не менялся).

## Этап Г — видео (2026-11-17) — РАБОТАЕТ, качество ограничено моделью

Рецепт `studio/recipes/wan.py`: Wan 2.2 TI2V-5B Q4 GGUF, 24 кадра/с, mp4 h264.
- Режимы: текст → видео, изображение → видео (начальный кадр).
- Длительность 2–5 с, разрешения: черновик ~640×352, стандарт ~832×480 (по умолчанию), 720p ~1280×704.
- Камера: пресеты (наезд, отъезд, панорамы, облёт, следование, кран, ручная) → фраза в промпт.
- Референсы персонажа/окружения/стиля: двухэтапная задача — Klein 4B строит ключевой кадр по референсам, Wan анимирует; кадр сохраняется в результатах.
- «Продолжить с последнего кадра»: последний кадр видео (PyAV) становится начальным кадром следующего.
- Конечный кадр: не поддерживается моделью — честно указано в интерфейсе.

Замеры (Quadro RTX 3000):
| Тест | Время | Качество |
|---|---|---|
| i2v, сцена, наезд, 2 с, 544×416 | 103 с | хорошо: кадр сохранён, движение камеры и неба |
| t2v «лиса в лесу», 2 с, 640×352 | ~5 мин | плохо: объекта нет |
| референсы → кадр → видео, 2 с, 640×352 | 627 с | персонаж «плывёт», меняется |
| i2v того же кадра, 2 с, 832×480 | 807 с | персонаж стабилен, идёт; мелкие артефакты |

Вывод: Wan 5B на 6 ГБ пригодна для i2v в стандартном разрешении, но медленная и средняя по качеству. Кандидат на апгрейд — Wan 2.2 I2V A14B GGUF Q4 (high+low noise ≈ 2×8.5 ГБ) + lightx2v 4-step LoRA + wan_2.1_vae; даёт режим начального+конечного кадра. Требует скачивания ~18–19 ГБ — только по согласованию.

## Этап Г+ — Wan 2.2 I2V 14B (2026-11-17) — РАБОТАЕТ, 720p подтверждено

Скачано и проверено по SHA-256 (~20.5 ГБ): QuantStack Wan2.2-I2V-A14B HighNoise/LowNoise Q4_K_M GGUF, lightx2v 4-step LoRA (high/low, Comfy-Org), wan_2.1_vae.
Рецепт `WanI2V14B`: i2v и «начальный + конечный кадр», 4 шага (2 high + 2 low), CFG 1, shift 5, 16 кадров/с. Без начального кадра — ключевой кадр строится в Klein по промпту/референсам.

Размеры по короткой стороне: 720p = 1280×720 (14B, кратность 16), 1280×704 (5B, кратность 32 — родное); 480p = 848×480 / 864×480.

Замеры (тот же кадр, seed 42, 2 с = 33 кадра):
| Разрешение | Время | Качество |
|---|---|---|
| 848×480 | 748 с (12.5 мин) | персонаж стабилен, без артефактов |
| 1280×720 | 3007 с (50 мин) | персонаж стабилен, чёткие детали |

На 720p веса полностью стримятся из ОЗУ (0 МБ весов в VRAM), один шаг ≈ 10 мин.

Исправлено в ходе приёмки:
- OOM на 720p после предыдущей задачи → перед тяжёлой моделью движок выгружает всё из VRAM, при OOM шаг повторяется один раз после очистки.
- Ложный «обрыв соединения»: ping WebSocket не проходил во время тяжёлого VAE 720p → heartbeat отключён, при обрыве — переподключение и сверка с историей движка; падение процесса определяется по коду возврата.
- `studio.bat` при уже запущенной студии открывает браузер вместо ошибки занятого порта.

## Этап Д — доведение до продукта (2026-11-17) — частично

Готово: история с избранным и удалением, «Повторить» (тот же seed), «Новый seed», отмена задач (проверено: 2 с), автоперезапуск движка после падения (проверено), понятные ошибки (OOM, валидация графа), окно «Модели» (файлы, лицензии, ограничения), кнопка «Освободить память», статус GPU/VRAM/очереди, `job.json` с графами для воспроизводимости, SHA-256 в `registry/models.yaml`.

Не сделано: рецепты Qwen-Image-Edit-2509 и Chroma1-HD (медленные, требуют отдельной приёмки ~20–50 мин на кадр), страница настроек (сейчас переменные окружения `STUDIO_PORT`, `STUDIO_COMFY_PORT`, `STUDIO_HOST`), импорт старых результатов из `vendor/ComfyUI/output` в историю.

## Previous phase (до переработки)

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
