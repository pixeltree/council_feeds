#!/usr/bin/env python3
"""
Gemini Service for Calgary Council Stream Recorder.
Uses Google Gemini API to refine speaker diarization with meeting context.
"""

import json
import logging
import asyncio
from typing import Dict, List, Optional
from datetime import datetime
from exceptions import GeminiError

logger = logging.getLogger(__name__)

# Constants for chunking and validation
NATURAL_PAUSE_THRESHOLD_SECONDS = 1.5  # Minimum pause duration to split chunks
TIMESTAMP_TOLERANCE_SECONDS = 0.5  # Tolerance for timestamp validation
MAX_GAP_SECONDS = 5.0  # Maximum allowed gap between segments


async def _refine_with_chunking(
    merged_transcript: Dict,
    expected_speakers: List[Dict[str, str]],
    meeting_title: str,
    api_key: str,
    model: str,
    chunk_size: int
) -> Dict:
    """
    Refine large transcripts using chunking strategy.
    Splits into smaller chunks to avoid Gemini response truncation.
    Each chunk is saved to a debug folder for inspection and retry.

    Note: Debug files are saved to {video_file}.gemini_debug/ directory.
    These files are useful for debugging but may accumulate over time.
    Consider cleaning up old debug folders periodically if disk space is a concern.
    """
    segments = merged_transcript.get('segments', [])
    total_segments = len(segments)
    video_file = merged_transcript.get('file', 'unknown')

    # Create debug folder
    import os
    debug_folder = video_file + '.gemini_debug'
    os.makedirs(debug_folder, exist_ok=True)
    logger.info(f"Debug folder: {debug_folder}")

    logger.info("=" * 80)
    logger.info(f"CHUNKING STRATEGY: Processing {total_segments} segments in chunks of {chunk_size}")
    logger.info("=" * 80)

    # Split segments into chunks at natural boundaries
    chunks = []
    current_chunk = []

    for i, segment in enumerate(segments):
        current_chunk.append(segment)

        # Check if we should split chunk
        if len(current_chunk) >= chunk_size:
            # Look for natural break point (pause > NATURAL_PAUSE_THRESHOLD_SECONDS)
            if i < len(segments) - 1:
                pause = segments[i + 1]['start'] - segment['end']
                if pause > NATURAL_PAUSE_THRESHOLD_SECONDS:
                    chunks.append(current_chunk)
                    current_chunk = []
            else:
                # Last segment
                chunks.append(current_chunk)
                current_chunk = []

    # Add remaining segments
    if current_chunk:
        chunks.append(current_chunk)

    logger.info(f"Split into {len(chunks)} chunks")

    # Process chunks sequentially (to maintain context and speaker mappings)
    refined_segments = []
    speaker_mappings = {}  # Track discovered speaker mappings across chunks

    for chunk_idx, chunk in enumerate(chunks):
        chunk_num = chunk_idx + 1
        logger.info("-" * 80)
        logger.info(f"Processing chunk {chunk_num}/{len(chunks)} ({len(chunk)} segments)")
        logger.info(f"Time range: {chunk[0]['start']:.1f}s - {chunk[-1]['end']:.1f}s")

        # Save chunk input (clean segments-only JSON)
        chunk_input_path = os.path.join(debug_folder, f'chunk_{chunk_num:03d}_input.json')
        chunk_segments_only = {'segments': chunk}
        with open(chunk_input_path, 'w', encoding='utf-8') as f:
            json.dump(chunk_segments_only, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved chunk input: {chunk_input_path}")

        # Refine this chunk
        try:
            # Create async client for this chunk
            from google import genai as client_lib
            client = client_lib.Client(api_key=api_key)

            # Construct prompt with known mappings from previous chunks
            prompt = _construct_prompt_for_chunk(
                chunk_segments_only,
                expected_speakers,
                meeting_title,
                known_mappings=speaker_mappings if speaker_mappings else None
            )

            # Save prompt to debug file
            prompt_path = os.path.join(debug_folder, f'chunk_{chunk_num:03d}_prompt.txt')
            with open(prompt_path, 'w', encoding='utf-8') as f:
                f.write(prompt)

            # Call API
            async with client.aio as async_client:
                response = await async_client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config={'temperature': 0.1}
                )

            # Extract response
            response_text = response.text if hasattr(response, 'text') else None

            # Save raw response to debug file
            response_path = os.path.join(debug_folder, f'chunk_{chunk_num:03d}_response.txt')
            with open(response_path, 'w', encoding='utf-8') as f:
                f.write(response_text if response_text else "NO RESPONSE TEXT")
            logger.info(f"Saved chunk response: {response_path}")

            if not response_text:
                logger.warning(f"Chunk {chunk_num}: No response text, using original")
                refined_segments.extend(chunk)
                continue

            # Parse JSON
            refined_json = _extract_json_from_response(response_text)

            # Save parsed JSON to debug file
            parsed_path = os.path.join(debug_folder, f'chunk_{chunk_num:03d}_parsed.json')
            if refined_json:
                with open(parsed_path, 'w', encoding='utf-8') as f:
                    json.dump(refined_json, f, indent=2, ensure_ascii=False)
                logger.info(f"Saved parsed JSON: {parsed_path}")
            else:
                with open(parsed_path, 'w', encoding='utf-8') as f:
                    f.write("PARSE FAILED")

            if refined_json and refined_json.get('segments'):
                refined_chunk_segments = refined_json['segments']

                # Extract speaker mappings from Gemini's response
                new_mappings = refined_json.get('speaker_mappings', {})
                if new_mappings:
                    speaker_mappings.update(new_mappings)
                    logger.info(f"Chunk {chunk_num}: Added {len(new_mappings)} new speaker mappings from Gemini. Total: {len(speaker_mappings)}")

                # Validate chunk has same number of segments
                if len(refined_chunk_segments) != len(chunk):
                    logger.warning(
                        f"Chunk {chunk_num}: Segment count mismatch! "
                        f"Expected {len(chunk)}, got {len(refined_chunk_segments)}. Using original."
                    )
                    refined_segments.extend(chunk)
                    continue

                # Validate timestamps match (within tolerance)
                timestamps_match = all(
                    abs(refined_chunk_segments[i]['start'] - chunk[i]['start']) < TIMESTAMP_TOLERANCE_SECONDS
                    for i in range(len(chunk))
                )

                if not timestamps_match:
                    logger.warning(f"Chunk {chunk_num}: Timestamp mismatch detected. Using original.")
                    refined_segments.extend(chunk)
                    continue

                # Update speaker mappings from segments (in addition to explicit mappings from Gemini)
                for i, seg in enumerate(refined_chunk_segments):
                    speaker = seg.get('speaker', '')
                    original_speaker = chunk[i]['speaker']

                    if speaker and not speaker.startswith('SPEAKER_'):
                        # Track mapping from generic to real name
                        if original_speaker.startswith('SPEAKER_'):
                            speaker_mappings[original_speaker] = speaker

                # Validation passed - use refined segments
                refined_segments.extend(refined_chunk_segments)
                logger.info(f"Chunk {chunk_num}: ✓ Refined successfully. Total speaker mappings: {len(speaker_mappings)}")
            else:
                logger.warning(f"Chunk {chunk_num}: Could not parse JSON, using original")
                refined_segments.extend(chunk)

        except Exception as e:
            logger.error(f"Chunk {chunk_num} failed: {e}")
            refined_segments.extend(chunk)  # Use original on failure

    # Validate final result integrity
    logger.info("-" * 80)
    logger.info("VALIDATING MERGED RESULT")

    if len(refined_segments) != total_segments:
        logger.error(
            f"MERGE ERROR: Segment count mismatch! "
            f"Expected {total_segments}, got {len(refined_segments)}"
        )
        # Return original if merge failed
        return merged_transcript

    # Check for timestamp gaps or overlaps
    for i in range(len(refined_segments) - 1):
        current_end = refined_segments[i]['end']
        next_start = refined_segments[i + 1]['start']

        if next_start < current_end - TIMESTAMP_TOLERANCE_SECONDS:  # Overlap
            logger.warning(f"Overlap detected at segment {i}: {current_end}s -> {next_start}s")
        elif next_start > current_end + MAX_GAP_SECONDS:  # Large gap
            logger.warning(f"Large gap detected at segment {i}: {current_end}s -> {next_start}s")

    # Count refined vs generic speakers
    all_speakers = set(seg['speaker'] for seg in refined_segments)
    generic_count = sum(1 for s in all_speakers if s.startswith('SPEAKER_'))
    refined_count = len(all_speakers) - generic_count

    logger.info(f"✓ Segment count: {len(refined_segments)}/{total_segments}")
    logger.info(f"✓ Speakers: {refined_count} named, {generic_count} generic")
    logger.info(f"✓ Unique speaker mappings discovered: {len(speaker_mappings)}")

    # Build final result
    result = {
        'file': merged_transcript.get('file', ''),
        'language': merged_transcript.get('language', 'en'),
        'segments': refined_segments,
        'full_text': ' '.join(seg.get('text', '') for seg in refined_segments),
        'num_speakers': len(all_speakers),
        'refined_by': 'gemini',
        'model': model,
        'timestamp': datetime.utcnow().isoformat(),
        'original_file': merged_transcript.get('file', ''),
        'chunking_strategy': {
            'total_segments': total_segments,
            'num_chunks': len(chunks),
            'chunk_size': chunk_size,
            'speaker_mappings_found': len(speaker_mappings),
            'refined_speakers': refined_count,
            'generic_speakers': generic_count
        }
    }

    logger.info("=" * 80)
    logger.info(f"CHUNKING COMPLETE: Successfully merged all {len(chunks)} chunks")
    logger.info("=" * 80)

    return result


