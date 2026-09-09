# Fantasy League History

A Streamlit dashboard for all-time ESPN fantasy football league stats. Data is pulled from
the ESPN API into a local SQLite database (`espn_league.db`), and the app reads from that
database to build the reports.

## How it fits together

| File | Role |
| --- | --- |
| `get_team_details.py` | Fetches teams and owners for each season. Run this first. |
| `get_matchups.py` | Fetches matchup results. |
| `get_box_scores.py` | Fetches per-player box scores (2019 onwards). |
| `get_draft.py` | Fetches draft picks. |
| `db.py` | Schema and all database writes. |
| `league_analytics.py` | Read-only SQL queries used by the reports. |
| `app.py` | The Streamlit dashboard. |

The app only reads from the database. New ESPN data only appears after you re-run the
import scripts — clicking *Rerun* in Streamlit refreshes the UI, not the data.

## Running locally

### 1. Create a virtual environment and install dependencies

Windows (PowerShell):

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

macOS / Linux:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure credentials

Create a `.env` file in the project root:

```
ESPN_S2=your_espn_s2_cookie_value
SWID={YOUR-SWID-GUID}
```

Both values are cookies set by ESPN once you are logged in. To find them, open
`fantasy.espn.com`, press `F12`, then go to **Application → Storage → Cookies →
https://fantasy.espn.com** and copy the `espn_s2` and `SWID` values. Keep the braces on
`SWID`, don't wrap either value in quotes, and don't URL-decode `espn_s2`.

These cookies expire periodically. If imports start failing with an access-denied error,
copy fresh values.

Public leagues work without credentials; private leagues require them.

The league itself is configured at the top of `get_team_details.py`:

```python
LEAGUE_ID = 6164510
YEAR = 2026
HISTORY_YEARS = 1
```

`YEAR` is the current season and `HISTORY_YEARS` is how many seasons back to reach when
the database is empty. Once `teams` has rows, the other scripts iterate over the seasons
already in the database rather than recomputing that range.

### 3. Load the data

Run these in order. The first one creates the seasons that the others iterate over:

```powershell
python get_team_details.py
python get_matchups.py
python get_box_scores.py
python get_draft.py
```

This creates `espn_league.db` in the project root. Each script prints how many rows it
saved and lists any seasons it had to skip.

`get_matchups.py` and `get_box_scores.py` also accept flags for targeted refreshes:

```powershell
python get_matchups.py --year 2026
python get_box_scores.py --year 2026 --week 3
```

Omitting `--year` loads the full history. `--week` requires `--year`. Writes use upserts,
so re-running a season overwrites existing rows rather than duplicating them.

### 4. Start the app

```powershell
streamlit run app.py
```

The dashboard opens at `http://localhost:8501`. Pick a report from the sidebar and use the
season and games filters to narrow the data.

## Keeping data fresh

Streamlit has no built-in scheduler, so the imports run separately. The repo ships a
GitHub Actions workflow (`.github/workflows/daily-update.yml`) that does this in the
cloud — see [Deploying](#deploying).

To schedule it locally instead, on Windows create a Task Scheduler task that runs a batch
file:

```bat
cd /d C:\Users\jimhi\espn-league-stats
venv\Scripts\python.exe get_matchups.py --year 2026
venv\Scripts\python.exe get_box_scores.py --year 2026
```

On Linux, the cron equivalent (Tuesdays at 6am):

```cron
0 6 * * 2 cd /path/to/espn-league-stats && venv/bin/python get_matchups.py --year 2026
```

The import scripts exit with a non-zero status if any season fails, so a scheduler or CI
job will report the failure instead of appearing to succeed.

## Deploying

The app is a standard Streamlit app, so any of the usual options work. The thing to plan
for in all of them is the database: `espn_league.db` is a file, and the app expects to find
it next to `app.py`.

### Streamlit Community Cloud + GitHub Actions (free)

Community Cloud hosts the app; GitHub Actions runs the daily import. The two halves are
connected by the database file in the repo: the workflow commits an updated
`espn_league.db`, and Community Cloud redeploys automatically on the new commit.

1. Push the project to GitHub. `.gitignore` already excludes `.env` and `venv/` while
   keeping `espn_league.db` tracked, since the app needs it at runtime.
2. Add the ESPN cookies as **repository** secrets under
   **Settings → Secrets and variables → Actions**, named `ESPN_S2` and `SWID`. These are
   for the scheduled import — `app.py` never reads them, so they are not needed as
   Streamlit secrets.
3. At [share.streamlit.io](https://share.streamlit.io), create an app pointing at your
   repo and set the main file to `app.py`. Dependencies install from `requirements.txt`.
4. Run the workflow once by hand from the **Actions** tab (**Daily data update → Run
   workflow**) to confirm the credentials work.

Things worth knowing about this setup:

- The filesystem on Community Cloud is ephemeral, so the app can only ever read the
  committed database. All writes happen in Actions.
- Committing the database daily grows the git history. At ~3 MB per commit that is fine
  for a long while, but expect to squash history occasionally.
- GitHub disables scheduled workflows after 60 days with no human activity in the repo,
  and the bot's own commits don't count. You'll get an email with a re-enable button.
- GitHub rejects any pushed file over 100 MiB. The workflow fails the run if the database
  passes 90 MiB so this surfaces before a push breaks.

### Docker

Gives you a persistent database via a mounted volume. There's no Dockerfile in the repo
yet; this is the minimal one:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

```bash
docker build -t espn-league-stats .
docker run -p 8501:8501 --env-file .env \
  -v "$(pwd)/espn_league.db:/app/espn_league.db" \
  espn-league-stats
```

Mounting the database file keeps data across container restarts and lets a scheduled job on
the host refresh it.

### VM or home server

Run it behind a reverse proxy (nginx, Caddy) with a process manager such as systemd:

```bash
streamlit run app.py --server.port 8501 --server.address 0.0.0.0
```

This is the option that handles scheduled refreshes most cleanly, since cron and the app
share a filesystem.

## Notes

- All matchup statistics use starter lineups only; bench and IR players are excluded, and
  winners are derived from starter totals.
- Box scores are only available from 2019 onwards (`MIN_BOX_SCORE_YEAR` in
  `get_box_scores.py`), so earlier seasons have matchups but no player-level data.
- Team names are normalised to strip emoji, so a team renamed with a decoration still
  groups with its earlier seasons.
- `.env` holds live credentials for your ESPN account and is excluded by `.gitignore`.
  Never commit it.
- The importers store only the fields the reports use, not the raw ESPN payloads. Keeping
  the raw JSON made the database 111 MB; without it the same data is under 3 MB.
  `migrate_slim_db.py` is the one-off migration that converted an older database to this
  layout, and can be deleted once every copy has been migrated.
- A player's position comes from ESPN's `defaultPositionId` via
  `DEFAULT_POSITION_ID_MAP` in `db.py`. Those ids are not the same as the lineup slot ids
  in `espn_api`'s `POSITION_MAP`, so don't substitute one for the other.
