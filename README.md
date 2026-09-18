# Auracular

**AUR Heuristic Threat Model**: a heuristic scanner that scores AUR packages so you know which ones deserve a manual look before (or after) installing.

**Status: early, personal project, actively developed.** I'm not presenting this as a finished or professionally audited security product, see "About this project" below.

```
    \    |   |  _ \     \     ___| |   | |        \     _ \
   _ \   |   | |   |   _ \   |     |   | |       _ \   |   |
  ___ \  |   | __ <   ___ \  |     |   | |      ___ \  __ <
_/    _\\___/ _| \_\_/    _\\____|\___/ _____|_/    _\_| \_\

                ◉  AUR Heuristic Threat Model  ◉
```

## What it does

The AUR (Arch User Repository) has no review process. Anyone can submit a `PKGBUILD`, and packages can sit unmaintained for years before a new "maintainer" quietly takes one over. Auracular doesn't replace reading the `PKGBUILD` yourself, it gives you a fast, automated first pass so you know *where* to look closer, by checking:

- **AUR metadata**: votes, popularity, package age, maintainer status, out-of-date flags
- **PKGBUILD text**: a scan for known-risky patterns (curl/wget piped into a shell, base64-decoded blobs, `eval` on downloaded output, setuid bits, sudoers/SSH-key tampering, downloads from raw IPs or pastebin-style hosts). The text is read with a small static shell parser that handles common bash syntax (quotes, comments, line continuations, command substitutions, `case` statements and heredocs, including heredocs fed to a shell), so the usual ways of hiding a command behind a `#` or an odd line split are caught. It doesn't understand all of bash, so as a backstop the most serious patterns are also checked against the plain text. A match that only shows up there (for example inside a comment) is reported as "check this by hand" and keeps the package out of LOW RISK.
- **Install scripts and other root-run files**: the package's `install=` script is found from the `PKGBUILD` and `.SRCINFO` (whatever it's named, including split packages) and scanned with the same patterns, along with any `.install`, `.hook`, `.service` and `.timer` files in the package repo. Findings in these files weigh more, since they can run as root. If a declared install script can't be read or its name can't be worked out, that's reported and lowers the score instead of passing silently.
- **Git commit history**: detects the "dormant package quietly taken over by a new maintainer" shape, a long gap in commits followed by a new identity picking it back up
- **Typosquatting**: flags names that closely resemble official repo packages

Each package gets a 0-100 score and a risk bucket (LOW RISK / REVIEW / CAUTION / HIGH RISK), sorted riskiest first.

**A high score is not a verdict.** It means fewer automated red flags, not "proven safe." A low score doesn't necessarily mean malicious, it means a human should look at this before trusting it. Auracular is a triage tool, not a substitute for judgment.

## Usage

```
auracular                        # no args = score every installed AUR package
auracular pkgname [pkgname2 ...] # check specific package(s), e.g. before installing
auracular -v                     # also show matched PKGBUILD lines
auracular --no-history           # skip cloning the package repo (faster, but see below)
auracular --explain pkgname      # plain-English, annotated PKGBUILD walkthrough
```

`--explain` is worth calling out on its own: it walks through a package's `source=()`, dependencies, and the lines of `verify()`/`prepare()`/`pkgver()`/`build()`/`check()`/`package()` with a best-effort plain-English annotation, plus a short primer on how to read a `PKGBUILD` yourself. Finding where each function ends relies on the same best-effort parser: when it can tell it lost track, it says so and shows everything after the function's start, but unusual syntax could still make it cut a function short, so treat the walkthrough as a reading aid rather than a complete copy. The goal is to make that habit approachable, not to replace it.

### What each mode reads

| | PKGBUILD | Install scripts and `.hook`/`.service`/`.timer` files | Commit history (handoff check) |
|---|---|---|---|
| Default | scanned | scanned, for files that pass the safety checks below | checked |
| `--no-history` | scanned | **not read** (the report says so, and a declared install script lowers the score) | skipped |
| `--explain` | walked through and scanned | **not read**; links are printed only for install scripts it can resolve from the PKGBUILD | not checked |

The default mode clones each package's AUR git repo to get the install scripts and history, so it's the only mode that attempts all three checks. For safety it won't read a file from the clone that is a symlink, points outside the repo, isn't a regular file, or is over 1MB. A declared install script skipped for one of those reasons is reported as unread; other skipped files (a `.service` symlink, say) currently aren't called out individually.

### Requirements

- Python 3.9 or newer (developed and tested on 3.14)
- `pacman` and `git` on `PATH` (Arch Linux or an Arch-based distro)
- Network access (AUR RPC + AUR git repos)

### Install

```
git clone https://github.com/IgnisNatura/auracular.git
cd auracular
./auracular --help
```

No dependencies outside the Python standard library. Symlink or copy `auracular` onto your `PATH` if you want it available globally.

### Running the tests

```
python3 -m unittest discover -s tests -v
```

