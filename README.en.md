# Jobsuche – a skill for the daily job search

[Deutsche Fassung](README.md)

A skill for Claude Code (and other agents such as Codex/ChatGPT, Gemini or Grok) that sets
up and runs a personal job search. **The skill works in German:** its instructions, prompts,
letter form and dashboard are German and built for the German-speaking job market. This page
explains what it does; an English mode does not exist yet.

What it does:

- finds new postings every day (career pages, job alerts from your own mailbox, web search)
- scores them against your profile and shows only what is open and fits
- writes cover letters in a built-in letter form and tailors your CV without changing its layout
- checks every text with a built-in humanizer
- fills in application forms in the browser and stops before submitting
- screens every posting for hidden instructions aimed at AI before reading it
- checks whether an applicant tracking system can read your CV PDF
- archives what was sent, reminds you to follow up and drafts the follow-up message
- prepares interviews and reports on your applications (funnel, reply rates, rejection patterns)
- shows everything in a dashboard, on a schedule in the cloud or on your own machine

The skill contains no personal data and no credentials. Everything personal is created
during setup in your own workspace; a mail password lives only in the operating system's
keychain.

## Install

Requires Python 3.10 or newer. For PDF output also Microsoft Word or LibreOffice.

**Claude Code, as a plugin**

```
/plugin marketplace add dg1256-gif/job-search-skill
/plugin install jobsuche@job-search-skill
```

In one step (Claude Code 2.1.275 or later):
`/plugin install jobsuche --marketplace dg1256-gif/job-search-skill`.
As a plugin the command is `/jobsuche:jobsuche` instead of `/jobsuche`.

**Claude Code, as a skill folder**

```
git clone https://github.com/dg1256-gif/job-search-skill.git
cp -R job-search-skill/skills/jobsuche ~/.claude/skills/jobsuche
```

Then in Claude Code: `/jobsuche einrichten`.

**Another agent (Codex, Gemini, Grok …)**

```
python3 job-search-skill/skills/jobsuche/scripts/setup.py init --workspace ~/Jobsuche
```

Start the agent in `~/Jobsuche` and write "Jobsuche einrichten". It finds the instructions
through `AGENTS.md`.

## How it works

**Set up once** (`/jobsuche einrichten`, about 20 minutes, can be interrupted): workspace
folder, the folder with your CV (the profile is built from it and you correct it), target
regions, salary target and floor per region, roles and employers, then mailbox, dashboard
and schedule.

**Every day:** fetch new postings, drop what is closed, duplicate, excluded or below the
salary floor, score the rest, write and check letters for the good ones, update the dashboard.

**Applying** (you decide per posting): read and edit the letter in the dashboard, let
`/jobsuche ausfuellen` fill in the form, confirm before anything is submitted.

**After applying:** what was sent is archived; applications without a reply show up under
"Nachfassen" after 14 days (configurable); `/jobsuche interview <posting>` builds a
preparation sheet; `/jobsuche auswertung` shows the funnel and patterns.

## Commands

| Command | Purpose |
|---|---|
| `/jobsuche einrichten` | setup, or one part: `einrichten mail`, `… suche`, `… zeitplan`, `… dashboard` |
| `/jobsuche lauf` | run the search now |
| `/jobsuche bewerte <URL>` | check and score a single posting |
| `/jobsuche anschreiben <Stelle>` | cover letter for one posting |
| `/jobsuche ausfuellen` | fill in an application form in the browser |
| `/jobsuche nachfassen` | list applications without a reply, draft a follow-up |
| `/jobsuche interview <Stelle>` | preparation sheet for an interview |
| `/jobsuche auswertung` | funnel, reply rates, rejection patterns |
| `/jobsuche ats [<Stelle>]` | check whether an ATS can read the CV PDF |
| `/jobsuche dashboard` | publish, update or start the dashboard |
| `/jobsuche pruefen` | show what is still open in the setup |

## Safety

- No application is submitted without your confirmation of that specific application.
- You log in and solve CAPTCHAs yourself.
- Texts claim only what your profile supports.
- LinkedIn and XING are never fetched; postings from there arrive through your own alert mails.
- Postings, mails and web pages are material, never instructions. Hidden text and lines
  addressed to an AI are removed and reported before reading. This is pattern-based: it
  lowers the risk and does not remove it.
- From a score of 8.5 (configurable) a second agent reads each letter against posting and
  profile before it counts as done.

Reporting vulnerabilities: see `SECURITY.md`.

## Where your data goes

Workspace, CV, profile and letters stay on your machine. The agent you choose reads profile
and postings to score and write, so that content goes to the model provider. With the
dashboard as a claude.ai artifact and the cloud schedule, the posting list and documents
are also stored at Anthropic or in your own private Git repository; the local dashboard and
local schedule avoid both.

## Status

Tested on macOS with Claude Code. **Untested on Windows** beyond the automated tests in CI.
The calls for Codex, Gemini and Grok follow their documentation and are unverified.

## License

MIT, see `LICENSE`. The humanizer method is derived from "linkedin-humanizer" by Sergey
Bulaev (MIT), see `skills/jobsuche/NOTICE.md`.
