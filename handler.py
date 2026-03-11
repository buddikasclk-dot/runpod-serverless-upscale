import os
import time
import base64
import requests


COMFY_API_URL = os.getenv("COMFY_API_URL")
WORKFLOW_2X = os.getenv("WORKFLOW_2X", "upscale_2x.json")
WORKFLOW_4X = os.getenv("WORKFLOW_4X", "upscale_4x.json")
WORKFLOW_8X = os.getenv("WORKFLOW_8X", "upscale_8x.json")


def load_workflow(scale: str):
    if scale == "2x":
        path = WORKFLOW_2X
    elif scale == "8x":
        path = WORKFLOW_8X
    else:
        path = WORKFLOW_4X

    if not os.path.exists(path):
        raise FileNotFoundError(f"Workflow file not found: {path}")

    import json
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def queue_prompt(prompt):
    url = f"{COMFY_API_URL}/prompt"
    response = requests.post(url, json={"prompt": prompt}, timeout=60)
    response.raise_for_status()
    return response.json()


def get_history(prompt_id):
    url = f"{COMFY_API_URL}/history/{prompt_id}"
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    return response.json()


def get_image(filename, subfolder="", folder_type="output"):
    url = f"{COMFY_API_URL}/view"
    params = {
        "filename": filename,
        "subfolder": subfolder,
        "type": folder_type
    }
    response = requests.get(url, params=params, timeout=120)
    response.raise_for_status()
    return response.content


def update_workflow_image(workflow, image_b64):
    for node_id, node in workflow.items():
        inputs = node.get("inputs", {})

        if "image" in inputs and isinstance(inputs["image"], str):
            if inputs["image"] in ["INPUT_IMAGE", "input.png", "image.png"]:
                inputs["image"] = image_b64

        if "base64_image" in inputs:
            inputs["base64_image"] = image_b64

    return workflow


def find_output_images(history_data, prompt_id):
    outputs = history_data.get(prompt_id, {}).get("outputs", {})
    found_images = []

    for node_id, node_output in outputs.items():
        images = node_output.get("images", [])
        for image in images:
            found_images.append(image)

    return found_images


def handler(event):
    try:
        if not COMFY_API_URL:
            return {
                "success": False,
                "error": "Missing COMFY_API_URL environment variable"
            }

        input_data = event.get("input", {})
        image_base64 = input_data.get("image_base64")
        scale = str(input_data.get("scale", "4x")).lower()

        if not image_base64:
            return {
                "success": False,
                "error": "Missing image_base64 in input"
            }

        workflow = load_workflow(scale)
        workflow = update_workflow_image(workflow, image_base64)

        queued = queue_prompt(workflow)
        prompt_id = queued.get("prompt_id")

        if not prompt_id:
            return {
                "success": False,
                "error": "No prompt_id returned from ComfyUI"
            }

        max_wait = 300
        start_time = time.time()

        while time.time() - start_time < max_wait:
            history = get_history(prompt_id)
            outputs = find_output_images(history, prompt_id)

            if outputs:
                first_image = outputs[0]
                image_bytes = get_image(
                    filename=first_image["filename"],
                    subfolder=first_image.get("subfolder", ""),
                    folder_type=first_image.get("type", "output")
                )

                result_b64 = base64.b64encode(image_bytes).decode("utf-8")

                return {
                    "success": True,
                    "scale": scale,
                    "image_base64": result_b64,
                    "prompt_id": prompt_id
                }

            time.sleep(2)

        return {
            "success": False,
            "error": "Timed out waiting for ComfyUI output",
            "prompt_id": prompt_id
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


if __name__ == "__main__":
    import runpod
    runpod.serverless.start({"handler": handler})