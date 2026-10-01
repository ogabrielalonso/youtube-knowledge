---
name: youtube-knowledge
description: Extract complete knowledge from YouTube videos of any length, analyze their entire transcript and meaningful visual content, and create substantial topic-routed Obsidian MOC and insight notes with validated bidirectional links when a user asks to learn from or document a YouTube video.
---
<!-- youtube-knowledge:managed -->

# YouTube Knowledge

Turn a video into substantial, interconnected knowledge. The method is complete
analysis before writing, whether the video lasts 15 minutes or three hours or more.
The CLI handles extraction and checks; you perform analysis and write the notes.

## Resolve the request

Input in Claude Code: `/youtube-knowledge <URL> [vault]`.
Input in Codex: `$youtube-knowledge <URL> [vault]`, or ask in natural language.

Before running CLI commands, use `yk` if it is available on PATH. Otherwise use
the installed wrapper below, or `~/.youtube-knowledge/bin/yk` for a default install.
Substitute that executable for `yk` in every command in this skill.

<!-- youtube-knowledge:wrapper -->

1. Resolve the vault in this order: the user's explicit argument, then
   `yk config get vault --json`, then ask the user for the path and offer to save it
   with `yk config set vault "/path/to/vault"`. Do not guess a personal vault path.
2. Confirm that the chosen directory exists and contains `.obsidian/`. Read and
   respect the vault's instructions before modifying notes.
3. Read `yk config get --json`. `notes_language: auto` means the video's original
   language. Otherwise use the configured language for prose and section titles.
   Retain exact source quotations and label translations when needed.
4. `no_dashes: true` is the default house style: normalize U+2013 and U+2014
   in source titles, frontmatter `source_title`, and exact quotations to a plain
   hyphen with surrounding spaces. This normalization is the only permitted
   change to an otherwise exact title or quotation. Do not use those Unicode
   dashes elsewhere in notes, frontmatter, or your report. The user can disable this with
   `yk config set no_dashes false`. Attribute quotations as `> Speaker, Video Title`.

Only if neither `yk` nor the wrapper exists, tell the user to run this installer,
then resume after setup:

```bash
curl -fsSL https://raw.githubusercontent.com/ogabrielalonso/youtube-knowledge/main/install.sh | bash
```

## Principles

- Analyze the complete transcript and meaningful keyframes before writing any note.
- Prefer two or three excellent insights over ten shallow notes. No empty notes.
- Route by the dominant topic, not by the tool mentioned in the title. A video
  about using an AI assistant for a second brain belongs with knowledge management,
  not automatically with that assistant's tooling notes.
- Before writing, search the vault using keywords and the agent's search tools.
  Use semantic search if the vault provides it. Find the existing topic cluster,
  write there, and connect the new notes bidirectionally with relevant siblings.
- Persist through long videos. Track progress and continue reading until the end.
  If a dependency or access issue blocks completion, report the actual blocker
  and retain working artifacts for recovery. Never claim partial analysis is complete.
- Clean up only this video's owned working directory after successful validation.
  Never delete a glob such as `yt_*` or another session's files.

## Extract deterministic artifacts

```bash
yk fetch "URL" --json
```

Use the real URL. Read the returned `workdir`, `lease`, and `video_id`; use those exact values
in subsequent commands. The default directory is the configured temporary root
or the system temporary directory, followed by `yt_<video_id>`. An explicit
`--workdir` is an exact directory and must have that basename.

The command writes `info.json`, original-language and English subtitles when
available, a video at no more than 720p, `frames/`, `transcript.txt`, and `meta.json`.
Captions become timestamped text with rolling duplicates removed. When captions
are absent, CPU Whisper transcribes audio with the configured model (default `base`).
The first fallback run downloads that model. Read `transcript_source` from the
metadata; distinguish `manual`, `auto`, and `whisper` in the final report.

Frames are extracted every five seconds at 1280 pixels wide. Frame N covers
`(N-1)*5` through `N*5` seconds. Reruns reuse completed artifacts. `--no-video`
is for an explicitly requested transcript-only run; audio may still be needed
for Whisper. Do not silently skip visual analysis in a normal knowledge run.

If extraction fails, inspect the reported error. A bot check can result from a
datacenter or VPN IP. Explain the suggested browser-cookie setting and, if needed,
a retry on the user's own machine. Private or unavailable videos require a valid
URL and an account with access. Do not retry blindly. For a persistent extractor
failure, recommend rerunning the installer to upgrade yt-dlp, then retry once.
If it still fails, report the cause and ask for an accessible URL or transcript.
Do not use raw yt-dlp, ffmpeg, or improvised transcript scripts.

## Analyze everything before writing

1. Read the ENTIRE `transcript.txt` in blocks of approximately 650 lines. Continue
   from the last offset until the end, not just until enough material seems available.
   Track topics and timestamps, exact quotations, frameworks, tools, and actionable
   steps. A summary or sampled transcript does not satisfy this step.
2. Generate visual candidates:

   ```bash
   yk keyframes "WORKDIR" --json
   ```

   Substitute the returned directory. The selector compares consecutive grayscale
   32x18 thumbnails with pixel differences. Read `keyframes.json`, align its
   timestamps with screen-sharing windows in the transcript, and inspect the
   selected images. Do not read every raw frame individually.
3. Always inspect meaningful frames containing text, diagrams, slides, code, or
   demonstrations. Pixel similarity is only a filter, not proof of redundancy.
   If a screen-share interval or small text change is missing, inspect the nearby
   raw frames and lower `--threshold` if necessary. Do not use `--max` to truncate
   required analysis. Track how many frames you actually inspected in detail.
   Reference scale, not a quota: a 94-minute video can yield 1126 extracted frames,
   approximately 220 keyframes, and approximately 30 frames requiring detailed reading.