async def refine_diarization_async(
    merged_transcript: Dict,
    expected_speakers: List[Dict[str, str]],
    meeting_title: str,
    api_key: Optional[str] = None,
    model: str = "gemini-1.5-flash",
    timeout: int = 30
) -> Dict:
    """
    Async version: Refine speaker diarization using Gemini AI.
    Non-blocking, suitable for use in async contexts like web servers.

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

    # Use chunking strategy for large meetings to avoid hitting response limits
    # Gemini can handle large inputs but struggles to return large JSON outputs
    MAX_SEGMENTS_PER_CHUNK = 250  # Balance between context and output size

    if num_segments > MAX_SEGMENTS_PER_CHUNK:
        logger.info(f"Large meeting detected ({num_segments} segments). Using chunking strategy.")
        return await _refine_with_chunking(
            merged_transcript,
            expected_speakers,
            meeting_title,
            api_key,
            model,
            MAX_SEGMENTS_PER_CHUNK
        )

    logger.info("========================================")
    logger.info("STARTING SPEAKER REFINEMENT (ASYNC)")
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

        # Call the API asynchronously using async context manager
        logger.info("Making async Gemini API call...")
        async with client.aio as async_client:
            response = await async_client.models.generate_content(
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

        # Save full response to file for debugging
        video_file = merged_transcript.get('file', 'unknown')
        response_debug_path = video_file + '.gemini_response_debug.txt'
        try:
            with open(response_debug_path, 'w', encoding='utf-8') as f:
                f.write("=" * 80 + "\n")
                f.write("GEMINI API RESPONSE DEBUG\n")
                f.write(f"Timestamp: {datetime.utcnow().isoformat()}\n")
                f.write(f"Model: {model}\n")
                f.write(f"Response length: {len(response_text)} characters\n")
                f.write("=" * 80 + "\n\n")
                f.write(response_text)
                f.write("\n\n" + "=" * 80 + "\n")
                f.write("END OF RESPONSE\n")
                f.write("=" * 80 + "\n")
            logger.info(f"Saved full Gemini response to: {response_debug_path}")
        except Exception as e:
            logger.warning(f"Could not save debug response file: {e}")

        # Extract JSON from response
        refined_json = _extract_json_from_response(response_text)

        if refined_json is None:
            logger.error("Could not parse valid JSON from response")
            logger.error(f"Response preview (first 500 chars): {response_text[:500]}")
            logger.error(f"Response preview (last 500 chars): {response_text[-500:]}")
            logger.error(f"Full response saved to: {response_debug_path}")
            raise GeminiError(
                'response parsing',
                f'Could not parse valid JSON from response. Full response saved to {response_debug_path}'
            )

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


def refine_diarization(
    merged_transcript: Dict,
    expected_speakers: List[Dict[str, str]],
    meeting_title: str,
    api_key: Optional[str] = None,
    model: str = "gemini-1.5-flash",
    timeout: int = 30
) -> Dict:
    """
    Synchronous wrapper for refine_diarization_async.
    For backward compatibility with synchronous code.

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
    # Run the async version in a new event loop
    return asyncio.run(refine_diarization_async(
        merged_transcript,
        expected_speakers,
        meeting_title,
        api_key,
        model,
        timeout
    ))


