---
title: Code signing policy
nav_order: 12
---

# Code signing policy

Free code signing provided by [SignPath.io](https://about.signpath.io), certificate by [SignPath Foundation](https://signpath.org)

The Windows release of the desktop app, `pokeldn-windows-x64.zip` on the
[Releases](https://github.com/Decryptu/pokeldn/releases) page, carries an Authenticode signature on
the binaries built from this repository's source: `pokeldn.exe`, the PKHeX helper
`pokeldn-pkhex.exe` and the Unicorn library `unicorn.dll`. GitHub Actions builds them from a `v*` tag
of this repository ([release.yml](https://github.com/Decryptu/pokeldn/blob/main/.github/workflows/release.yml));
SignPath signs the files that build produced and nothing built elsewhere. The artifact configuration
is [.github/signpath/artifact-configuration.xml](https://github.com/Decryptu/pokeldn/blob/main/.github/signpath/artifact-configuration.xml).
Third-party files bundled unchanged keep their own publisher's signature or none.

## Team roles

| role | members |
|---|---|
| Committers and reviewers | [Decryptu](https://github.com/Decryptu) |
| Approvers | [Decryptu](https://github.com/Decryptu) |

Every signing request for a release is approved by hand. Contributions from other people reach the
repository only as pull requests a committer reviews.

## Privacy policy

This program will not transfer any information to other networked systems unless specifically
requested by the user or the person installing or operating it. The requests it makes:

| when | to | what is sent |
|---|---|---|
| at launch, while Settings, Updates is on (the default) | the GitHub API, and each installed plugin's update address | a request for the latest release; nothing about the player or their games |
| the player downloads radio firmware or event raid data | GitHub | a download request |
| the player uses Trade (Online) or the GTS | public Nostr relays ([Online trade](online.md)) | encrypted trade events, including the offered Pokemon |
| the player installs or updates a plugin, or browses a plugin source | the address of that plugin or source | a download request |

GitHub's privacy statement covers requests to GitHub. Each relay operator's own policy covers that
relay. The app sends no analytics and no crash reports.