4. Synthesize BEFORE writing: the central problem, three to five main concepts,
   what is novel versus generic, and practical takeaways. Separate what the source
   demonstrates from your interpretation. Do not invent unread visuals or quotations.
5. Search the existing topic cluster now. Inspect likely siblings and any source
   INDEX. Decide the destination, what deserves a standalone insight, and which
   existing notes should receive reciprocal links.

## Write substantial notes

Always create one MOC (overview). Usually create two to five insights, more for a
video over three hours when justified. A standalone insight should have at least
three minutes of dedicated explanation, a meaningful framework or diagram, a
step-by-step process, or equivalent standalone value. Do not manufacture insights
to reach a count.

Use hyphen-separated filenames without special characters, at most 50 characters
including `.md`. Use descriptive ASCII slugs while keeping titles in the configured
notes language. Follow existing topic organization and naming conventions where
compatible. Existing notes are the user's content. Never delete, rewrite, reorder,
or reformat existing text, and never change an existing note's title, filename, or
existing frontmatter values. Before writing to an existing note, record its current
content by reading it. After editing, confirm that the original text is still present
verbatim; if it is not, restore it before continuing.

Edits to existing notes are additive only. Append wikilinks to an existing Related
section, or add a Related section at the end if none exists. Add frontmatter keys
only when the vault already uses those keys. Optionally append one clearly headed
section at the end, such as `## From "<video title>"`, with a short summary and a
link to the new MOC or insight. Never change existing frontmatter values or content
to fit this skill's schema.

When an existing note already covers a concept explained in depth by the video,
write the new insight as a new note with a different, more specific filename and
link the existing note and new insight both ways. Mention this overlap in the
report. Do not use an existing note as a substitute for a new insight.

Each note has YAML frontmatter with these keys:

| Key | Value |
| --- | --- |
| `source` | `youtube`, or an established source identifier required by the vault |
| `type` | `moc`, `insight`, `tactic`, or `principle` |
| `title` | Descriptive title |
| `description` | Dense, specific summary of the note's value |
| `source_title` | Exact video title, applying the configured dash normalization above |
| `source_url` | Canonical YouTube URL |
| `channel` | Source channel |
| `duration` | Video duration in seconds |
| `upload_date` | Upload date from metadata |
| `tags` | A YAML list of meaningful topic tags |
| `status` | `active` |
| `created`, `modified` | Actual dates in ISO format |
| `parent` | Quoted wikilink to the source INDEX for a MOC if one exists, otherwise null; insights link to the MOC |
| `related` | YAML list of quoted wikilinks to relevant existing sibling notes |

Use real values and quote wikilinks in YAML. A genuinely unavailable source field
can be null with an explanation in the note. Do not invent metadata or use filler.

### MOC: at least 150 non-blank lines

Include all applicable sections, translated to the notes language:

- Metadata table: channel, duration, URL.
- Central Thesis: one substantial paragraph.
- Overview: three to five paragraphs covering the problem and proposed solution.
- Key Concepts: dense explanation, source quotation, how to apply it, and a link
  to the corresponding insight when one exists, for each concept.
- Timestamps: a table linking moments to topics.
- Notable Quotations: exact, attributed statements.
- Tools and Resources: those actually mentioned, if any.
- Action Items: practical steps supported by the source.
- Related Notes: the relevant topic cluster and newly created insights.
- Processing footer: transcript source and extracted, selected, and inspected
  frame counts.

### Insights: at least 50 non-blank lines each

An insight must be useful without reading the MOC. Include:

- Opening quotation with attribution.
- What It Is.
- The Problem It Solves.
- How It Works, with concrete steps.
- Practical Examples.
- Key Principles.
- When to Use and When NOT to Use.
- Related: MOC and relevant sibling notes.
- Source footer with the relevant timestamps.

Remove a section that would otherwise be empty. Never leave placeholders, TODOs,
generic filler, or empty headings. The line minimum counts actual non-blank lines;
it is a floor for substantial content, not a reason to split sentences artificially.
If the source cannot support the required substance, explain the limitation instead
of padding notes or claiming completion.

## Validate, connect, clean, report

1. Finish all new notes so their links can resolve. Run:

   ```bash
   yk check "MOC_PATH" "INSIGHT_PATH" --vault "VAULT_PATH" --json
   ```

   Supply all actual new or updated source notes. Fix each failure: required
   frontmatter, minimum lines, forbidden dashes when enabled, and every wikilink.
   Alias and heading links must point to existing notes. Validation checks note
   targets, not heading existence or the truth of your analysis. Review content too.
2. Add reciprocal links in the Related sections of the cited sibling notes and
   update the source INDEX if applicable, following the additive-only rules above.
   Recheck changed YouTube notes; inspect links added to legacy notes without
   imposing this skill's source-note schema on the entire vault.
3. After successful validation, run `yk clean "WORKDIR" --lease "LEASE" --json` with the exact
   `workdir` and `lease` returned by that fetch. Each successful fetch creates a
   fresh lease, including cached reruns. Release each lease once; the directory
   is removed only after its last lease. Video IDs and stale tokens are refused.
   Never use a shell deletion glob.
   On interruption, report retained work and resume before cleanup.
4. Report the video, channel and duration; each created note's path and real line
   count; transcript source; extracted/keyframe/actually inspected counts;
   validation outcome; reciprocal links and INDEX changes; and cleanup outcome.
   List every existing note touched and exactly what was appended. Mention any
   overlap between a new insight and an existing note, plus limitations plainly.
   Report success only for actions actually completed.