def _construct_prompt_for_chunk(
    chunk_data: Dict,
    expected_speakers: List[Dict[str, str]],
    meeting_title: str,
    known_mappings: Dict[str, str] = None
) -> str:
    """
    Construct an optimized prompt for a chunk (segments-only JSON).
    This version expects chunk_data = {'segments': [...]}
    """
    # Format expected speakers list as "Role LastName"
    if expected_speakers:
        formatted_speakers = []
        for s in expected_speakers:
            last_name = s['name'].split()[-1] if s.get('name') else 'Unknown'
            role = s.get('role', 'Unknown')
            formatted_speakers.append(f"{role} {last_name}")
        speaker_list = ", ".join(formatted_speakers)
    else:
        speaker_list = "None provided"

    # Format known mappings from previous chunks
    mappings_context = ""
    if known_mappings:
        mapping_lines = [f'  "{k}": "{v}"' for k, v in sorted(known_mappings.items())]
        mappings_context = f"""

SUGGESTED speaker mappings from previous chunks (use as hints only, not authoritative):
{{
{chr(10).join(mapping_lines)}
}}

IMPORTANT: These mappings are suggestions only. The diarization system may have incorrectly separated or merged speakers, so SPEAKER_XX labels may not consistently represent the same person. Always verify each segment independently using context clues.
"""

    # Format chunk as compact JSON (segments only)
    chunk_str = json.dumps(chunk_data, separators=(',', ':'))

    prompt = f"""Map SPEAKER_XX labels to real names in this Calgary City Council meeting transcript chunk.

Meeting: {meeting_title}
Expected: {speaker_list}{mappings_context}

Transcript chunk (segments only):
{chunk_str}

Context Clues (priority order):
1. Roll call: "Councillor X" → response "Present/Here" = Councillor X
2. Self-intro: "I'm [Name]" = that speaker
3. Addressed: "Thank you, [Name]" = previous speaker is Name
4. Match phonetically to expected list (e.g., "Pawn" → Pantazopolous)

Rules:
- ONLY assign names with STRONG evidence (roll call, self-intro, direct address)
- Format: "Title LastName" (Mayor Gondek, Councillor Smith)
- Use EXACT spelling from expected list
- When uncertain, keep SPEAKER_XX
- WARNING: SPEAKER_XX labels are unreliable - the same person may have different SPEAKER_XX labels, and different people may share the same SPEAKER_XX label
- Verify EVERY segment independently based on context clues, not just the SPEAKER_XX label
- Preserve ALL timestamps, text, structure exactly

Return JSON with this structure:
{{
  "segments": [...refined segments...],
  "speaker_mappings": {{
    "SPEAKER_00": "Mayor Gondek",
    "SPEAKER_01": "Councillor Smith"
  }}
}}

The speaker_mappings should include ALL confident mappings you discovered in this chunk (for use in future chunks).
Return ONLY the JSON (no markdown, no explanation):"""

    return prompt


