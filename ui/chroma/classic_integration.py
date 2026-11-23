"""Optional ClassicWheel bridge for Classic chroma selection."""

from injection.classic import is_classic_game_mode, to_regular_skin_id
from utils.core.logging import get_logger

log = get_logger()


def handle_classic_chroma_selection(message_handler, payload: dict) -> bool:
    state = message_handler.shared_state
    if not is_classic_game_mode(getattr(state, "current_game_mode", None)):
        return False

    selection_handler = getattr(message_handler, "_handle_classic_skin_selection", None)
    champion_id = getattr(state, "classic_champion_id", None)
    default_skin_id = getattr(state, "classic_default_skin_id", None)
    catalog = getattr(state, "classic_catalog_skin_ids", None)
    if not callable(selection_handler) or not champion_id or not catalog:
        return False

    try:
        skin_id = int(to_regular_skin_id(payload.get("skinId")) or 0)
        chroma_id = int(to_regular_skin_id(payload.get("chromaId")) or 0)
    except (TypeError, ValueError):
        return True
    if chroma_id not in (0, skin_id):
        log.warning(
            "[CLASSIC:CHROMA] Rejected mismatched skin=%s chroma=%s",
            skin_id,
            chroma_id,
        )
        return True

    selection = dict(payload)
    selection.update(
        {
            "type": "classic-skin-selection",
            "schemaVersion": 1,
            "mode": "JADE",
            "championId": champion_id,
            "defaultSkinId": default_skin_id,
            "skinId": skin_id,
            "catalog": [{"id": value} for value in catalog],
            "skin": payload.get("chromaName") or f"skin_{skin_id}",
            "source": "classic-chroma",
            "userInitiated": True,
            "selectionGeneration": getattr(state, "classic_selection_generation", 0)
            + 1,
        }
    )
    selection_handler(selection)
    if state.last_hovered_skin_id != skin_id:
        return True

    state.selected_chroma_id = skin_id if chroma_id else None
    log.info(
        "[CLASSIC:CHROMA] selected target=%s chroma=%s owned=%s",
        skin_id,
        state.selected_chroma_id,
        getattr(state, "classic_selected_skin_owned", False),
    )
    message_handler.broadcaster.broadcast_chroma_state()
    return True
