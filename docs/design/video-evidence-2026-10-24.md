# Video evidence, first slice, 2026-10-24

Status: structural caption timing and one synthetic visual qualifier.
Default analysis prompts are unchanged. No video was downloaded. No frame
was extracted. No video model was called. This note is not a release row,
does not expand frozen `0.20.8`, and does not close issue #67.

## Question this step answers

Can a video insight record whether caption time and text coverage exist,
without putting cue text into the analysis prompt, and can a separate local
manifest qualify one visual claim against a synthetic frame?

## Caption timing

`distill/ingestors/youtube/caption_timing.py` writes
`caption-evidence.v1` beside the plain transcript. The sidecar name is the
transcript stem plus `.timing.json`. It is not a new library artifact type.

The plain VTT conversion used for analysis is unchanged. It still drops
timestamps and repeated lines. The timed parser keeps one cue per timed
block, including a repeated line. Cue text stays in the sidecar. It is not
copied into the insight body.

Coverage is `unavailable`, `failed`, `empty`, `partial`, or `complete`.
Timing is `unavailable`, `unknown`, or `caption`. Source is
`youtube_captions`, `asr`, `none`, or `interrupted`. An interior gap longer
than 60 seconds makes coverage partial. A tail gap is recorded only when a
duration is supplied. Unknown duration does not invent a tail. Interrupted
capture with cues is partial. Interrupted capture with no cues is failed.
Empty captions are empty. ASR timing is `unknown`. Cue times are not
invented for ASR. A missing sidecar leaves existing insight frontmatter
unchanged. Malformed JSON is failed evidence with source `none`.

`get_transcript` still refuses a non-YouTube identity before any write.
Caption success writes the plain transcript, then the sidecar. Whisper or
scribe success writes ASR evidence after the text file exists. If that file
cannot be read, the sidecar is failed ASR evidence and the transcript call
can still return true. Total acquisition failure writes failed evidence and
returns false.

`process_video` loads the sidecar when it is present and passes it to the
existing short, scan, and full analysis functions. After the model call,
frontmatter gains `caption_timing`, `caption_text_coverage`,
`caption_source`, `caption_cue_count`, and `caption_gap_count`. The prompt
still receives only the plain transcript.

## Synthetic frame manifest

`distill/pipeline/analysis/frame_manifest.py` is not imported by video
analysis. Default analysis does not sample frames.

The sample grid starts at 0 and steps by 60 seconds while the timestamp is
inside the duration. Blind intervals are the open gaps between samples,
including the tail. Repeated slides are consecutive equal fingerprints.

Qualification is structural:

- A claim with no frame timestamp qualifies from the transcript alone, even
  when the manifest is missing or cancelled.
- A frame timestamp on a cancelled or missing manifest is cancelled.
- An advertised frame with `present` false is `missing_frame`. Visible text
  is not used.
- A present unreadable frame is `unreadable`.
- A claim that does not equal the frame's visible text is unmatched.
- A matching claim that contradicts the transcript is `disagreement`. Both
  strings are retained.
- Otherwise the claim is `qualified_visual`.
- A timestamp inside a blind interval, with no frame at that time, is
  `blind_interval`.
- A restarted manifest uses only the frames on that object.

## What remains open on issue #67

This slice does not transcribe a captionless live source, sample a real
slide change, read code from a real frame, or cancel a real capture. A
video-model brief is not qualified. Real-source qualification stays
separately authorized. Issues #33 and #63 stay closed.
