#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""What an injection will install, so the loadout countdown can stage it.

LTK Manager's patcher only overlays a game the client creates after its scan
started, and the client creates the game about a second after the injection
begins: too soon to install the mods and start the patcher then. So while the
countdown runs, InjectionManager.stage_plan installs what the injection will
install and starts the patcher; the injection then finds the same mods in
place (mod_fingerprint) and the scan keeps running.

A plan lists the mods in the order the injection installs them. The trigger
builds it from the selection (InjectionTrigger.staging_plan), one path each:

- a skin (SkinInjector.inject_skin): SkinStep, then friends' skins
- a custom skin mod or map/font/announcer/other mods
  (InjectionTrigger._run_custom_mod_injection): the carrier skin, the custom
  mod, the other mods, the loading screen name, then friends' skins
- friends' skins alone (InjectionManager.inject_party_skins_only)

A saved mod LTK Manager holds is planned as its LTK reference: nothing is
linked for it, and the injection switches its entry on (injection.core.mod_source).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, NamedTuple, Optional, Tuple

from utils.core.junction import is_junction
from utils.core.logging import get_logger

from ..loadingname.loading_name import build as build_loading_name
from ..mods.mod_manager import ModManager
from .mod_source import ModSource, loading_name_mods

log = get_logger()

# The label of a plan that only holds friends' skins: what
# InjectionManager.inject_party_skins_only passes to cancel_staging(keep=...)
PARTY_SKINS_LABEL = "party skins"


@dataclass(frozen=True)
class SkinStep:
    """A skin and its loading screen name mod (SkinInjector.prepare_skin_mods)."""
    skin_name: str
    champion_name: Optional[str]
    champion_id: Optional[int]
    classic: bool


@dataclass(frozen=True)
class CarrierStep:
    """The skin archive a custom mod (or the other mods of an unowned skin) rides on."""
    skin_name: str
    champion_name: Optional[str]
    champion_id: Optional[int]


@dataclass(frozen=True)
class ModStep(ModSource):
    """A saved mod: the custom skin mod, a map, font, announcer or other mod."""
    # The custom skin mod: without it the injection installs nothing
    required: bool = False


@dataclass(frozen=True)
class LoadingNameStep:
    """The loading screen name of the custom mod's skin (else the carrier's)."""
    skin_id: int


@dataclass(frozen=True)
class PartyStep:
    """A friend's skin (party.integration.injection_hook.prepare_peer_skin)."""
    summoner_id: int
    summoner_name: str
    champion_id: int
    skin_id: int
    chroma_id: Optional[int]
    custom_mod_path: Optional[str]
    classic: bool


class StagePlan(NamedTuple):
    """The mods an injection installs, in its order.

    *label* is what that injection passes to cancel_staging(keep=...): the
    injection name, or PARTY_SKINS_LABEL.
    """
    label: str
    steps: Tuple[object, ...]


def skin_plan(skin_name: str, champion_name: Optional[str] = None, champion_id: Optional[int] = None,
              classic: bool = False, party: Tuple[PartyStep, ...] = ()) -> StagePlan:
    """The plan of a skin injection (SkinInjector.inject_skin)."""
    return StagePlan(skin_name, (SkinStep(skin_name, champion_name or None, champion_id, classic),) + tuple(party))


def describe(plan: StagePlan) -> str:
    """What the plan installs besides its label, for the logs ("" when nothing)."""
    extras = []
    mods = sum(1 for step in plan.steps if isinstance(step, ModStep))
    friends = sum(1 for step in plan.steps if isinstance(step, PartyStep))
    if mods:
        extras.append(f"{mods} mod{'s' if mods > 1 else ''}")
    if friends and plan.label != PARTY_SKINS_LABEL:
        extras.append(f"{friends} friend skin{'s' if friends > 1 else ''}")
    return f" + {' + '.join(extras)}" if extras else ""


def prepare_plan(injector, plan: StagePlan, target_dir: Path) -> Optional[List[str]]:
    """Prepare the plan's mods in *target_dir*, as the injection prepares them
    in its mods folder (the same files, so the same fingerprints).

    Returns their folder names in the injection's order, or None when the
    injection would install nothing (it gives up without the skin, the
    carrier or the custom mod).
    """
    target_dir = Path(target_dir)
    names: List[str] = []
    custom_folder: Optional[str] = None
    carrier_folder: Optional[str] = None
    for step in plan.steps:
        if isinstance(step, SkinStep):
            prepared = injector.prepare_skin_mods(
                step.skin_name, target_dir, champion_name=step.champion_name,
                champion_id=step.champion_id, classic=step.classic, report=False,
            )
            if not prepared:
                return None
            names.extend(prepared)
        elif isinstance(step, CarrierStep):
            folder = _prepare_carrier(injector, step, target_dir)
            if folder is None:
                return None
            carrier_folder = folder
            names.append(folder)
        elif isinstance(step, ModStep):
            folder = step.put(target_dir)
            if folder is None:
                log.debug(f"[STAGE] Mod not available: {step.source}")
                if step.required:
                    return None
                continue
            if step.required:
                custom_folder = folder
            names.append(folder)
        elif isinstance(step, LoadingNameStep):
            skin_folder = custom_folder or carrier_folder
            if skin_folder:
                mods = [mod for mod in plan.steps if isinstance(mod, ModStep)]
                skin, others = loading_name_mods(target_dir, skin_folder, names, mods)
                loading_name = build_loading_name(injector.game_dir, target_dir, skin, step.skin_id, other_mods=others)
                if loading_name:
                    names.append(loading_name)
        elif isinstance(step, PartyStep):
            folder = _prepare_party_skin(injector, step, target_dir)
            if folder:
                names.append(folder)
    return names or None


def _prepare_carrier(injector, step: CarrierStep, target_dir: Path) -> Optional[str]:
    """Link the carrier skin archive (InjectionTrigger._run_custom_mod_injection)."""
    zp = injector._resolve_zip(
        step.skin_name, skin_name=step.skin_name, champion_name=step.champion_name,
        champion_id=step.champion_id,
    )
    if not zp or not Path(zp).exists():
        log.debug(f"[STAGE] Skin carrier archive not found: {step.skin_name}")
        return None
    folder = ModManager(target_dir).link_archive(Path(zp))
    if not folder or not (folder.exists() or is_junction(folder)):
        return None
    return folder.name


def _prepare_party_skin(injector, step: PartyStep, target_dir: Path) -> Optional[str]:
    from party.discovery.skin_collector import PartySkinData
    from party.integration.injection_hook import prepare_peer_skin

    skin_data = PartySkinData(
        summoner_id=step.summoner_id,
        summoner_name=step.summoner_name,
        champion_id=step.champion_id,
        skin_id=step.skin_id,
        chroma_id=step.chroma_id,
        custom_mod_path=step.custom_mod_path,
    )
    try:
        return prepare_peer_skin(skin_data, injector, classic=step.classic, mods_dir=target_dir)
    except Exception as e:
        log.debug(f"[STAGE] Could not prepare {step.summoner_name}'s skin: {e}")
        return None
