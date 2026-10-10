# Third-party components

`vendor/webui.html` is the compiled `stable-diffusion.cpp` WebUI, taken from the
`master-951-f89d9b1` release (`f89d9b13d730eabeede7314ce49dacd18d3c90c2`).
Its upstream MIT license is included in `vendor/stable-diffusion.cpp-LICENSE`.
The compiled Vue runtime includes its license marker. Vue's MIT license is
included in `vendor/Vue-LICENSE`; see https://github.com/vuejs/core/blob/main/LICENSE.

Model weights, CUDA binaries and Python dependencies are downloaded separately.
Their own licenses apply; this project's MIT license does not relicense them.

Sources and revisions are listed in `models-manifest.json`:

- https://github.com/leejet/stable-diffusion.cpp
- https://huggingface.co/AtomicChat/Qwen-Image-2.1-Turbo-GGUF
- https://huggingface.co/AtomicChat/Qwen-Image-2.1-Turbo-Uncensored-GGUF
- https://huggingface.co/Comfy-Org/Qwen-Image-2.1

Python packages are pinned in `service/requirements.txt`.
