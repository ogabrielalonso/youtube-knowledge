# Changelog

## 0.1.0

First public release.

- One-command installer for macOS and Linux, no sudo: Python 3.12 via uv, yt-dlp with EJS and
  curl-cffi impersonation, Deno, bundled ffmpeg and CPU Whisper, with pinned dependency constraints.
- Shared skill for Claude Code (`/youtube-knowledge <url>`) and Codex (`$youtube-knowledge <url>`),
  installed into each agent's skills folder with the absolute path of the CLI.
- `yk` CLI: `fetch`, `keyframes`, `check`, `clean`, `doctor` and `config`.
- Captions through yt-dlp's own downloader (including HLS-served automatic captions), rolling
  caption cleanup, and Whisper fallback when no usable captions exist.
- Visual keyframe selection by thumbnail difference.
- Note validation: Markdown-aware wikilinks and attachments, frontmatter values, minimum
  non-blank line counts and the optional dash rule.
- Lease-based cleanup, so concurrent runs never delete each other's work.
- Existing vault notes are never rewritten: their text and frontmatter values are preserved,
  and additions are limited to reciprocal links, keys the vault already uses and an optional
  source section.
- Manifest-based uninstall that removes the managed installation and leaves vault notes,
  work directories, skill backups and shared caches untouched.
- 167 tests.