def _construct_prompt(
    merged_transcript: Dict,
    expected_speakers: List[Dict[str, str]],
    meeting_title: str
) -> str:
    """
    Construct an optimized, concise prompt for Gemini API.
    Reduced from ~2000 chars to ~600 chars for faster processing.
    """
    # Format expected speakers list as "Role LastName"
    if expected_speakers:
        formatted_speakers = []
        for s in expected_speakers:
            last_name = s['name'].split()[-1] if s.get('name') else 'Unknown'
            role = s.get('role', 'Unknown')
            formatted_speakers.append(f"{role} {last_name}")
        speaker_list = ", ".join(formatted_speakers)
    else:
        speaker_list = "None provided"

    # Format merged transcript compactly (no indentation to save tokens)
    transcript_str = json.dumps(merged_transcript, separators=(',', ':'))

    prompt = f"""Map SPEAKER_XX labels to real names in this Calgary City Council meeting transcript.

Meeting: {meeting_title}
Expected: {speaker_list}

Transcript:
{transcript_str}

Context Clues (priority order):
1. Roll call: "Councillor X" → response "Present/Here" = Councillor X
2. Self-intro: "I'm [Name]" = that speaker
3. Addressed: "Thank you, [Name]" = previous speaker is Name
4. Match phonetically to expected list (e.g., "Pawn" → Pantazopolous)

Rules:
- ONLY assign names with STRONG evidence (roll call, self-intro, direct address)
- Format: "Title LastName" (Mayor Gondek, Councillor Smith)
- Use EXACT spelling from expected list
- When uncertain, keep SPEAKER_XX
- WARNING: SPEAKER_XX labels are unreliable - the same person may have different SPEAKER_XX labels, and different people may share the same SPEAKER_XX label
- Verify EVERY segment independently based on context clues, not just the SPEAKER_XX label
- Preserve ALL timestamps, text, structure exactly

Return ONLY the JSON (no markdown, no explanation):"""

    return prompt


