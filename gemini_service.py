#!/usr/bin/env python3
"""
Gemini Service for Calgary Council Stream Recorder.
Uses Google Gemini API to refine speaker diarization with meeting context.
"""

import json
import logging
from typing import Dict, List, Optional
from datetime import datetime
from exceptions import GeminiError

logger = logging.getLogger(__name__)


def refine_diarization(
    merged_transcript: Dict,
    expected_speakers: List[Dict[str, str]],
    meeting_title: str,
    api_key: Optional[str] = None,
    model: str = "gemini-1.5-flash",
    timeout: int = 30
) -> Dict:
    """
    Refine speaker diarization using Gemini AI with meeting context and transcript text.

    Args:
        merged_transcript: Merged transcript JSON with segments containing text and speaker labels
        expected_speakers: List of expected speakers from agenda parser
        meeting_title: Title of the meeting for context
        api_key: Gemini API key (required)
        model: Gemini model to use (default: gemini-1.5-flash)
        timeout: API timeout in seconds (default: 30)

    Returns:
        Refined transcript JSON with real speaker names where confident, or
        original JSON on any failure (graceful degradation)
    """
    # Handle missing API key
    if not api_key:
        logger.error("No API key provided, returning original transcript")
        return merged_transcript

    # Handle empty speakers list (still attempt refinement with context)
    if not expected_speakers:
        logger.warning("No expected speakers provided, will use context only")

    # Get segment count for early size check
    segments = merged_transcript.get('segments', [])
    num_segments = len(segments)
    num_speakers = len(expected_speakers)

    # Skip refinement for very large meetings (>1000 segments) before attempting API call
    if num_segments > 1000:
        logger.info(f"Skipping refinement for meeting with {num_segments} segments (too large)")
        return merged_transcript

    logger.info("========================================")
    logger.info("STARTING SPEAKER REFINEMENT")
    logger.info(f"Model: {model}")
    logger.info(f"Segments: {num_segments}")
    logger.info(f"Expected speakers: {num_speakers}")
    logger.info("========================================")

    # Check prompt size for warning about large meetings
    # Estimate token count (rough: 1 token ≈ 4 characters)
    prompt_estimate = len(json.dumps(merged_transcript)) / 4
    MAX_REASONABLE_TOKENS = 30000  # Leave headroom for Gemini's context limit (usually 32k-128k)

    if prompt_estimate > MAX_REASONABLE_TOKENS:
        logger.warning(f"Transcript is very large (~{int(prompt_estimate)} tokens)")
        logger.warning("Large meetings may hit API limits or incur high costs")
        logger.warning(f"Consider chunking strategy for meetings with >{num_segments} segments")

    import time
    start_time = time.time()

    try:
        # Import google-genai here to avoid import errors if not installed
        from google import genai as client_lib

        # Create client
        client = client_lib.Client(api_key=api_key)

        # Log the speaker list for debugging
        logger.info("Speaker list being used:")
        logger.info("=" * 80)
        formatted_speakers = []
        for speaker in expected_speakers:
            last_name = speaker['name'].split()[-1] if speaker.get('name') else 'Unknown'
            role = speaker.get('role', 'Unknown')
            formatted_speakers.append(f"{role} {last_name}")
        logger.info(', '.join(formatted_speakers))
        logger.info("=" * 80)

        # Construct the prompt
        prompt = _construct_prompt(merged_transcript, expected_speakers, meeting_title)

        # Log the prompt for debugging
        logger.debug("Prompt being sent to API:")
        logger.debug("=" * 80)
        logger.debug(prompt)
        logger.debug("=" * 80)

        # Call the API with config
        # Note: timeout is not supported in config for google-genai SDK
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config={
                'temperature': 0.1  # Low temperature for consistency
            }
        )

        # Extract response text with error handling
        response_text = None
        try:
            # Try accessing .text attribute
            response_text = response.text
        except AttributeError:
            # If .text doesn't exist, try accessing candidates
            logger.warning("response.text not available, checking candidates")
            if hasattr(response, 'candidates') and response.candidates:
                candidate = response.candidates[0]
                if hasattr(candidate, 'content') and candidate.content is not None:
                    if hasattr(candidate.content, 'parts') and candidate.content.parts:
                        response_text = candidate.content.parts[0].text

        if not response_text:
            logger.error("Could not extract text from response")
            logger.error(f"Response type: {type(response)}")
            logger.error(f"Response dir: {dir(response)}")
            raise GeminiError('response parsing', 'Could not extract text from response')

        # Log the raw response for debugging
        logger.debug("Raw response from API:")
        logger.debug("=" * 80)
        logger.debug(response_text[:2000])  # First 2000 chars to avoid too much output
        if len(response_text) > 2000:
            logger.debug(f"... (truncated, total length: {len(response_text)} chars)")
        logger.debug("=" * 80)

        # Extract JSON from response
        refined_json = _extract_json_from_response(response_text)

        if refined_json is None:
            logger.warning("Could not parse valid JSON from response")
            raise GeminiError('response parsing', 'Could not parse valid JSON from response')

        # Add metadata about refinement
        refined_json['refined_by'] = 'gemini'
        refined_json['model'] = model
        refined_json['timestamp'] = datetime.utcnow().isoformat()
        refined_json['original_file'] = merged_transcript.get('file', '')

        # Count how many speakers were refined
        original_labels = _count_unique_speakers(merged_transcript)
        refined_labels = _count_unique_speakers(refined_json)
        generic_count = sum(1 for label in refined_labels if label.startswith('SPEAKER_'))
        refined_count = len(refined_labels) - generic_count

        elapsed_time = time.time() - start_time

        logger.info("========================================")
        logger.info("REFINEMENT COMPLETED")
        logger.info(f"Time taken: {elapsed_time:.1f} seconds")
        logger.info(f"Original speakers: {sorted(original_labels)}")
        logger.info(f"Refined speakers: {sorted(refined_labels)}")
        logger.info(f"Summary: {refined_count} named, {generic_count} still generic")
        logger.info("========================================")

        return refined_json

    except ImportError as e:
        elapsed_time = time.time() - start_time
        logger.error("========================================")
        logger.error("REFINEMENT FAILED - google-genai not installed")
        logger.error(f"Time taken: {elapsed_time:.1f} seconds")
        logger.error("========================================")
        raise GeminiError('initialization', 'google-genai library not installed')
    except GeminiError:
        # Re-raise GeminiError without wrapping
        raise
    except Exception as e:
        elapsed_time = time.time() - start_time
        logger.error("========================================")
        logger.error("REFINEMENT FAILED - API error")
        logger.error(f"Error: {e}", exc_info=True)
        logger.error(f"Time taken: {elapsed_time:.1f} seconds")
        logger.error("========================================")
        raise GeminiError('speaker refinement', str(e))


