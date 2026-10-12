# Agent skills

`docling/` is the official Docling agent skill (MIT, docling-project) copied from the Docling package
pinned in the worker image (`docling==2.130.0`, path `site-packages/docling/.agents/skills/docling`).
The same copy is in `.claude/skills/docling/` for Claude Code. Refresh both after a Docling upgrade:

    c=$(docker compose ps -q worker)
    docker cp "$c:/usr/local/lib/python3.12/site-packages/docling/.agents/skills/docling" .agents/skills/
    docker cp "$c:/usr/local/lib/python3.12/site-packages/docling/.agents/skills/docling" .claude/skills/

(`uvx library-skills --claude` does the same when Docling is installed in the host environment.)
