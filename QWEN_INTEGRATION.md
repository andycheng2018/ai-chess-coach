# Qwen integration

Andy’s `feature/vbot-qwen` is integrated into `add-llm-log` alongside the current
Android, stage-performance, safety-rescan and room-QR work.

On the Mac, double-click **Launch Chess Buddy Qwen.command**. This uses the
existing `ssh` and `cloudflared` installation and Cloudflare Access login to reach
Andy’s Mac Studio Ollama server through local port 18000. Complete any login
prompts yourself. An existing backend must report `coach.provider=qwen`; the
launcher asks you to stop an older/different backend rather than silently reusing
it. It manages only the tunnel it starts.

The launcher sets `LLM_PROVIDER=qwen`, `QWEN_BASE_URL=http://127.0.0.1:18000/v1`
and `QWEN_MODEL=qwen3.8-27b:latest` for its process. Normal launchers retain their
existing provider selection. Qwen coaching and Luna chat use the existing model
interfaces; the VBOT demo desk adds short reaction text tied to an existing,
verified/rehearsal controller event. Generated text has no motion authority.

Both coaching and reaction model attempts enter the existing unified audit
journal. Raw reaction output is retained there before display cleanup/truncation.
The existing TTS layer remains the speech playback path. This branch adds model
and commentary integration; it does not install a new on-dog audio pipeline.
The standalone Android provider continues using its existing settings and does
not enable the Mac’s loopback tunnel.

Validation uses mocked model responses and robot controls. Passing tests/builds
does not establish a live Cloudflare login, Qwen response or audible speech.
