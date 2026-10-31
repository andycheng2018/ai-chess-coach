import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server'))
import app
from tablet_access import TabletAccess, TABLET_HEADER, TABLET_ORIGIN

TOKEN='test-key-'+'x'*44


class TabletAccessTests(unittest.TestCase):
    def test_native_remote_access_needs_explicit_token_origin_and_private_address(self):
        access=TabletAccess(TOKEN)
        self.assertTrue(access.authorized('192.168.0.21',TABLET_ORIGIN,TOKEN))
        for address,origin,token in [('192.168.0.21',TABLET_ORIGIN,''),('192.168.0.21','https://evil.example',TOKEN),('8.8.8.8',TABLET_ORIGIN,TOKEN),('bad',TABLET_ORIGIN,TOKEN),('192.168.0.21',TABLET_ORIGIN,'é')]:
            self.assertFalse(access.authorized(address,origin,token))
        self.assertFalse(TabletAccess().authorized('192.168.0.21',TABLET_ORIGIN,TOKEN))

    def handler(self,address='192.168.0.21',token=TOKEN,origin=TABLET_ORIGIN):
        handler=object.__new__(app.Handler)
        handler.client_address=(address,1234)
        handler.server=SimpleNamespace(server_port=8765)
        handler.headers={'Host':'192.168.0.20:8765','Origin':origin,TABLET_HEADER:token}
        handler.path='/api/vbot/status'
        handler._send=Mock()
        return handler

    def test_paired_client_passes_existing_robot_gate_but_unpaired_lan_does_not(self):
        with patch.object(app,'tablet_access',TabletAccess(TOKEN)):
            paired=self.handler()
            self.assertTrue(paired._vbot_local_request())
            self.assertFalse(paired._tablet_api_denied())
            unpaired=self.handler(token='')
            self.assertFalse(unpaired._vbot_local_request())
            self.assertTrue(unpaired._tablet_api_denied())
            self.assertEqual(unpaired._send.call_args.args[0],403)

    def test_original_local_mac_controls_remain_available(self):
        with patch.object(app,'tablet_access',TabletAccess(TOKEN)):
            handler=self.handler(address='127.0.0.1',token='',origin='http://localhost:5173')
            handler.headers['Host']='127.0.0.1:8765'
            self.assertTrue(handler._vbot_local_request())
            self.assertFalse(handler._tablet_api_denied())

    def test_pairing_key_page_never_goes_to_lan_or_untrusted_host(self):
        remote=self.handler()
        self.assertFalse(remote._host_pairing_page_allowed())
        local=self.handler(address='127.0.0.1',origin='')
        local.headers['Host']='127.0.0.1:8765'
        self.assertTrue(local._host_pairing_page_allowed())
        local.headers['Host']='attacker.example'
        self.assertFalse(local._host_pairing_page_allowed())

    def test_pairing_page_contains_local_qr_without_third_party_scripts(self):
        page=TabletAccess(TOKEN,'http://192.168.0.20:8765').page().decode()
        self.assertIn('<svg',page)
        self.assertIn(TOKEN,page)
        self.assertNotIn('<script',page)

    def test_pairing_file_is_private_stable_and_not_a_symlink(self):
        spec=importlib.util.spec_from_file_location('tablet_launcher',ROOT/'scripts/tablet_backend.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'pairing.json'
            first=module.pairing_key(path)
            self.assertEqual(first,module.pairing_key(path))
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            link=Path(folder)/'link';link.symlink_to(path)
            with self.assertRaises(RuntimeError):module.pairing_key(link)


if __name__=='__main__':unittest.main()
