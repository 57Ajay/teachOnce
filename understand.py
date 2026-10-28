"""Muse Spark watches the teach video with the event log and narration and returns a step graph."""
import json

import meta_client
import prompts

_STEP = {
    "type": "object",
    "additionalProperties": False,
    "required": ["event_idx", "intent", "is_variable", "variable_name", "variable_reason", "visual_success_signal",
                 "target_visual_description", "target_noun_phrase", "confidence"],
    "properties": {
        "event_idx": {"type": "integer"},
        "intent": {"type": "string"},
        "is_variable": {"type": "boolean"},
        "variable_name": {"type": "string"},
        "variable_reason": {"type": "string"},
        "visual_success_signal": {"type": "string"},
        "target_visual_description": {"type": "string"},
        "target_noun_phrase": {"type": "string"},
        "confidence": {"type": "number"},
    },
}
_OUTPUT = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "page", "where", "example"],
    "properties": {"name": {"type": "string"}, "page": {"type": "string"}, "where": {"type": "string"},
                   "example": {"type": "string"}},
}
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["task_name", "task_summary", "steps", "outputs"],
    "properties": {
        "task_name": {"type": "string"},
        "task_summary": {"type": "string"},
        "steps": {"type": "array", "items": _STEP},
        "outputs": {"type": "array", "items": _OUTPUT},
    },
}


def understand(video_path, event_table: str, turns: list[dict]) -> dict:
    narration = "\n".join(f"[{t['startMs'] / 1000:.1f}s-{t['endMs'] / 1000:.1f}s] {t['transcript']}" for t in turns)
    file_id = meta_client.upload_file(video_path)
    content = [
        {"type": "input_video", "file_id": file_id},
        {"type": "input_text", "text": f"EVENT LOG:\n{event_table}\n\nNARRATION:\n{narration or '(no narration recorded)'}"},
    ]
    return meta_client.structured(
        meta_client.SPARK,
        [{"role": "user", "content": content}],
        SCHEMA,
        "step_graph",
        effort="high",
        max_output_tokens=16000,
        instructions=prompts.UNDERSTAND,
        metadata={"prompt": prompts.UNDERSTAND_VERSION},
        purpose="teach",
        timeout=300,
    )


if __name__ == "__main__":
    import sys

    import recording
    import teach

    rec = recording.load(sys.argv[1])
    events = teach.final_pass(rec["events"])
    print(json.dumps(understand(rec["dir"] / "teach.mp4", teach.event_table(events), teach.transcribe(rec)), indent=2))
