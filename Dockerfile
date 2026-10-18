# KI-Studio Worker: ComfyUI + Wan 2.2 Animate auf RunPod Serverless
# Basis: offizielles worker-comfyui (ComfyUI 0.34, CUDA 12.8, PyTorch 2.11)
FROM runpod/worker-comfyui:5.10.0-base

# --- Custom Nodes (gleiche wie in deinen Workflows A/B/C) ---
WORKDIR /comfyui/custom_nodes
RUN git clone --depth 1 https://github.com/kijai/ComfyUI-WanVideoWrapper.git && \
    git clone --depth 1 https://github.com/kijai/ComfyUI-WanAnimatePreprocess.git && \
    git clone --depth 1 https://github.com/kijai/ComfyUI-KJNodes.git && \
    git clone --depth 1 https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git && \
    git clone --depth 1 https://github.com/kijai/ComfyUI-segment-anything-2.git && \
    git clone --depth 1 https://github.com/Fannovel16/ComfyUI-Frame-Interpolation.git

COPY constraints.txt /tmp/constraints.txt
# --python: explizit in die Umgebung installieren, mit der ComfyUI startet (/opt/venv).
# Ohne diese Angabe findet uv im Ordner /comfyui eine zweite Umgebung (.venv) und installiert dorthin.
RUN uv pip install --python /opt/venv/bin/python -c /tmp/constraints.txt \
      -r ComfyUI-WanVideoWrapper/requirements.txt \
      -r ComfyUI-WanAnimatePreprocess/requirements.txt \
      -r ComfyUI-KJNodes/requirements.txt \
      -r ComfyUI-VideoHelperSuite/requirements.txt \
      -r ComfyUI-Frame-Interpolation/requirements-no-cupy.txt

# --- Schnellere Attention für Wan (SageAttention, ca. 1,5–2x schneller auf L40S/RTX 6000 Ada/H100) ---
RUN uv pip install --python /opt/venv/bin/python -c /tmp/constraints.txt sageattention==1.0.6

# --- Modellpfade: alles vom Network Volume ---
COPY extra_model_paths.yaml /comfyui/extra_model_paths.yaml
# Ordner, die Nodes selbst befüllen (Pose-Modelle, SAM2, RIFE), auf das Volume umleiten,
# damit sie nicht bei jedem Kaltstart neu geladen werden
RUN rm -rf /comfyui/models/detection /comfyui/models/sam2 /comfyui/custom_nodes/ComfyUI-Frame-Interpolation/ckpts && \
    ln -s /runpod-volume/models/detection /comfyui/models/detection && \
    ln -s /runpod-volume/models/sam2 /comfyui/models/sam2 && \
    ln -s /runpod-volume/cache/vfi_ckpts /comfyui/custom_nodes/ComfyUI-Frame-Interpolation/ckpts

# --- Build-Check: bricht ab, wenn ein Custom Node nicht lädt (statt erst beim ersten Job) ---
RUN cd /comfyui && (timeout 900 python main.py --quick-test-for-ci --cpu > /tmp/ci.log 2>&1 || true) \
    && tail -n 60 /tmp/ci.log \
    && if grep -q "IMPORT FAILED" /tmp/ci.log; then echo "FEHLER: Custom Node konnte nicht geladen werden"; grep -B30 "IMPORT FAILED" /tmp/ci.log | head -120; exit 1; fi \
    && python -c "import transformers, huggingface_hub, diffusers; print('transformers', transformers.__version__, '| hub', huggingface_hub.__version__, '| diffusers', diffusers.__version__)" \
    && /opt/venv/bin/python -c "import sageattention; print('sageattention OK')"

# --- Eigener Handler (Video-Ausgabe + Upload über presigned URLs) ---
COPY handler.py /handler.py

WORKDIR /
