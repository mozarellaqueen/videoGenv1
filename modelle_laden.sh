#!/usr/bin/env bash
# Lädt alle Modelle für Workflow A/B/C auf das RunPod Network Volume.
# Ausführen in einem kurzen Hilfs-Pod, an den das Network Volume angehängt ist
# (Pods sehen das Volume unter /workspace, Serverless-Worker unter /runpod-volume).
#
#   bash modelle_laden.sh            # Standard: /workspace
#   bash modelle_laden.sh /mein/pfad
set -euo pipefail
ROOT="${1:-/workspace}/models"
HF="https://huggingface.co"

dl () {  # Ordner Dateiname URL
  mkdir -p "$ROOT/$1"
  echo ">> $1/$2"
  curl -L -C - --retry 5 --fail -o "$ROOT/$1/$2" "$3"
}

dl diffusion_models Wan2_2-Animate-14B_fp8_scaled_e4m3fn_KJ_v2.safetensors \
   "$HF/Kijai/WanVideo_comfy_fp8_scaled/resolve/main/Wan22Animate/Wan2_2-Animate-14B_fp8_scaled_e4m3fn_KJ_v2.safetensors"
dl text_encoders umt5_xxl_fp8_e4m3fn_scaled.safetensors \
   "$HF/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors"
dl clip_vision clip_vision_h.safetensors \
   "$HF/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/clip_vision/clip_vision_h.safetensors"
dl vae wan_2.1_vae.safetensors \
   "$HF/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/vae/wan_2.1_vae.safetensors"
dl loras lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors \
   "$HF/Kijai/WanVideo_comfy/resolve/main/Lightx2v/lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors"
dl loras WanAnimate_relight_lora_fp16_resized_from_128_to_dynamic_22.safetensors \
   "$HF/Kijai/WanVideo_comfy/resolve/main/LoRAs/Wan22_relight/WanAnimate_relight_lora_fp16_resized_from_128_to_dynamic_22.safetensors"
dl detection vitpose_h_wholebody_model.onnx \
   "$HF/Kijai/vitpose_comfy/resolve/main/onnx/vitpose_h_wholebody_model.onnx"
dl detection vitpose_h_wholebody_data.bin \
   "$HF/Kijai/vitpose_comfy/resolve/main/onnx/vitpose_h_wholebody_data.bin"
dl detection yolov10m.onnx \
   "$HF/Wan-AI/Wan2.2-Animate-14B/resolve/main/process_checkpoint/det/yolov10m.onnx"

mkdir -p "$ROOT/sam2" "$ROOT/../cache/vfi_ckpts"
echo
echo "FERTIG. Inhalt:"
du -sh "$ROOT"/* 2>/dev/null
echo
echo "Wichtig: Die Dateinamen müssen exakt so in deinen Workflows stehen."
echo "Steht im Workflow ein Unterordner (z. B. WanVideo/…), lege die Datei in denselben Unterordner."