def _construct_prompt(
    merged_transcript: Dict,
    expected_speakers: List[Dict[str, str]],
    meeting_title: str
) -> str:
    """
    Construct the prompt for Gemini API.
    """
    # Format expected speakers list as "Role LastName"
    if expected_speakers:
        formatted_speakers = []
        for s in expected_speakers:
            last_name = s['name'].split()[-1] if s.get('name') else 'Unknown'
            role = s.get('role', 'Unknown')
            formatted_speakers.append(f"{role} {last_name}")
        speaker_list = "  - " + "\n  - ".join(formatted_speakers)
    else:
        speaker_list = "  - No speaker list available (use meeting context only)"

    # Format merged transcript compactly
    transcript_str = json.dumps(merged_transcript, indent=2)

    prompt = f"""You are refining speaker identification in a transcript from a Calgary City Council meeting.

Meeting: {meeting_title}

Expected Speakers (may be incomplete, especially for public hearings):
{speaker_list}

Current Transcript (with generic speaker labels and text):
{transcript_str}

Task: Map generic speaker labels (SPEAKER_00, SPEAKER_01, etc.) to real names where you can identify them.

KEY CONTEXT CLUES TO USE (with examples):

1. **Roll Call Pattern** - THE MOST IMPORTANT CLUE:
   - When SPEAKER_A says "Councillor Kelly" and SPEAKER_B responds "Present" or "Here", then SPEAKER_B = "Councillor Kelly"
   - Example sequence:
     * SPEAKER_00: "Councillor Kelly." → SPEAKER_00 is calling roll (likely Chair)
     * SPEAKER_02: "Present." → SPEAKER_02 = "Councillor Kelly"
   - Apply this pattern throughout: person being called = person who responds

2. **Direct Self-Introduction**:
   - "I'm Councillor Smith" → that speaker is Councillor Smith
   - "This is Mayor Jones speaking" → that speaker is Mayor Jones

3. **Being Addressed by Others**:
   - "Thank you, Councillor Smith" → previous speaker was Councillor Smith
   - "Councillor Jones, you have the floor" → next speaker will be Councillor Jones

4. **Role Transitions**:
   - "Councillor Pawn is elected Chair" → when they start chairing, update their label
   - The person conducting business after election = the elected person

5. **Text Content Clues**:
   - Names in the text often indicate who the speaker is (e.g., "Chief Administrative Officer Designat-Moller" suggests the speaker is introducing CAO Moller OR is CAO Moller)

6. **Name Matching with Expected Speakers**:
   - Whisper may transcribe difficult names incorrectly (e.g., "Pantazopolous" → "Pawn Stoppeless")
   - When you identify a speaker, check if any expected speaker has a similar-sounding name
   - Example: Transcript says "Pawn" or "Pawn Stoppeless", expected list has "Councillor Pantazopolous" → Use "Councillor Pantazopolous"
   - Always prefer the correct spelling from the expected speakers list

CRITICAL RULE - SPEAKER LABEL UNCERTAINTY:
- WARNING: SPEAKER_XX labels from diarization may NOT be consistent throughout the transcript
- The diarization system may assign the same label (e.g., SPEAKER_00) to different people at different points
- Identify each speaker segment INDEPENDENTLY based on its local context clues
- Do NOT assume SPEAKER_XX means the same person throughout - verify with context each time

CRITICAL RULE - ONLY ASSIGN NAMES WITH STRONG EVIDENCE:
- **IMPORTANT**: The expected speakers list may be INCOMPLETE or INCORRECT for this specific meeting
- **DO NOT** assign a name from the expected speakers list unless you have STRONG EVIDENCE from the transcript
- **Strong evidence includes**: Roll call responses, direct self-introductions, or being explicitly addressed by name
- **Weak evidence is NOT enough**: Do NOT assign names based only on role assumptions (e.g., assuming the chair is a specific person)
- **When in doubt, keep SPEAKER_XX**: It is better to leave a speaker as generic than to assign the wrong name
- **Example of INCORRECT inference**: "The chair is speaking, and Mayor X is on the expected list, so the chair must be Mayor X" → WRONG! Only assign if there's explicit evidence.

Speaker Name Formatting and Matching:
- Format: "Title LastName" (e.g., "Councillor Atkinson", "Mayor Gondek")
- Common titles: Mayor, Councillor, CAO, Deputy Mayor
- **Match names to expected speakers list**: The expected speakers list shows full names with roles
- **Use the EXACT spelling from expected speakers list**: If you identify someone as matching an expected speaker, use the title + last name from that speaker's entry
  - Example: Expected list has "Jasmine Mian" with role "Councillor" → Use "Councillor Mian"
  - Example: Expected list has "Gian-Carlo Carra" with role "Councillor" → Use "Councillor Carra"
- **Handle transcription errors**: Whisper may mangle difficult names - match phonetically similar names from expected list
  - Example: Transcript says "Pawn Stoppeless" but expected list has "Sonya Pantazopolous" → Use "Councillor Pantazopolous"
- **When uncertain, prefer names from expected speakers list** over transcript variations
- If expected speakers list is empty, use names exactly as they appear in transcript

Instructions:
1. **BE CONSERVATIVE**: Only assign names when you have STRONG evidence from the transcript text
2. **Use context clues**: Roll call, self-introductions, and being addressed by name are the best evidence
3. **Preserve structure**: Keep timestamps, text, JSON structure EXACTLY as provided
4. **Keep generic when uncertain**: If you don't have strong evidence, keep "SPEAKER_XX"
5. **Return ONLY JSON**: No markdown blocks, no explanation, just the JSON

Output the refined transcript JSON with identical structure:"""

    return prompt


