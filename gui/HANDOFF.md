# Handoff: M365-Assess Consultant GUI — module import bug

Written for a fresh coding agent/session picking this up with no prior
context. Read this fully before touching code.

## What this project is

A Flask + HTML page ("Consultant Console") that wraps the `M365-Assess`
PowerShell module, so a security consultant can run a Microsoft 365
security assessment against a client tenant without opening a visible
PowerShell window in front of the client. The user is a solo M365 security
consultant, not a developer — **all responses to them must use simple,
plain, non-technical language.** No jargon, no assuming familiarity with
PowerShell/dev concepts.

- Fork: `https://github.com/AbuAyrin/M365-Assess` (upstream: `Galvnyz/M365-Assess`)
- Working branch: `consultant-gui` (built on top of a `branding` branch —
  both are merged into `consultant-gui`, which has everything)
- Everything GUI-specific lives under `gui/`; the actual assessment engine
  is the untouched-except-for-branding module under `src/M365-Assess/`
- User's local checkout: a downloaded zip (not a git clone), extracted to
  `C:\Users\Muhammed.Mahalil\Downloads\M365-Assess-consultant-gui\M365-Assess-consultant-gui\`
  — note the **doubled folder name** in that path. Flagged once as
  possibly a duplicate-extraction artifact, never fully chased down.
  Tenant being tested against: `Mannai.onmicrosoft.com`. Admin UPN used
  in testing: `muhammed.fadil@mannai.onmicrosoft.com`.

## How updates reach the user

The user does not use git. Every fix is pushed to `consultant-gui` on
GitHub, then the user runs `gui/Update-Console.ps1` (already on their
machine), which re-downloads every `gui/*` file fresh from
`raw.githubusercontent.com/AbuAyrin/M365-Assess/consultant-gui/gui/...`.

**Caching gotcha, learned the hard way:** that branch-name raw URL lags
a few minutes behind a push. If a fix needs to be verified *right after*
pushing, fetch it via the commit SHA instead, which is not cached stale:
`raw.githubusercontent.com/AbuAyrin/M365-Assess/<full-40-char-sha>/gui/<path>`.
Confirmed immediate/correct; the branch-name form was confirmed stale for
several minutes after a push during this session.

Standard update flow given to the user each time:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force   # only needed in a fresh window
.\Update-Console.ps1
```
Then close and reopen with `Start-Console.bat`, and retry.

## Environment specifics (confirmed on the real test machine)

- Windows PowerShell 5.1 (`powershell.exe`) was the user's original,
  long-installed shell. PowerShell 7 (`pwsh`) was installed partway
  through this project specifically because `M365-Assess.psd1` requires
  it (`PowerShellVersion = '7.0'` in the manifest — confirmed, not
  optional).
- The 8 required `Microsoft.Graph.*` modules (see
  `src/M365-Assess/M365-Assess.psd1` → `RequiredModules`) are installed
  **only** under the Windows PowerShell 5.1 module folder —
  `Documents\WindowsPowerShell\Modules` — not under PowerShell 7's own
  module folder. Confirmed directly by the user running
  `Get-Module Microsoft.Graph.Authentication -ListAvailable` in their
  `pwsh` session, which found it at
  `C:\Users\Muhammed.Mahalil\Documents\WindowsPowerShell\Modules`.
- `ExchangeOnlineManagement`: both 3.10.1 and 3.7.1 are installed
  side-by-side; the tool pins to 3.7.1 at runtime due to an MSAL
  assembly conflict with 3.10.1 (this part works correctly, not the bug).

## Current, unsolved bug

Running an assessment through the GUI fails at the very first step —
importing the M365-Assess module inside `gui/Run-Assessment.ps1` — before
any tenant connection is even attempted. The exact error text has shifted
across attempts (see below); the last one seen was:

```
The specified module 'Microsoft.Graph.Authentication' was not loaded
because no valid module file was found in any module directory.
```

**The user's last message was "same issue" after the 3rd fix attempt
below, without pasting the new exact error text.** Getting that exact
text is the necessary first step — see "Immediate next step."

## What's already been tried, in order — all insufficient

1. **Bare-name pre-import.** Added, before importing the M365-Assess
   manifest:
   ```powershell
   Import-Module -Name 'Microsoft.Graph.Authentication' -ErrorAction Stop
   ```
   (and the other 7 required Graph modules the same way). Theory: PowerShell's
   `RequiredModules` auto-load is unreliable when the manifest itself is
   imported by full file path rather than resolved by name from the module
   path. Result: failed with *"no valid module file was found in any module
   directory"* — a stronger, more definitive failure than the original
   "required module ... is not loaded" error, which is what led to
   attempt 2.

2. **Patch `$env:PSModulePath` with a computed path.** Added:
   ```powershell
   $legacyModules = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'WindowsPowerShell\Modules'
   if ((Test-Path -Path $legacyModules -PathType Container) -and ($env:PSModulePath -notlike "*$legacyModules*")) {
       $env:PSModulePath = "$legacyModules;$env:PSModulePath"
   }
   ```
   Reasoning was sound (the module genuinely lives in that kind of
   folder, per the user's own `Get-Module -ListAvailable` output) but the
   **fix did not work** — user got the exact same "no valid module file
   was found" error again. Leading (unconfirmed) theory when this was
   abandoned: `[Environment]::GetFolderPath('MyDocuments')` may resolve to
   a *redirected* path (e.g. OneDrive-redirected Documents) that differs
   from the real, non-redirected folder the user's own diagnostic output
   showed. This was never actually confirmed — worth checking directly:
   ```powershell
   [Environment]::GetFolderPath('MyDocuments')
   ```
   and compare against the literal path from `Get-Module -ListAvailable`.

3. **Import by `Get-Module -ListAvailable`-discovered path.** Replaced
   both prior approaches with:
   ```powershell
   $found = Get-Module -Name $graphModule -ListAvailable -ErrorAction SilentlyContinue |
       Sort-Object Version -Descending | Select-Object -First 1
   if (-not $found) { throw "..." }
   Import-Module -Name $found.Path -ErrorAction Stop
   ```
   This exact pattern (discover via `-ListAvailable`, import the resolved
   `.Path`) was verified working in a sandboxed test against a real
   installed module before shipping — see git log for the verification
   command used. **User reports "same issue"** after trying this on the
   real machine. Exact new error text not captured. This is the most
   important open thread: if `Get-Module -ListAvailable` can find the
   module (confirmed it can, from the user's own earlier direct run) but
   `Import-Module -Name <that exact resolved path>` still fails the same
   way, that's a stranger and more specific problem than a path/lookup
   issue — possibly:
   - A genuinely corrupt or partial module install at that path (missing
     files the `.psd1` references, e.g. a `.psm1` or nested binary)
   - A PowerShell 7 vs. Windows PowerShell 5.1 **compatibility** issue —
     some modules are 5.1-only and PS7 refuses to load them even when
     found, for reasons other than "not found" (worth checking
     `CompatiblePSEditions` in the module's own manifest)
   - The version installed (2.39.0, per the user's own `-ListAvailable`
     output) may not actually be usable by PS7 for some other reason
   - A different code path than the one just changed is what's actually
     erroring (double check the *exact* file/line in any new error text)

## Also fixed in this session — working, not the current blocker

All committed and pushed to `consultant-gui`, all verified before
shipping (via direct reproduction in a sandboxed pwsh, Playwright
rendering, or a real Flask test client — not just reasoned about):

- PowerShell 7 requirement: preflight check in `Setup.ps1` and
  `backend.py` with a plain-language error pointing at
  `winget install Microsoft.PowerShell`
- `-Section` parameter wasn't binding correctly when
  `Run-Assessment.ps1` is launched via `pwsh -File` from a spawned
  subprocess (PowerShell's `-File` argument binding doesn't slurp
  multiple space-separated tokens into an array parameter the way an
  in-session call does) — fixed by passing one comma-joined string and
  splitting it back into an array inside the script
- The GUI's status page didn't display the backend's `error` field, only
  `recentLog` — so a failure before any log output existed (e.g. a
  Python-level exception) looked like an empty, silent failure — fixed
- Report-detection hang: the backend only checked for the finished report
  *after* the spawned `pwsh` process fully exited, but a lingering
  Exchange Online session/cleanup can keep the process alive well after
  the report is actually written — reproduced directly with a stand-in
  script, fixed by checking for the report as soon as the
  `GUI_BRIDGE: RESULT_FOLDER=` marker line appears in the stream, not
  waiting for process exit
- `Test-BlockedScripts` (a real M365-Assess safety feature) refuses to
  run if any `.ps1` file is still tagged "downloaded from the internet"
  (Windows Zone.Identifier) — `Setup.ps1` and `Update-Console.ps1` now
  auto-unblock every `.ps1` under the repo root
- A stale background copy of `backend.py` (started via `pythonw`, which
  detaches and survives closing the browser tab or the window) could
  keep answering on port 5050 after "restarting," making it look like
  fixes weren't taking effect — `Start-Console.bat` now kills whatever's
  on port 5050 before starting a fresh one
- **Device-code/interactive sign-in timing out after ~2 minutes**
  ("Authentication timed out ... due to inactivity" / "User canceled
  authentication") even after the user successfully completes sign-in —
  root cause confirmed three ways: (1) the identical sign-in worked when
  run directly in an open PowerShell window instead of through the GUI,
  (2) no custom timeout exists anywhere in this project's own code
  (`Connect-Service.ps1` just calls `Connect-MgGraph` plain), (3) this
  tool's own docs
  (`docs/user/AUTHENTICATION.md`) describe `[Environment]::UserInteractive`
  becoming `$false` for exactly this kind of headless-launched process,
  for a different but related purpose. Fix attempted: launch the spawned
  `pwsh` with the `CREATE_NO_WINDOW` process creation flag instead of no
  console at all — **not yet confirmed working**, because the module
  import bug (this doc's main subject) has prevented any assessment run
  from getting far enough to test it. Worth re-testing once the import
  bug is fixed. App Registration + certificate auth (see
  `Grant-M365AssessConsent`) sidesteps this whole class of problem and is
  the fallback if the console fix doesn't hold up.

## Immediate next step

1. **Get the user's exact current error text.** They said "same issue"
   without pasting it — do not assume it's identical to before. Ask them
   to paste it verbatim, or send a screenshot.
2. In parallel, ask them to run (from the `gui` folder, in `pwsh`):
   ```powershell
   $m = Get-Module Microsoft.Graph.Authentication -ListAvailable
   $m | Format-List *
   Test-Path $m.Path
   Get-Content $m.Path -TotalCount 5
   ```
   This confirms whether the resolved `.Path` is actually a real, readable
   file from that exact PowerShell session — which the current code
   assumes but has not directly verified on the real machine.
3. Also worth checking `CompatiblePSEditions` in
   `Microsoft.Graph.Authentication`'s own manifest (via
   `$m.CompatiblePSEditions` on the object from step 2) — if it's
   `Desktop`-only, PowerShell 7 may refuse it for a reason unrelated to
   "found or not found," which would explain persisting past attempt 3.
4. If the module install itself turns out to be broken/incompatible, the
   clean fix is likely: `Install-Module Microsoft.Graph -Scope
   CurrentUser -Force` run directly inside `pwsh` (not through the GUI),
   which installs a PS7-native copy into PS7's own module folder,
   sidestepping the cross-version folder question entirely. This has not
   been tried or suggested to the user yet.

## Communication style — hard requirement

The user has repeatedly and explicitly asked for **very simple, plain,
non-technical language** ("i dont understand what you are doing your
language is so complicated"). They are a security consultant, not a
developer. Avoid jargon in anything shown to them; save technical detail
for code comments and commit messages, not chat replies. They also
strongly prefer single, copy-pasteable commands over multi-step
sequences, and get frustrated (understandably, at this point) by fixes
that turn out not to have worked — verify anything possible in a sandbox
*before* telling them to try it, the way every fix above but the current
one was handled.
