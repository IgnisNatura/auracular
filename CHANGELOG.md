# Changelog

Notable changes to Auracular. Dates are the date the work landed.

## 0.2.0 - 2026-09-18

The first update since the initial release. The theme of this one is not
finding more threats, it is being honest about what was actually checked. A
scanner that says "looks fine" when it could not read the important file is
worse than no scanner, because you act on it. Most of the work below exists
to close gaps of that kind.

Much of it came out of adversarial testing: packages were crafted to obfuscate
what they actually did and slip past the scanner, hiding code that would run as
root at install time. Every gap they found is fixed here and covered by a test.

### Install scripts are actually found now

An install script runs as root when you install or upgrade a package, so it
is the single most important thing to read. Previously Auracular only looked
at files whose names ended in `.install`, `.hook`, `.service` or `.timer`.
`makepkg` accepts any filename, so an install script named anything else was
never read and never mentioned.

- Install scripts are now found from the `install=` declaration itself, in
  both the `PKGBUILD` and the `.SRCINFO`, whatever the file is called.
- Split packages are covered, including per-package `install=` overrides.
- Simple variable names such as `install=$pkgname.install` are resolved.
  Resolution is deliberately narrow and refuses to guess: see "Coverage" below.

### A real shell parser

Scanning used to work line by line. A `PKGBUILD` is a Bash script, so that
missed anything spread across the constructs Bash actually allows.

- Added a static shell lexer shared by the scanner, install script discovery,
  and `--explain`. It never executes anything.
- Red flags are now found inside here-documents, backticks, `case` statements,
  braced parameter expansions, `coproc` blocks, and commands split across line
  continuations.
- Fewer false alarms in the other direction: the parser knows what is a
  comment and what is inside quotes.
- A raw-text backstop still runs over the whole file, so a parser gap warns
  instead of passing silently. One known trade-off: a comment that mentions a
  download-and-run command produces a "check by hand" note rather than nothing.

### Coverage is reported honestly

- If a declared install script cannot be read, or its name cannot be worked
  out, that is reported, lowers the score, and prevents a LOW RISK result.
- Any line that might set `install=` in a form Auracular does not fully
  understand is counted and reported rather than ignored.
- A file that was scanned is tracked separately from one that was merely
  found, so reading a harmless file never clears a warning about a different
  file that was not read.
- Variable resolution only credits a variable that is set in exactly one place
  in the whole file, in the plain assignments at the top of the `PKGBUILD`,
  before the line that uses it. Anything else is left unresolved and warned
  about. This will occasionally warn on an honest package, which is the
  intended trade-off: a guessed filename is not a verified one.

### Correctness and robustness

- Git history is parsed with NUL separators, so a `|` in an author's name can
  no longer silently drop commits from the maintainer handoff check. Malformed
  history is reported as unavailable instead of analyzed in part.
- AUR RPC responses are type and range checked. Malformed or null data now
  reports as unavailable instead of crashing or being read as "package not
  found".
- Numeric `setuid`/`setgid` detection was missing two permission digits, so
  `chmod 5755` went unflagged while `chmod 4755` was caught. Both are caught now.
- Files are read with symlink, containment and size limits, so a package
  cannot point the scanner at a file outside its own repository.
- `source=` entries with variable-built or malformed hosts are reported rather
  than raising an error.

### Tests

- Added a regression suite: 129 tests, standard library only, no new
  dependencies. Run with `python3 -m unittest discover -s tests`.
- The initial release had no automated tests.

### Documentation

- The README now describes what each mode actually reads, states the limits of
  the parser and of variable resolution, and includes a plain language section
  on what this tool does not promise.

## 0.1.0 - 2026-09-15

Initial public release: AUR metadata scoring, a red flag scan of the
`PKGBUILD`, a typosquat check against the official repositories, a maintainer
handoff check from the git history, and `--explain` for an annotated,
plain English walkthrough of a `PKGBUILD`.
