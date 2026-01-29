#!/usr/bin/env python3
"""
Gemini Service for Calgary Council Stream Recorder.
Uses Google Gemini API to refine speaker diarization with meeting context.
"""

import json
from typing import Dict, List, Optional
from datetime import datetime


def refine_diarization(
    pyannote_json: Dict,
    expected_speakers: List[Dict[str, str]],
    meeting_title: str,
    api_key: Optional[str] = None,
    model: str = "gemini-1.5-flash",
    timeout: int = 30
) -> Dict:
    """
    Refine speaker diarization using Gemini AI with meeting context.

    Args:
        pyannote_json: Original diarization JSON from pyannote with generic speaker labels
        expected_speakers: List of expected speakers from agenda parser
        meeting_title: Title of the meeting for context
        api_key: Gemini API key (required)
        model: Gemini model to use (default: gemini-1.5-flash)
        timeout: API timeout in seconds (default: 30)

    Returns:
        Refined diarization JSON with real speaker names where confident, or
        original JSON on any failure (graceful degradation)
    """
    # Handle missing API key
    if not api_key:
        print("[GEMINI] ERROR: No API key provided, returning original diarization")
        return pyannote_json

    # Handle empty speakers list (still attempt refinement with context)
    if not expected_speakers:
        print("[GEMINI] WARNING: No expected speakers provided, will use context only")

    # Get segment count for early size check
    segments = pyannote_json.get('segments', pyannote_json.get('diarization', []))
    num_segments = len(segments)
    num_speakers = len(expected_speakers)

    # Skip refinement for very large meetings (>1000 segments) before attempting API call
    if num_segments > 1000:
        print(f"[GEMINI] Skipping refinement for meeting with {num_segments} segments (too large)")
        return pyannote_json

    print(f"[GEMINI] Sending diarization to Gemini (model: {model})")
    print(f"[GEMINI] Processing {num_segments} diarization segments with {num_speakers} expected speakers")

    # Check prompt size for warning about large meetings
    # Estimate token count (rough: 1 token ≈ 4 characters)
    prompt_estimate = len(json.dumps(pyannote_json)) / 4
    MAX_REASONABLE_TOKENS = 30000  # Leave headroom for Gemini's context limit (usually 32k-128k)

    if prompt_estimate > MAX_REASONABLE_TOKENS:
        print(f"[GEMINI] WARNING: Diarization is very large (~{int(prompt_estimate)} tokens)")
        print(f"[GEMINI] Large meetings may hit API limits or incur high costs")
        print(f"[GEMINI] Consider chunking strategy for meetings with >{num_segments} segments")

    try:
        # Import google-generativeai here to avoid import errors if not installed
        import google.generativeai as genai

        # Configure API
        genai.configure(api_key=api_key)

        # Create the model
        model_instance = genai.GenerativeModel(model)

        # Construct the prompt
        prompt = _construct_prompt(pyannote_json, expected_speakers, meeting_title)

        # Log the prompt for debugging
        print(f"[GEMINI] Prompt being sent to API:")
        print("=" * 80)
        print(prompt)
        print("=" * 80)

        # Call the API with timeout
        # Note: google-generativeai doesn't support direct timeout parameter in generate_content
        # We use request_options to set timeout at the HTTP level
        import google.generativeai.types as genai_types

        request_options = genai_types.RequestOptions(timeout=timeout)
        response = model_instance.generate_content(
            prompt,
            generation_config={'temperature': 0.1},  # Low temperature for consistency
            request_options=request_options
        )

        # Log the raw response for debugging
        print(f"[GEMINI] Raw response from API:")
        print("=" * 80)
        print(response.text[:2000])  # First 2000 chars to avoid too much output
        if len(response.text) > 2000:
            print(f"... (truncated, total length: {len(response.text)} chars)")
        print("=" * 80)

        # Extract JSON from response
        refined_json = _extract_json_from_response(response.text)

        if refined_json is None:
            print("[GEMINI] WARNING: Could not parse valid JSON from response, using original")
            return pyannote_json

        # Add metadata about refinement
        refined_json['refined_by'] = 'gemini'
        refined_json['model'] = model
        refined_json['timestamp'] = datetime.utcnow().isoformat()
        refined_json['original_file'] = pyannote_json.get('file', '')

        # Count how many speakers were refined
        original_labels = _count_unique_speakers(pyannote_json)
        refined_labels = _count_unique_speakers(refined_json)
        generic_count = sum(1 for label in refined_labels if label.startswith('SPEAKER_'))
        refined_count = len(refined_labels) - generic_count

        print(f"[GEMINI] Original: {len(original_labels)} speakers, Refined: {refined_count} named, {generic_count} generic")

        return refined_json

    except ImportError:
        print("[GEMINI] ERROR: google-generativeai not installed, returning original diarization")
        return pyannote_json
    except Exception as e:
        print(f"[GEMINI] ERROR: API call failed: {e}")
        return pyannote_json


def _construct_prompt(
    pyannote_json: Dict,
    expected_speakers: List[Dict[str, str]],
    meeting_title: str
) -> str:
    """
    Construct the prompt for Gemini API.
    """
    # Format expected speakers list
    if expected_speakers:
        speaker_list = "\n".join([
            f"  - {s['name']} ({s['role']}, confidence: {s['confidence']})"
            for s in expected_speakers
        ])
    else:
        speaker_list = "  - No speaker list available (use meeting context only)"

    # Format pyannote JSON compactly
    pyannote_str = json.dumps(pyannote_json, indent=2)

    prompt = f"""You are refining speaker diarization output from a Calgary City Council meeting.

Meeting: {meeting_title}

Expected Speakers (may be incomplete, especially for public hearings):
{speaker_list}

Original Diarization (with generic labels):
{pyannote_str}

Task: Map generic speaker labels (SPEAKER_00, SPEAKER_01, etc.) to real names where you have HIGH confidence (>80%) based on:
- Speaking patterns and context from the transcription text
- Expected speaker roles and likely speaking order
- Meeting flow and structure
- Content of what each speaker says

Critical Rules:
1. Preserve ALL timestamps EXACTLY as they are
2. Preserve the EXACT JSON structure (same keys, same nesting)
3. ONLY replace speaker labels where confidence is HIGH (>80%)
4. Keep "SPEAKER_XX" labels for uncertain mappings - this is IMPORTANT
5. Public hearings have many unlisted speakers - keep them as generic labels
6. If a speaker is clearly not in the expected list, keep it generic
7. Return ONLY valid JSON, no explanation or commentary

Output the refined diarization JSON with the same structure:"""

    return prompt


def _extract_json_from_response(response_text: str) -> Optional[Dict]:
    """
    Extract and validate JSON from Gemini response.

    Gemini sometimes wraps JSON in markdown code blocks, so we need to handle that.
    """
    try:
        # Try parsing directly first
        return json.loads(response_text)
    except json.JSONDecodeError:
        # Try extracting from markdown code block
        import re

        # Pattern: ```json ... ``` or ``` ... ```
        json_pattern = re.compile(r'```(?:json)?\s*(\{.*?\})\s*```', re.DOTALL)
        match = json_pattern.search(response_text)

        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # Try finding any JSON object in the text
        json_pattern = re.compile(r'\{.*\}', re.DOTALL)
        match = json_pattern.search(response_text)

        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        return None


def _count_unique_speakers(diarization_json: Dict) -> List[str]:
    """
    Count unique speaker labels in diarization JSON.
    """
    segments = diarization_json.get('segments', diarization_json.get('diarization', []))
    speakers = set(seg.get('speaker', 'UNKNOWN') for seg in segments)
    return list(speakers)
