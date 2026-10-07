import re
import unittest
from pathlib import Path

from pengu.core import skin_monitor

PLUGINS = Path(__file__).resolve().parents[2] / 'Pengu Loader' / 'plugins'


class BridgePortRangeTests(unittest.TestCase):
    """The plugins only look for Rose on 50000-50010 while the bridge could take
    any of 100 ports: on a later one they were loaded but never connected"""

    def test_plugins_search_every_port_the_bridge_can_take(self):
        last_port = skin_monitor.BRIDGE_FIRST_PORT + skin_monitor.BRIDGE_PORT_COUNT - 1
        for plugin in ('ROSE-SkinMonitor', 'ROSE-PartyMode'):
            source = (PLUGINS / plugin / 'index.js').read_text(encoding='utf-8')
            with self.subTest(plugin=plugin):
                start = re.search(r'DISCOVERY_START_PORT = (\d+);', source)
                end = re.search(r'DISCOVERY_END_PORT = (\d+);', source)
                self.assertEqual(int(start.group(1)), skin_monitor.BRIDGE_FIRST_PORT)
                self.assertEqual(int(end.group(1)), last_port)


if __name__ == '__main__':
    unittest.main()
