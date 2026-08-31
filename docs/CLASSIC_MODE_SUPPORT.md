# Classic Mode Support

## Overview

Classic Mode support is isolated to JADE sessions. Its catalog, projected
selection, history, random preference, chroma state, package lookup, and client
controls do not replace the regular-mode implementations. The regular chroma,
forms, history, and random plug-ins only add a lifecycle guard that removes
their controls while JADE is active and restores their normal behavior after
the session.

## Mode and ID Boundary

Rose derives Classic Mode from live LCU session data. `gameMode == JADE` is the
primary signal, with queue `3260` and map `453` retained as compatibility
fallbacks.

Inside Rose, champion and skin IDs match the external `classic/` resource tree,
for example champion `55` and skin `55301`. JADE's `600` prefix belongs only to
the LCU transport boundary: `60055` and `60055301` are normalized when read and
restored only when Rose must write a mode-native value back to LCU. Catalog,
history, randomization, package lookup, naming, and injection use resource IDs.

The active carrier is resolved from the live Classic catalog rather than from a
per-champion fallback table. Before an LCU write, Rose verifies that the carrier
belongs to the active champion and is present in the current pickable-skin
catalog.

## Native Carousel and Selection

`ROSE-ClassicWheel` adapts Riot's native JADE skin carousel. Riot's cards remain
responsible for layout, focus, animation, arrow interaction, and full champion-
select splash transitions. ClassicWheel supplies the Classic catalog, enforces
its finite boundaries, projects history or random targets through native
navigation, and publishes one normalized selection contract to the other
Classic controls.

Owned Classic skins continue through the official LCU selection path. For an
unowned target, Rose keeps a valid owned carrier as the server-visible LCU
selection and stores the requested visual target separately. Automatic
navigation may pass through owned cards to obtain the native splash transition,
but those intermediate cards are not accepted as user selections. The target
splash remains protected until real user navigation, a context exit, or an
explicit replacement target releases it.

Selection generations prevent delayed carousel or WebSocket events from
replacing a newer target during the final lock transition. Injection consumes
the accepted projected selection rather than inferring it again from transient
card state.

## Classic Plug-ins

Classic controls are separate plug-ins:

- `ROSE-ClassicWheel` provides the finite native carousel adapter and shared
  selection contract.
- `ROSE-ClassicChroma` renders variants from the Classic catalog and publishes
  Classic chroma selections.
- `ROSE-ClassicHistoric` restores and presents mode-scoped history.
- `ROSE-ClassicRandom` stores per-champion random state and presents its dice
  control and selected-card marker.

Classic randomization follows the regular-mode probability model: it selects a
parent skin first, then chooses between that parent and its eligible chromas.
The visual target is projected during the stable final-countdown window instead
of moving the carousel as soon as random mode is enabled.

Classic-specific Forms are not included because the current resource catalog
does not contain a confirmed target that requires the regular FormsWheel
behavior.

## Resource and Injection Flow

Classic packages resolve only from the isolated `classic/` resource directory;
Rose does not fall back to regular `skins/` packages for a Classic selection.
Parent skins and nested chroma packages use the same normalized resource IDs
published by ClassicWheel.

Before launching an unowned target, Rose restores the validated mode-native
carrier and reuses the existing overlay and injection pipeline. The projected
target, carrier, chroma, history state, selection generation, and final
injection ID are retained as separate values through this boundary.

Classic peer selections in Party Mode are normalized into the Classic resource
namespace before package lookup. This path has passed compilation checks but
has not received formal live-machine validation.

Rose uses [Alban1911/LeagueSkins](https://github.com/Alban1911/LeagueSkins) as
its default resource repository. Classic packages are read from that
repository's isolated `classic/` directory.

## Diagnostics

Classic browser messages use searchable `[CLASSIC:<AREA>]` tags and are routed
through the plug-in log bridge. Backend checkpoints cover catalog acceptance,
selection and chroma changes, history and random state, LCU carrier state, game
start identity, package resolution, and the final injection target. Regular-mode
messages retain their existing prefixes.

## Experimental Mod Components

The Classic third-party Mod source and backend contracts are included so the
mode-specific state model remains complete. `ROSE-ClassicMods` contains the
full selector and `ROSE-ClassicSkinSelector` contains the selected-card shortcut.
Their entry points are stored as `index.js_`, Pengu Loader's native disabled
format, so neither Classic control is loaded or shown by default.

Classic and regular Mod history use separate persistence scopes. Active skin,
map, font, announcer, UI, voiceover, loading-screen, VFX, SFX, and other Mod
selections are discarded before they can cross the mode boundary. The regular
CustomWheel is also hidden during JADE sessions.

Full Classic Mod loading remains experimental and has not received formal
live-machine validation. The disabled entry points must not be enabled until
the relevant package categories and their Classic carrier behavior have been
validated.

`ROSE-SettingsPanel` integration for Classic skin Mods is also deferred. The
regular `ROSE-CustomWheel`, `ROSE-CustomSkinSelector`, and SettingsPanel code
remain available for regular game modes.
