# Classic Mode Support

## Overview

Classic Mode support is implemented as an isolated feature for JADE games. The
regular game-mode flow and its existing plug-ins remain unchanged. Classic-only
state, persistence, resource resolution, and client plug-ins are kept separate
so that a Classic selection cannot leak into a regular match.

## Mode Detection

Rose normalizes the active mode from live LCU session data. `gameMode == JADE`
is the strongest signal, with queue `3260` and map `453` used as compatibility
fallbacks. The normalized mode is stored centrally and is cleared when the
champ-select session ends or contradicting session data is received.

## ID and Carrier Model

Classic Mode exposes several IDs for the same visual choice:

- The prime champion ID identifies the regular champion.
- The mode champion ID identifies the Classic entity.
- The raw LCU skin ID identifies the mode-native skin selection.
- The resource skin ID identifies the package in the Classic resource library.
- The visual skin ID identifies the regular skin being projected locally.

These ID domains are converted through `utils/core/classic_mode_ids.py` rather
than inferred at individual call sites.

Classic champions use different native carriers. Rose resolves a carrier from
the current LCU catalog when possible and falls back to the versioned matrix:

- Skin0 for champions without a Classic Skin301/302 carrier.
- Skin301 for the supported Skin301 champions.
- Skin302 for Kayle.

The carrier belongs to the current mode champion and remains the server-visible
selection throughout local projection.

## Selection and Ownership

Owned Classic skins continue through the official LCU selection path and are not
locally injected. For an unowned visual selection, Rose keeps the owned
mode-native carrier in LCU and stores the requested visual skin separately. The
unowned projected ID is never written to LCU.

Selection generations reject stale events during the final lock transition.
This prevents delayed UI events from replacing a newer selection or updating a
different champion.

## Classic Plug-ins

Classic controls are provided by separate plug-ins:

- `ROSE-ClassicWheel` provides the finite Classic skin carousel.
- `ROSE-ClassicChroma` provides Classic chroma selection and persistence.
- `ROSE-ClassicHistoric` provides isolated Classic history state and display.
- `ROSE-ClassicRandom` provides per-champion Classic randomization.

The regular plug-ins are not modified to contain Classic conditionals. Classic
controls clean themselves up when champ select ends and do not leave overlays or
state behind for the next match.

`ROSE-ClassicWheel` ports Catcat's validated JADE adapter for Riot's native
skin-card carousel. It is unrelated to `ROSE-CustomWheel`, which manages
third-party mods. The chroma, history, and random plug-ins port Catcat's
isolated JADE controls as Classic counterparts to Rose's regular features.
They preserve the corresponding behavior and bridge contracts, but they are
not source-level forks of the regular Rose plug-ins.

## Resource and Injection Flow

Classic packages are resolved only from the `classic/` resource directory. Rose
does not fall back to the regular `skins/` directory for a Classic selection.
The downloader and cleanup logic treat `skins/`, `classic/`, and `resources/`
as separate resource sets.

Classic packages may use a mode-native carrier while targeting a different
visual skin. The converted package therefore retains the required dependency
closure and redirects model, weapon, animation, VFX, and related asset links to
the correct carrier. Package preparation restores the native carrier before
launch and reuses Rose's existing overlay and injection path.

Rose uses [Alban1911/LeagueSkins](https://github.com/Alban1911/LeagueSkins)
as its default resource repository. Classic packages are read from that
repository's isolated `classic/` directory.

## Current Limitations

Classic Mode support is working end to end, but some edge cases may still need
follow-up validation across client versions and less common skin dependency
graphs. The resource changes are currently maintained separately from Rose and
can be proposed to the upstream resource repository in a later PR.
