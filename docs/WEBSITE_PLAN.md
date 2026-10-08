# Plan: "Claude plays Zork" — a website where an AI plays Zork I to the end, nonstop

Status: **plan only, nothing implemented.** Builds on the engine in `zork-mcp/`
(see `docs/PLAN.md`).

## 1. What we're building

A public web page that shows an AI playing Zork I live, from "West of House" to
winning (350 points, entering the Stone Barrow). When a run ends, the next run
starts automatically. Viewers see:

- the game transcript, scrolling like a terminal;
- the AI's reasoning summary for each move ("why I'm going north");
- the AI's own notes: map, inventory, open puzzles, plan;
- current room, score, move count, deaths and checkpoint restores;
- past runs: result, moves, time, cost.

Viewers watch; they don't control the game (see section 7, Safety).

## 2. Architecture

```
            ┌──────────────────────── one Linux container ────────────────────────┐
            │                                                                      │
 Claude API │  ┌──────────────┐   tool calls   ┌──────────────┐   stdin/stdout     │
 ◄─────────►│  │ Agent runner │ ─────────────► │  ZMachine    │ ◄────────────────► dfrotz
            │  │ (Python,     │                │  engine.py   │                    │ (native)
            │  │  tool loop)  │                └──────────────┘                    │
            │  └──────┬───────┘                                                    │
            │         │ events (move, reasoning, notes, score, death, run end)     │
            │         ▼                                                            │
            │  ┌──────────────┐    SSE /api/stream    ┌──────────────────────┐     │
            │  │ SQLite       │ ◄──── FastAPI ──────► │ Browser: static page │     │
            │  │ runs, turns, │        /api/runs      │ (HTML + JS)          │     │
            │  │ notes, costs │                       └──────────────────────┘     │
            │  └──────────────┘                                                    │
            └──────────────────────────────────────────────────────────────────────┘
```

Components:

| Component | Tech | Notes |
|---|---|---|
| Game engine | existing `ZMachine` | add a **native** launch mode (no `wsl`) for Linux hosting |
| Agent runner | Python, Anthropic SDK, manual tool loop or Tool Runner | calls `ZMachine` in-process; no MCP hop |
| Store | SQLite (WAL mode) | one file; replays come from here |
| Web API | FastAPI + Server-Sent Events | read-only; one SSE stream fans out to all viewers |
| Frontend | static HTML/CSS/JS, no build step | served by FastAPI |
| Hosting | one Docker image on a small VPS (or Fly.io / Railway) | `apt install frotz` in the image |

**Why not go through MCP here?** MCP is the right interface for Claude Code
and Desktop. For a server-side loop we own, calling the engine in-process
removes a process hop and a failure mode. The tool *definitions* stay the same as
the MCP server's, so prompts and behaviour carry over. The MCP server is still
there for people who want to play from Claude Code.

## 3. The agent

### 3.1 Model and settings
- **Default: Claude Opus 5.5 (`claude-opus-5-5`)**. Zork needs long-horizon
  planning and puzzle solving, so the stronger model is worth it at first.
- Run the same setup on **Sonnet 5.5 (`claude-sonnet-5-5`)** and **Haiku 5.5
  (`claude-haiku-5-5`)** in Milestone 1 and compare cost per *completed* run
  (not per move). Switch only if the cheaper model finishes reliably. Haiku 5.5
  is about 40x cheaper per token than Opus 5.5, but the research in section 11
  suggests smaller models fall off sharply on Zork, so don't assume it will finish.
- Thinking is adaptive and always on with Opus 5.5. Effort is set explicitly:
  start at `medium` for normal moves, and raise it for the "stuck" reflection
  step (3.5). Use `thinking.display: "summarized"` so the site can show
  reasoning to viewers.
- Enable the server-side refusal fallback (`fallbacks: "default"`) so a
  rare false-positive refusal (combat text, for example) doesn't stop the run.
- `tool_choice: auto`. Forced tool use returns a 400 on Opus 5.5, so the system
  prompt tells the model to act through tools every turn.

### 3.2 Tools given to the model

| Tool | Purpose |
|---|---|
| `send_command(text)` | one game command; returns reply plus room, score and moves |
| `update_notes(section, content)` | rewrite one notes section: `map`, `inventory`, `puzzles`, `plan`, `dangers` |
| `save_checkpoint(label)` | named save (the harness also saves automatically, see 3.4) |
| `restore_checkpoint(label)` | go back to a save |
| `list_checkpoints()` | names, with the move and score at each |