def _extract_json_from_response(response_text: str) -> Optional[Dict]:
    """
    Extract and validate JSON from Gemini response.

    Gemini sometimes wraps JSON in markdown code blocks, so we need to handle that.
    """
    from typing import cast
    try:
        # Try parsing directly first
        return cast(Dict, json.loads(response_text))
    except json.JSONDecodeError:
        # Try extracting from markdown code block
        import re

        # Pattern: ```json ... ``` or ``` ... ```
        json_pattern = re.compile(r'```(?:json)?\s*(\{.*?\})\s*```', re.DOTALL)
        match = json_pattern.search(response_text)

        if match:
            try:
                return cast(Dict, json.loads(match.group(1)))
            except json.JSONDecodeError:
                pass

        # Try finding any JSON object in the text
        json_pattern = re.compile(r'\{.*\}', re.DOTALL)
        match = json_pattern.search(response_text)

        if match:
            try:
                return cast(Dict, json.loads(match.group(0)))
            except json.JSONDecodeError:
                pass

        return None


def _count_unique_speakers(transcript_json: Dict) -> List[str]:
    """
    Count unique speaker labels in transcript JSON.
    """
    segments = transcript_json.get('segments', [])
    speakers = set(seg.get('speaker', 'UNKNOWN') for seg in segments)
    return list(speakers)
