import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pengu.communication.broadcaster import Broadcaster, custom_mod_state_payload
from pengu.communication.message_handler import MessageHandler


SELECTED_MOD = {
    "mod_name": "Neon Talon",
    "display_name": "  Neon  ",
    "skin_id": 91004,
    "champion_id": 91,
    "relative_path": "skins/91004/Neon Talon",
    "target_skin_ids": [91004, "91005", 0, -3],
}


class CustomModStatePayloadTests(unittest.TestCase):
    def test_a_selected_mod(self):
        payload = custom_mod_state_payload(SELECTED_MOD)
        self.assertEqual(payload["type"], "custom-mod-state")
        self.assertTrue(payload["active"])
        self.assertEqual(payload["modName"], "Neon Talon")
        self.assertEqual(payload["displayName"], "Neon")
        self.assertEqual(payload["skinId"], 91004)
        self.assertEqual(payload["championId"], 91)
        self.assertEqual(payload["relativePath"], "skins/91004/Neon Talon")
        self.assertEqual(payload["targetSkinIds"], [91004, 91005])

    def test_no_selected_mod(self):
        payload = custom_mod_state_payload(None)
        self.assertFalse(payload["active"])
        self.assertIsNone(payload["modName"])
        self.assertIsNone(payload["relativePath"])
        self.assertEqual(payload["targetSkinIds"], [])

    def test_a_blank_display_name_is_left_out(self):
        payload = custom_mod_state_payload({**SELECTED_MOD, "display_name": "   "})
        self.assertIsNone(payload["displayName"])

    def test_unreadable_targets_are_left_out(self):
        payload = custom_mod_state_payload({**SELECTED_MOD, "target_skin_ids": ["x"]})
        self.assertEqual(payload["targetSkinIds"], [])

    def test_missing_targets(self):
        payload = custom_mod_state_payload({**SELECTED_MOD, "target_skin_ids": None})
        self.assertEqual(payload["targetSkinIds"], [])

    def test_an_empty_selection_is_still_a_selection(self):
        payload = custom_mod_state_payload({})
        self.assertTrue(payload["active"])
        self.assertIsNone(payload["relativePath"])


class BroadcastCustomModStateTests(unittest.TestCase):
    def test_the_broadcast_sends_the_payload_for_the_selected_mod(self):
        broadcaster = Broadcaster.__new__(Broadcaster)
        broadcaster.websocket_server = SimpleNamespace(loop=object(), connections={object()})
        broadcaster.shared_state = SimpleNamespace(selected_custom_mod=dict(SELECTED_MOD))
        sent = []
        with patch.object(Broadcaster, "_send_message", side_effect=sent.append):
            broadcaster.broadcast_custom_mod_state()
        self.assertEqual(len(sent), 1)
        message = json.loads(sent[0])
        expected = custom_mod_state_payload(SELECTED_MOD)
        message.pop("timestamp")
        expected.pop("timestamp")
        self.assertEqual(message, expected)


class SkinModsResponseTests(unittest.TestCase):
    """ROSE-CustomSlots forgets the selection on an unlock or a reload; the
    mods response gives it back so the slot and the splash match Rose"""

    def _response(self, selected_custom_mod):
        handler = MessageHandler.__new__(MessageHandler)
        handler.shared_state = SimpleNamespace(selected_custom_mod=selected_custom_mod)
        handler.mod_storage = SimpleNamespace(
            mods_root=Path("mods"),
            list_mods_for_champion=lambda champion_id: [],
        )
        handler.skin_scraper = None
        handler.port = 50000
        sent = []
        with patch.object(MessageHandler, "_send_response", side_effect=sent.append), \
                patch("pengu.communication.message_handler.get_config_option", return_value="false"), \
                patch("utils.core.historic.get_historic_skin_for_champion", return_value=None):
            handler._handle_request_skin_mods({"championId": 91, "skinId": 91004})
        self.assertEqual(len(sent), 1)
        return json.loads(sent[0])

    def test_the_response_carries_the_selected_mod(self):
        response = self._response(dict(SELECTED_MOD))
        self.assertEqual(response["type"], "skin-mods-response")
        state = response["customModState"]
        self.assertTrue(state["active"])
        self.assertEqual(state["relativePath"], "skins/91004/Neon Talon")
        self.assertEqual(state["targetSkinIds"], [91004, 91005])

    def test_the_response_says_when_no_mod_is_selected(self):
        response = self._response(None)
        self.assertFalse(response["customModState"]["active"])


if __name__ == "__main__":
    unittest.main()
