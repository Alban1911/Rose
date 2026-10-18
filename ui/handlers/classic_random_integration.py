"""Optional ClassicWheel lifecycle hooks for Classic randomization."""

from injection.classic import (
    is_classic_champion_id,
    is_classic_game_mode,
    to_regular_skin_id,
)
from ui.handlers.randomization_handler import (
    RandomizationHandler,
    clear_random_runtime,
)
from utils.core.random_preferences import is_random_enabled_for_champion


def reset_classic_random_runtime(state, champion_id: int) -> None:
    if not (
        is_classic_game_mode(getattr(state, "current_game_mode", None))
        or is_classic_champion_id(champion_id)
    ):
        return
    if (
        state.random_mode_active
        or state.random_skin_id is not None
        or state.random_skin_name is not None
    ):
        clear_random_runtime(state)


def restore_classic_random_from_catalog(state, skin_scraper, broadcaster) -> bool:
    champion_id = getattr(state, "classic_champion_id", None)
    if not champion_id:
        return False

    catalog_ids = getattr(state, "classic_catalog_skin_ids", set())
    if is_random_enabled_for_champion(champion_id):
        random_target = int(to_regular_skin_id(state.random_skin_id) or 0)
        random_active = bool(state.random_mode_active and random_target in catalog_ids)
        if state.random_mode_active and not random_active:
            clear_random_runtime(state)
        if not random_active:
            random_active = RandomizationHandler(state, skin_scraper).activate_persisted()
        if random_active:
            if state.historic_mode_active or state.historic_skin_id is not None:
                state.historic_mode_active = False
                state.historic_skin_id = None
                broadcaster.broadcast_historic_state()
            state.historic_first_detection_done = True
            return True

    try:
        from utils.core.historic import get_historic_skin_for_champion

        historic_skin_id = get_historic_skin_for_champion(champion_id, "classic")
    except (ImportError, TypeError, ValueError):
        historic_skin_id = None
    if (
        not state.historic_first_detection_done
        and isinstance(historic_skin_id, int)
        and historic_skin_id in catalog_ids
    ):
        state.historic_mode_active = True
        state.historic_skin_id = historic_skin_id
        broadcaster.broadcast_historic_state()
    state.historic_first_detection_done = True
    return False