def _extract_json_from_response(response_text: str) -> Optional[Dict]:
    """
    Extract and validate JSON from Gemini response.

    Gemini sometimes wraps JSON in markdown code blocks, so we need to handle that.
    """
    from typing import cast
    import re

    # Strategy 1: Try parsing directly first
    try:
        parsed = json.loads(response_text)
        logger.debug("Successfully parsed JSON directly (no markdown wrapper)")
        return cast(Dict, parsed)
    except json.JSONDecodeError as e:
        logger.debug(f"Direct JSON parse failed: {e}")

    # Strategy 2: Try extracting from markdown code block with ```json or ```
    json_pattern = re.compile(r'```(?:json)?\s*(\{.*?\})\s*```', re.DOTALL)
    match = json_pattern.search(response_text)

    if match:
        try:
            parsed = json.loads(match.group(1))
            logger.debug("Successfully extracted JSON from markdown code block")
            return cast(Dict, parsed)
        except json.JSONDecodeError as e:
            logger.debug(f"Markdown JSON parse failed: {e}")

    # Strategy 3: Try finding any JSON object in the text (greedy match)
    json_pattern = re.compile(r'\{.*\}', re.DOTALL)
    match = json_pattern.search(response_text)

    if match:
        try:
            parsed = json.loads(match.group(0))
            logger.debug("Successfully extracted JSON using greedy pattern")
            return cast(Dict, parsed)
        except json.JSONDecodeError as e:
            logger.debug(f"Greedy pattern JSON parse failed: {e}")

    # Strategy 4: Look for JSON between specific markers
    # Sometimes Gemini adds text before/after the JSON
    json_start = response_text.find('{')
    json_end = response_text.rfind('}')

    if json_start != -1 and json_end != -1 and json_end > json_start:
        try:
            candidate = response_text[json_start:json_end + 1]
            parsed = json.loads(candidate)
            logger.debug("Successfully extracted JSON using start/end markers")
            return cast(Dict, parsed)
        except json.JSONDecodeError as e:
            logger.debug(f"Start/end markers JSON parse failed: {e}")

    logger.error("All JSON extraction strategies failed")
    logger.error(f"Response starts with: {response_text[:100]}")
    logger.error(f"Response ends with: {response_text[-100:]}")

    return None


def _count_unique_speakers(transcript_json: Dict) -> List[str]:
    """
    Count unique speaker labels in transcript JSON.
    """
    segments = transcript_json.get('segments', [])
    speakers = set(seg.get('speaker', 'UNKNOWN') for seg in segments)
    return list(speakers)