`look`, `inventory` and `score` are just `send_command` calls, so the tool
list stays small and stable, which also keeps it cacheable.

### 3.3 Context management: episodes plus notes

A run is thousands of moves, so one ever-growing conversation is not an option.
Plan:

- **Episodes.** One conversation covers K moves (start with K = 60). Then the
  harness ends it and starts a fresh conversation seeded with:
  1. the fixed system prompt (cached);
  2. the current notes, all sections;
  3. the last ~15 moves of transcript;
  4. the current score, moves, checkpoints and lamp turns used.
- **Notes are the long-term memory.** The model is told to keep them current;
  they're the only thing that survives between episodes. They're also what
  viewers see in the notes panel.
- **Why episodes instead of trimming history in place:** with Opus 5.5,
  editing earlier turns invalidates thinking blocks. A fresh conversation per
  episode never edits history, so it avoids that entirely. Within an episode
  the history is append-only and prompt caching works normally.
- **Alternative to test in M1:** server-side compaction (beta
  `compact-2026-01-12`) in one long conversation. It's less code for us, but we
  control less of what's kept. Pick whichever finishes more runs.

### 3.4 Harness-managed safety net
The harness, not the model, guarantees progress isn't lost:
- **Auto-checkpoint** every 25 moves and whenever the score goes up, keeping
  the last 10 in rotation.
- **On death,** Zork I revives you twice, then the game ends. The harness
  records each death. When the game ends, it restores the latest auto-checkpoint
  and tells the model what happened.
- **On a stuck parser state** (the game waiting at an unexpected prompt, or a
  timed-out read), the harness restarts dfrotz and restores the latest checkpoint.

### 3.5 Making sure it reaches the end
Zork I is hard: the thief, the maze, timed puzzles, and the lamp battery. "Always
plays to the end" needs explicit anti-stall measures:

1. **Stuck detector:** no score increase and no new room for N moves (start
   with N = 80) triggers a **reflection step**. That's one extra call at higher
   effort with only the notes and recent transcript, asking for a new plan,
   which is written into `plan`.
2. **Loop detector:** the same command or room cycle repeated three times in a
   row triggers a nudge as a mid-conversation system message.
3. **Resource watch:** the harness tracks lamp-on turns and warns the model
   as the battery runs low. From the ZIL source (`1dungeon.zil`, `1actions.zil`):
   the lamp gives **385 lit turns** in total (200 + 100 + 70 + 15, counted only
   while it's on) and the candles **75** (40 + 20 + 10 + 5). The move counter
   itself has no limit (a 16-bit global, `MOVES`), so the lamp is the real
   clock on a run. Restoring a checkpoint also restores the battery, so restores
   are the recovery path if the lamp is wasted.
4. **Unwinnable state:** if the model concludes the game can't be won (for
   example, a treasure destroyed), it can call `restore_checkpoint` to an earlier
   save. As a last resort the harness starts a new run, recorded as "restarted".
5. **Hint tiers (a policy choice, see section 10):**
   - *Pure*: no outside help. The run may fail; it counts as "gave up after X moves".
   - *Assisted*: after R reflection steps without progress, inject one
     generic hint (an InvisiClues-style nudge, not a walkthrough). Runs are
     labelled "assisted" on the site.
6. **Hard caps:** at most M moves per run (for example 5,000) and $B dollars
   per run. Hitting a cap ends the run as "timed out" and the next one starts.

End detection, from the Zork I source (`gverbs.zil`, `1actions.zil`):

1. Reaching **350 points** sets `WON-FLAG` and prints
   *"An almost inaudible voice whispers in your ear, "Look to your treasures for the final secret.""*
   A map appears in the trophy case.
2. With `WON-FLAG` set, a path **south-west of West of House** leads to the Stone Barrow.
   Entering prints `Inside the Barrow` … `You have mastered the first part of the ZORK trilogy`.
3. The game then runs `FINISH`, which prints
   `Your score is 350 (total of 350 points), in N moves.` /
   `This gives you the rank of Master Adventurer.` and asks
   `(Type RESTART, RESTORE, or QUIT):`.

