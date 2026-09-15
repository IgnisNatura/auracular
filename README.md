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
- **PKGBUILD text**: regex scan for known-risky patterns (curl/wget piped into a shell, base64-decoded blobs, `eval` on command substitution, setuid bits, sudoers/SSH-key tampering, downloads from raw IPs or pastebin-style hosts)
- **Git commit history**: detects the "dormant package quietly taken over by a new maintainer" shape, a long gap in commits followed by a new identity picking it back up
- **Typosquatting**: flags names that closely resemble official repo packages

Each package gets a 0-100 score and a risk bucket (LOW RISK / REVIEW / CAUTION / HIGH RISK), sorted riskiest first.

**A high score is not a verdict.** It means fewer automated red flags, not "proven safe." A low score doesn't necessarily mean malicious, it means a human should look at this before trusting it. Auracular is a triage tool, not a substitute for judgment.

## Usage

```
auracular                        # no args = score every installed AUR package
auracular pkgname [pkgname2 ...] # check specific package(s), e.g. before installing
auracular -v                     # also show matched PKGBUILD lines
auracular --no-history           # skip the git-clone handoff check (faster)
auracular --explain pkgname      # plain-English, annotated PKGBUILD walkthrough
```

`--explain` is worth calling out on its own: it walks through a package's `source=()`, dependencies, and every line of `prepare()`/`build()`/`check()`/`package()` with a best-effort plain-English annotation, plus a short primer on how to read a `PKGBUILD` yourself. The goal is to make that habit approachable, not to replace it.

### Requirements

- Python 3
- `pacman` and `git` on `PATH` (Arch Linux or an Arch-based distro)
- Network access (AUR RPC + AUR git repos)

### Install

```
git clone https://github.com/IgnisNatura/auracular.git
cd auracular
./auracular --help
```

No dependencies outside the Python standard library. Symlink or copy `auracular` onto your `PATH` if you want it available globally.

## Limitations

- The red-flag patterns are a fixed, hand-picked list. They catch careless and copy-pasted malware, not a determined attacker who knows this tool exists and works around it (e.g. splitting a command across variables). A `PKGBUILD` can be malicious without tripping any of them.
- The maintainer-handoff detection is a heuristic on commit timing and identity similarity, not a positive identification of anything. Legitimate co-maintenance changes can occasionally trigger it, and never seeing a flag doesn't rule out a quieter takeover.
- It reads the `PKGBUILD` as text and never executes it. That's deliberate, but it also means anything only visible at build/run time is outside its reach.
- `install=` hook files (`.install` scripts, which run as root at install/upgrade time) are flagged as present when history-fetching succeeds, but their *contents* aren't scored the way the PKGBUILD's are. Read them yourself when one is flagged, `--explain` prints the direct link.
- It complements reading the `PKGBUILD` yourself. It doesn't replace it.

### Known gaps (roadmap, not yet implemented)

- No checksum analysis. `sha256sums=(SKIP SKIP)` on remote sources means nothing pins the downloaded bytes, and this isn't currently flagged.
- No check for a package's `provides=`/`replaces=` hijacking an official repo package name on upgrade.
- The typosquat check only compares against official repo packages, not other popular AUR packages (so an AUR-vs-AUR squat like `yay-bim` vs `yay-bin` is invisible), and misses some short-name squats.
- `KNOWN_HOSTS` (used by `--explain`'s source-host check) is a short allowlist and will mislabel plenty of legitimate vendor download hosts as "unrecognized." Treat that specific check as low-confidence for now.
- `extract_array()` can mis-parse a `source=()` array that contains a nested `$(...)` command substitution.

## About this project

I run Arch, and the real AUR malware incidents (packages sitting dormant for years, then quietly taken over by a new "maintainer" who swaps in a PKGBUILD that pulls and runs a remote payload) worried me enough that I wanted something to flag that risk before I installed something myself. That's where this started: a personal tool for my own system.

Pretty quickly after seeing it work, though, I wanted more than that. If it helps other people too, even better, and I wanted an ongoing project I could keep building on as I keep learning to code. So this is meant to grow, not stay a one-off script.

It's still early, and it'll keep changing as I improve it and as my own Python skills improve. The "Known gaps" section above and the issue tracker are where that gets tracked.

AI played a role in scripting this application, but it's been heavily modified and reviewed by me since. I designed the heuristics, decided what an actual AUR compromise looks like and what should get checked for, and tested it against real AUR packages myself. I'm mentioning the AI involvement up front rather than letting it surface later, since this is a security-adjacent tool people might use to help decide what to trust.

Either way, treat the source the same way Auracular asks you to treat a `PKGBUILD`: it's readable, it's not long, and you should look at it yourself rather than taking my word for what it does. Issues and PRs pointing out logic gaps, missed patterns, or just cleaner ways to write something are welcome. That's a big part of why I'm sharing this while it's still early instead of waiting until it feels finished.

## License

[FSL-1.1-MIT](LICENSE) (Functional Source License). Free to use, modify, and redistribute for any purpose that isn't a competing commercial product or service. Each release automatically converts to plain MIT two years after it's published, see the LICENSE file for the exact terms.
