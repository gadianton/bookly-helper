# Docker containers

Branches are not run in containers to keep them side by side.

## Why
The only clash between branches' servers was the port; the server keeps no shared state on disk, and each task folder already has its own Python environment. A container would still need its own host port, so it adds a build step without removing the clash.

## Prior requests
- 2026-10-10: run each worktree's build in its own Docker container