The tests run offline. They use small hand-written `PKGBUILD` examples, mocked AUR responses and throwaway local git repos, and never execute any package code. Many of them come straight from outside reviews of this project, kept so a later change can't quietly bring an old bug back.

## Limitations

- The red-flag patterns are a fixed, hand-picked list. They catch careless and copy-pasted malware, not a determined attacker who knows this tool exists and works around it (e.g. splitting a command across variables). A `PKGBUILD` can be malicious without tripping any of them.
- The maintainer-handoff detection is a heuristic on commit timing and identity similarity, not a positive identification of anything. Legitimate co-maintenance changes can occasionally trigger it, and never seeing a flag doesn't rule out a quieter takeover.
- It reads the `PKGBUILD` as text and never executes it. That's deliberate, but it also means anything only visible at build/run time is outside its reach. The shell parser covers common bash syntax, not all of it, and code that's assembled while the script runs (like `eval` on a built-up string, which is flagged on its own) can't be followed.
- Working out which install script a package uses is best-effort. It only fills in a variable when that variable is set in exactly one place in the whole file, that place is one of the plain assignments in the `PKGBUILD` header, and it comes before the line using it. That covers the usual `install=$pkgname.install` style, but it deliberately gives up on anything else: a value set in a branch, in a subshell, inside a function, or in more than one place is left unresolved, because reading the file does not establish which value actually reaches `install=`. Anything it can't resolve, or doesn't recognize as a plain `install=` line, is reported as a warning, and that warning stands even when a plausible-looking file was found and scanned. That will occasionally warn on an honest package, which is the intended trade-off: a guessed filename is not the same as a verified one.
- Install scripts and `.hook`/`.service`/`.timer` findings are weighted as if they run as root, based only on the file type. That's true for install scripts but not necessarily for every service or timer file.
- With no arguments it checks your installed AUR packages by name, but it scans each package's *current* recipe on the AUR, not the exact version you installed.
- It complements reading the `PKGBUILD` yourself. It doesn't replace it.

### Known gaps (roadmap, not yet implemented)

- No checksum analysis. `sha256sums=(SKIP SKIP)` on remote sources means nothing pins the downloaded bytes, and this isn't currently flagged.
- No check for a package's `provides=`/`replaces=` hijacking an official repo package name on upgrade.
- The typosquat check only compares against official repo packages, not other popular AUR packages (so an AUR-vs-AUR squat like `yay-bim` vs `yay-bin` is invisible), and misses some short-name squats.
- `KNOWN_HOSTS` (used by `--explain`'s source-host check) is a short allowlist and will mislabel plenty of legitimate vendor download hosts as "unrecognized." Treat that specific check as low-confidence for now.
- `--explain`'s dependency and `source=()` listing still uses simpler parsing than the scanner and can mis-read an array that contains a nested `$(...)` command substitution.
- A package that isn't found on the AUR (removed, renamed, or moved to the official repos) scores 0 / HIGH RISK, the same as a truly dangerous one. It should get its own "couldn't verify" result instead.
- Exit codes don't yet tell "scan finished" apart from "something failed along the way" (for example, if `pacman` or the AUR can't be reached), so scripts calling Auracular can't rely on them.

## About this project

I run Arch, and the real AUR malware incidents (packages sitting dormant for years, then quietly taken over by a new "maintainer" who swaps in a PKGBUILD that pulls and runs a remote payload) worried me enough that I wanted something to flag that risk before I installed something myself. That's where this started: a personal tool for my own system.

Pretty quickly after seeing it work, though, I wanted more than that. If it helps other people too, even better, and I wanted an ongoing project I could keep building on as I keep learning to code. So this is meant to grow, not stay a one-off script.

It's still early, and it'll keep changing as I improve it and as my own Python skills improve. The "Known gaps" section above and the issue tracker are where that gets tracked.

AI played a role in scripting this application, but it's been heavily modified and reviewed by me since. I designed the heuristics, decided what an actual AUR compromise looks like and what should get checked for, and tested it against real AUR packages myself. I'm mentioning the AI involvement up front rather than letting it surface later, since this is a security-adjacent tool people might use to help decide what to trust.

Either way, treat the source the same way Auracular asks you to treat a `PKGBUILD`: it's readable, it's not long, and you should look at it yourself rather than taking my word for what it does. Issues and PRs pointing out logic gaps, missed patterns, or just cleaner ways to write something are welcome. That's a big part of why I'm sharing this while it's still early instead of waiting until it feels finished.

## No warranty

Auracular is provided as is, with no guarantee that it will catch a malicious package or that its scores are correct. A LOW RISK result can still be wrong. You're responsible for what you choose to install, and the author isn't liable for any damage or loss from using this tool or relying on its results. See the [LICENSE](LICENSE) for the full terms.

## License

[FSL-1.1-MIT](LICENSE) (Functional Source License). Free to use, modify, and redistribute for any purpose that isn't a competing commercial product or service. Each release automatically converts to plain MIT two years after it's published, see the LICENSE file for the exact terms.