`FINISH` also runs after a final death or `quit`, so the restart prompt alone
does **not** mean a win. The harness marks a run **won** only when it sees, in
the interpreter's own output (never the model's claim):
`Inside the Barrow` **and** `rank of Master Adventurer` **and** status score 350.
It records the final move count from that line.

### Win conditions for Zork II and III (for later rotation, open question 6)

Neither sequel uses "maximum score" as its win condition. The win is a final
room, which then calls `FINISH`.

| Game | Max score | How it's won (source) | Win signature to detect |
|---|---|---|---|
| Zork I | 350 | 350 points → enter the Stone Barrow (`1actions.zil:403`) | `Inside the Barrow` + `rank of Master Adventurer` |
| Zork II | 400 | Holding the **wand**, go through the door to the runed staircase (`ZORK3-FCN`, `2actions.zil:715`). Sets `WON-FLAG`; score isn't required. With 400 points and no win, the score says *"Master Adventurer, but somehow you don't feel done"*. | `you have conquered the Wizard of Frobozz` + `concludes in "Zork III` |
| Zork III | 7 ("potential", `Your potential is N of a possible 7`) | Reach the **Treasury of Zork**; the Dungeon Master appears and you take his place (`NIRVANA-F`, `3actions.zil:1717`). Score points are optional. | `the Dungeon Master materializes` + `completed your quest in ZORK` |

The harness keeps a per-game table of these signatures (all from the interpreter's output) plus
the max score for display. For Zork III, the site shows "potential X/7" instead
of points.

### Who finished: recording the winner
- Every run row stores who played: model ID, effort, mode (pure or
  assisted), harness version, start and end time, moves, deaths, restores, cost.
- On a win, the harness keeps proof:
  - the full transcript (already in `turns`);
  - the final save file just before entering the barrow;
  - a SHA-256 of the transcript, shown on the run page.
  Anyone can replay the save in Frotz and see the ending.
- **Hall of fame page (`/winners`):** each win with the model, mode, moves to
  win, real time, cost and a link to the replay. Ranked by fewest moves, with a
  separate list for assisted runs.
- Optional: a downloadable "certificate" image per win (model, date, moves,
  rank "Master Adventurer"), generated server-side from the run row.

## 4. Cost estimate (to verify in Milestone 1)

Opus 5.5 prices: $4 per million input tokens, $20 per million output, and $0.20
per million cached input reads. Per move, roughly:

| Part | Tokens | Cost |
|---|---|---|
| Cached prefix (system + notes + episode history), average | ~25,000 | ~$0.005 |
| New input (last tool result and so on) | ~1,000 | ~$0.004 |
| Output (thinking + tool call) | ~600 | ~$0.012 |
| **Total per move** | | **about $0.02** |

- A run of 1,500–3,000 moves (the minimum for Zork I is about 300; an AI exploring
  will take several times that) comes to **about $30–60 per run on Opus 5.5**,
  and roughly half that on Sonnet 5.5.
- At 5–15 s per move, a run takes about 3–10 hours. Back-to-back runs nonstop
  could cost **$100–300 a day**. A daily budget cap and pacing (section 6) are
  needed for that.
- These are estimates. Milestone 1 measures real `usage` numbers per move and
  replaces this table.

## 5. Website

### Pages
- **Live (`/`):** transcript (terminal style, with the AI's command highlighted),
  a reasoning panel, a notes panel, a stats bar (score, moves, deaths,
  checkpoint restores, run time) and a small score-over-moves chart.
- **Runs (`/runs`):** table of past runs: outcome, moves, duration, cost, model,
  pure or assisted.
- **Replay (`/runs/{id}`):** step through a finished run with a move slider.
- **Winners (`/winners`):** the hall of fame (see 3.5).
- **About:** what this is, the open-source credits (MIT-licensed Zork source,
  Frotz), and a link to the repo.

### API
| Endpoint | Purpose |
|---|---|
| `GET /api/stream` | SSE: `turn`, `reasoning`, `notes`, `status`, `run_start` and `run_end` events |
| `GET /api/state` | snapshot for a new viewer: current run, last 50 turns, notes |
| `GET /api/runs` | run list |
| `GET /api/runs/{id}/turns?from=&to=` | paged turns for replays |
| `GET /healthz` | worker alive, last move time, today's spend |

New viewers load `/api/state` and then subscribe to the stream, so they never
see an empty screen.

### Data model (SQLite)
- `runs(id, started_at, ended_at, outcome, model, effort, mode, harness_version, moves, score, rank, deaths, restores, cost_usd, transcript_sha256, final_save)`
  — `outcome` is one of `won`, `died`, `gave_up`, `capped`, `restarted`
- `turns(run_id, n, command, reply, room, score, moves, reasoning_summary, tokens_in, tokens_cached, tokens_out, cost_usd, at)`
- `notes(run_id, n, section, content)`, versioned so replays can show notes at each move
- `checkpoints(run_id, label, move, score, file)`

## 6. Operations

- **Supervisor:** the container runs two processes, the web server and the agent
  worker, under a supervisor (or as two services in `docker-compose`). The
  worker restarts on crash and resumes the current run from the latest checkpoint
  and notes.
- **Pacing:** an optional minimum delay between moves (for example 3 s) so it's
  watchable. That also caps spend per hour.
- **Budgets:** per-run and per-day dollar caps from summed `usage`. When the
  daily cap is hit, the worker pauses and the site shows "resting until 00:00 UTC".
- **API errors:** the SDK retries 429 and 5xx errors. After repeated failures the
  worker backs off for minutes, not seconds, and the site shows "reconnecting".
- **Secrets:** `ANTHROPIC_API_KEY` stays in the server environment only.
- **Logs:** the `request-id` per call, so failed calls can be traced.

## 7. Safety and abuse
- **No viewer input reaches the model.** That rules out prompt injection and
  people driving up the bill. A later "cheer" or reaction feature stays
  cosmetic and isn't sent to the agent.
- The page is read-only, so it needs no accounts or auth. Rate-limit
  `/api/*` per IP. SSE connections are cheap but capped (for example 500).
- Game text is shown as plain text and HTML-escaped. The model's reasoning and
  notes are escaped too.

## 8. Milestones

| # | Milestone | Done when |
|---|---|---|
| M0 | Decisions | the open questions in section 10 are answered |
| M1 | **Headless runner** (local, Windows/WSL engine) | the agent plays Zork I in the console with episodes, notes, checkpoints, stuck detection and budget caps, logging to SQLite. Measure cost per move and try at least 3 full runs. **This is the main risk: if it can't finish, everything else is moot.** |
| M2 | Engine native mode | `ZMachine` launches `dfrotz` directly on Linux; tests pass in a Linux container |
| M3 | Web viewer (local) | FastAPI + SSE + static page show a live run and the run list |
| M4 | Container and deploy | Docker image (Python, uv, frotz, story file); runs on the host; health check; restarts on crash |
| M5 | Polish | replay page, score chart, About page, daily budget display, Sonnet comparison runs |
| M6 | *Optional:* "Small model in your browser" page (section 11) | game and a small local model both run in the visitor's browser; labelled as an experiment, not expected to finish |

Suggested order: M1 → M2 → M3 → M4 → M5. M1 is the gate; if Opus
finishes fewer than 1 in 3 pure runs, decide on the assisted mode before building the site.

## 9. Proposed layout

```
zork-mcp/                 existing engine + MCP server (unchanged, engine gains native mode)
zork-live/
  pyproject.toml          deps: anthropic, fastapi, uvicorn, sse-starlette (or Starlette's own), zork-mcp (path dep)
  src/zork_live/
    agent.py              episode loop, tools, prompts
    harness.py            checkpoints, stuck/loop detection, budgets, run lifecycle
    store.py              SQLite schema and queries
    web.py                FastAPI app, SSE broadcaster
    prompts/system.md     the fixed system prompt
  static/                 index.html, runs.html, replay.html, app.js, style.css
  Dockerfile
  docker-compose.yml
  tests/
```

## 10. Open questions (answer before M1)

1. **Pure or assisted?** May the AI get hints when stuck, or must every run be
   unaided even if some never finish?
2. **Budget:** what daily and per-run spend are you comfortable with? This sets
   the pacing and how many runs a day.
3. **Model:** start on Opus 5.5 as planned, or go straight to Sonnet 5.5 to save money?
4. **Hosting:** which provider (a VPS you have, Fly.io, Railway, ...) and what
   domain? Public, or private behind a password?
5. **Pace:** as fast as possible, or slowed to be watchable (for example one move
   every 5–10 s)?
6. **Scope:** Zork I only, or should runs later rotate through Zork II and III?
7. **Browser small-model page (M6):** build it as a side experiment, or skip it?

## 11. Research: can a small model play Zork in the browser? (2026-10-08)

**Short answer:** it can *run* in the browser today, but it **can't play Zork I
to the end**. Evidence says it won't get much past the start. Keep the live
"plays to the end" show on a frontier model server-side, and treat a browser
small model as an optional experiment.

### It is technically possible
- **The game in the browser:** `ifvms.js` (MIT) is the Z-machine engine behind
  Parchment, the standard web interpreter. It runs `zork1.z3` client-side with
  no server. Other options are JSZM (public domain, no DOM, bring your own UI)
  and `zmachine-core` (TypeScript, a hobby project at 0.1.0).
- **The model in the browser:** WebLLM (`@mlc-ai/web-llm`, WebGPU,
  OpenAI-style API, 160+ prebuilt builds from SmolLM2 360M to 13B) or
  Transformers.js v4 (WebGPU, tool-calling support in its text-generation
  pipeline; Qwen3-0.6B and Gemma 4 demos run fully client-side).
- **Practical size:** about 1–4B parameters at 4-bit. A 4-bit Llama 3.2 1B is a
  ~700 MB download and needs ~900 MB of GPU memory. WebGPU is in Chrome/Edge,
  Safari 26 and Firefox 141 on Windows, but support varies by device, and phones
  struggle.
- **Cost:** zero for us per move. The visitor's GPU does the work.

### It won't get far
- **Local models on Zork I** (one author's harness, 100-move cap, 5 games each):
  - Gemma 4 26B MoE averaged 19 points (best run 40), and Mistral Small 24B averaged 12.
  - Qwen 2.5 14B averaged 3; Phi-4 Reasoning 14B and Gemma 4 E4B (~4B active) scored 0.
  - No model got past the troll.
  - The author describes "a cliff, not a gradient" as models get smaller. Even the
    24–26B models are far too big for a browser.
- **TextQuests** (25 Infocom games incl. Zork I–III): even frontier models
  completed no game without clues. Smaller "mini" models made much less progress
  (about 5–22% average progress without clues against ~31% for the best model).
  The paper says model scale matters a lot for these tasks.
- **Earlier studies** put ChatGPT-era models and RL agents at roughly 10–45 of
  350 points on Zork I.
- Taken together: a 1–4B browser model would likely score 0–10 points and loop
  near the house. That's interesting to watch once, but it's not "plays to the end".

### What a browser page could still be (M6, optional)
- **"Watch a tiny model try":** ifvms.js and WebLLM both in the visitor's
  browser, using the same harness ideas (notes, loop detection, auto-saves),
  ported to JavaScript. It's honest about being weak, costs us nothing, and makes
  a nice contrast with the frontier model on the live page.
- **Heavier scaffolding helps a little:** a harness-maintained map, a
  valid-action list (Jericho-style), and forced short commands. This lifts small
  models but won't close the gap to finishing the game.
- **Not recommended:** making the browser model "finish" with a scripted
  walkthrough. At that point the AI isn't playing.

### What changes in this plan
- The main site stays as designed: a frontier model server-side.
- M1 now also measures Sonnet 5.5 and Haiku 5.5 as cheaper server-side options.
- New optional milestone M6 for the in-browser small-model page.
- The live site keeps `dfrotz` on the server. `ifvms.js` is only needed for M6.

### Sources
- Bahgat, "Same agent, different score" (local models on Zork I): https://www.abahgat.com/blog/same-agent-different-score/
- Bahgat, "Stuck in the maze": https://dev.to/abahgat/stuck-in-the-maze-why-ai-agents-cant-hold-the-map-2fjm
- TextQuests (Phan et al., 2025): https://arxiv.org/abs/2507.23701
- "Can LLMs play text games well?" (2023): https://arxiv.org/abs/2304.02868
- WebLLM: https://webllm.mlc.ai/ and https://pinggy.io/blog/run_llm_in_browser_webgpu/
- Transformers.js releases: https://github.com/huggingface/transformers.js/releases
- ifvms.js: https://github.com/curiousdannii/ifvms.js
- JSZM: https://www.ifwiki.org/JSZM
- zmachine-core: https://npmjs.com/package/zmachine-core
