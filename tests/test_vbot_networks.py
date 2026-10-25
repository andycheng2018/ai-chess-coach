"""Network recognition/memory and connection lifecycle. No live network/robot use."""
import copy,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from vbot_networks import NetworkBook,detect_network,network_identity,normalize_target
from vbot_demo import VbotDemo,ssh_command,check_robot
FP='SHA256:'+'a'*43

def net(ip='192.168.0.191',gateway='192.168.0.1',mac='aa:bb:cc:dd:ee:ff',ssid=None):
    return network_identity(interface='en0',local_ip=ip,netmask='0xffffff00',gateway=gateway,gateway_mac=mac,ssid=ssid)

class NetworkBookTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'networks.json';self.network=net()
        self.detector=Mock(side_effect=lambda:dict(self.network))
        self.book=NetworkBook(self.path,detector=self.detector)
    def test_router_identity_survives_mac_dhcp_change_and_ssid_redaction(self):
        self.assertEqual(net()['id'],net(ip='192.168.0.75',ssid='Stone')['id'])
        self.assertNotEqual(net()['id'],net(mac='11:22:33:44:55:66')['id'])
        self.assertNotEqual(net()['id'],net(ip='192.168.1.23',gateway='192.168.1.1')['id'])
    def test_hotspots_with_same_subnet_remain_distinct(self):
        rich=net(ip='172.20.10.4',gateway='172.20.10.1',mac='00:11:22:33:44:55')
        mine=net(ip='172.20.10.4',gateway='172.20.10.1',mac='66:77:88:99:aa:bb')
        self.assertNotEqual(rich['id'],mine['id'])
        self.assertIsNone(net(mac=None)['id'])  # never match a subnet alone
    def test_detector_only_reads_route_interface_wifi_name_and_cached_router(self):
        calls=[]
        def run(argv,**kw):
            calls.append(argv)
            text={'route':'gateway: 192.168.0.1\ninterface: en0',
                  'ifconfig':'inet 192.168.0.191 netmask 0xffffff00 broadcast 192.168.0.255',
                  'networksetup':'You are not associated with an AirPort network.',
                  'arp':'? (192.168.0.1) at a:b:c:d:e:f on en0 ifscope [ethernet]'}[Path(argv[0]).name]
            return type('Result',(),{'returncode':0,'stdout':text})()
        result=detect_network(run=run)
        self.assertEqual(result['gatewayMac'],'0a:0b:0c:0d:0e:0f');self.assertIsNone(result['ssid'])
        self.assertEqual([Path(c[0]).name for c in calls],['route','ifconfig','networksetup','arp'])
        self.assertEqual(calls[-1],['/usr/sbin/arp','-n','192.168.0.1'])
    def test_vpn_unknown_or_failed_network_detection_never_guesses(self):
        run=Mock(return_value=type('R',(),{'returncode':0,'stdout':'gateway: 10.0.0.1\ninterface: utun4'})())
        self.assertIsNone(detect_network(run=run)['id']);self.assertEqual(run.call_count,1)
        run.side_effect=PermissionError()
        self.assertIsNone(detect_network(run=run)['id'])
    def test_atomic_persistence_and_multiple_addresses_with_latest_selection(self):
        self.book.remember('192.168.0.170',label='Home',fingerprint=FP,verified=True)
        self.book.remember('192.168.0.171')
        snap=NetworkBook(self.path,detector=self.detector).snapshot()
        self.assertEqual(snap['suggestedTarget'],'vbot@192.168.0.171');self.assertEqual(snap['label'],'Home')
        self.assertEqual(len(snap['addresses']),2);self.assertEqual(os.stat(self.path).st_mode&0o777,0o600)
        self.assertTrue(self.book.target_verified('192.168.0.170',FP))
        self.assertFalse(self.book.target_verified('192.168.0.171',FP))
        self.assertFalse(self.book.target_verified('192.168.0.170','SHA256:'+'b'*43))
        self.assertFalse(list(self.path.parent.glob('*.tmp')))
    def test_new_network_has_no_fallback_to_another_network_ip(self):
        self.book.remember('192.168.0.170',label='Home')
        self.network=net(ip='172.20.10.4',gateway='172.20.10.1',mac='00:11:22:33:44:55')
        self.book.current(force=True)
        self.assertIsNone(self.book.snapshot()['suggestedTarget'])
        self.book.remember('172.20.10.5',label="Rich's hotspot",fingerprint=FP,verified=True)
        self.assertEqual(len(self.book.snapshot()['profiles']),2)
        self.network=net();self.book.current(force=True)
        self.assertEqual(self.book.snapshot()['suggestedTarget'],'vbot@192.168.0.170')
    def test_stale_network_wrong_subnet_and_mac_router_addresses_cannot_be_saved(self):
        old=self.book.current()['id'];self.network=net(mac='11:22:33:44:55:66')
        with self.assertRaises(ValueError):self.book.remember('192.168.0.170',network_id=old)
        for target in ['172.20.10.5','192.168.0.191','192.168.0.1']:
            with self.assertRaises(ValueError):self.book.remember(target)
        self.assertFalse(self.path.exists())
    def test_unknown_network_does_not_get_remembered_under_a_weak_key(self):
        self.network=net(mac=None)
        with self.assertRaises(ValueError):self.book.remember('192.168.0.170')
        self.assertFalse(self.path.exists())
    def test_invalid_or_corrupt_memory_is_preserved_and_not_used(self):
        for data in ['{broken','{"version":99,"networks":{}}']:
            self.path.write_text(data);book=NetworkBook(self.path,detector=self.detector)
            self.assertTrue(book.snapshot()['error']);self.assertIsNone(book.snapshot()['suggestedTarget'])
            with self.assertRaises(ValueError):book.remember('192.168.0.170')
            self.assertEqual(self.path.read_text(),data)
    def test_failed_atomic_save_does_not_change_disk_or_memory(self):
        self.book.remember('192.168.0.170');before=self.path.read_text();state=copy.deepcopy(self.book.data)
        with patch('vbot_networks.os.replace',side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):self.book.remember('192.168.0.171')
        self.assertEqual(self.path.read_text(),before);self.assertEqual(self.book.data,state)
    def test_targets_and_alias_anchor_reject_option_or_command_injection(self):
        for target in ['-oProxyCommand=bad','root@192.168.0.170','192.168.0.999','8.8.8.8','127.0.0.1','host;cmd','$(cmd)']:
            with self.assertRaises(ValueError):normalize_target(target)
        command=ssh_command('vbot@192.168.0.170','actions/ROCKYOU.json','a'*32,host_key_alias='vbot@172.20.10.5')
        self.assertIn('HostKeyAlias=172.20.10.5',command);self.assertIn('StrictHostKeyChecking=yes',command)
        self.assertNotIn('StrictHostKeyChecking=no',command)

class NetworkControllerTests(unittest.TestCase):
    def setUp(self):
        NetworkBookTests.setUp(self)
        self.profile={'target':'vbot@172.20.10.5','hostKeyFingerprint':FP,'presets':[
            {'preset':'actions/ROCKYOU.json','status':'SUCCEEDED','errorCategory':0,'movementConfirmed':True}]}
        self.keys=Mock(side_effect=lambda target:{FP} if target==self.profile['target'] else set())
        self.checker=Mock(return_value={'ready':True,'code':'ready','reason':None})
        self.sender=Mock()
        self.demo=VbotDemo(network_book=self.book,verification=self.profile,fingerprint_reader=self.keys,
                           checker=self.checker,sender=self.sender)
    def test_status_selects_saved_current_network_without_ssh_probe_or_arming(self):
        self.book.remember('192.168.0.170')
        status=self.demo.status()
        self.assertEqual(status['target'],'vbot@192.168.0.170');self.assertFalse(status['armed'])
        self.checker.assert_not_called();self.sender.assert_not_called();self.keys.assert_not_called()
    def test_check_learns_only_after_matching_ssh_identity_and_helper_reply(self):
        self.demo.check_device({'target':'vbot@192.168.0.170'})
        self.assertTrue(self.book.target_verified('192.168.0.170',FP))
        self.assertTrue(self.demo._verified_entry('vbot@192.168.0.170','actions/ROCKYOU.json'))
        self.assertTrue(self.demo._identity_matches('vbot@192.168.0.170'))
        self.assertFalse(self.demo.armed)
    def test_unverified_candidate_does_not_inherit_rehearsals_or_learn_from_failure(self):
        self.book.remember('192.168.0.170')
        self.assertIsNone(self.demo._verified_entry('vbot@192.168.0.170','actions/ROCKYOU.json'))
        self.checker.return_value={'ready':False,'code':'unavailable'}
        self.demo.check_device({'target':'vbot@192.168.0.170'})
        self.assertFalse(self.book.target_verified('192.168.0.170',FP))
    def test_wrong_saved_ssh_anchor_blocks_probe_without_learning(self):
        self.keys.return_value=set();self.keys.side_effect=None
        with self.assertRaises(ValueError):self.demo.check_device({'target':'vbot@192.168.0.170'})
        self.checker.assert_not_called();self.assertFalse(self.path.exists())
    def test_network_change_disarms_clears_readiness_selects_no_stale_fallback(self):
        self.book.remember('192.168.0.170',fingerprint=FP,verified=True)
        self.demo.check_device({'target':'vbot@192.168.0.170'})
        self.demo.arm({'mode':'live','gameId':'AbCd1234','target':'vbot@192.168.0.170',
            'confirmSafeWorkspace':True,'confirmHandsetStop':True,'requireReadiness':True})
        self.network=net(ip='172.20.10.4',gateway='172.20.10.1',mac='00:11:22:33:44:55')
        self.demo._sync_network(force=True);status=self.demo.status()
        self.assertFalse(status['armed']);self.assertIsNone(status['readiness']);self.assertEqual(status['target'],'')
        self.assertTrue(any(e.get('reasonCode')=='network_changed' for e in status['events']))
        self.sender.assert_not_called()
    def test_network_hop_during_readiness_cannot_save_or_arm_stale_check(self):
        def check(_):
            self.network=net(mac='11:22:33:44:55:66')
            return {'ready':True,'code':'ready'}
        self.demo.checker=check
        with self.assertRaises(ValueError):self.demo.check_device({'target':'vbot@192.168.0.170'})
        self.assertFalse(self.path.exists());self.assertFalse(self.demo.armed)
    def test_manual_remember_requires_current_network_and_never_marks_an_address_verified(self):
        with self.assertRaises(ValueError):self.demo.remember_network({'target':'192.168.0.170'})
        network_id=self.book.current()['id']
        self.demo.remember_network({'target':'192.168.0.170','networkId':network_id,'label':'Home'})
        self.assertFalse(self.book.target_verified('192.168.0.170',FP));self.sender.assert_not_called()
        self.demo.arm({'gameId':'AbCd1234'})
        with self.assertRaises(ValueError):self.demo.remember_network({'target':'192.168.0.171','networkId':network_id})

    def test_real_check_and_dispatch_build_strict_ssh_with_existing_identity_anchor(self):
        import shlex
        commands=[]
        def run(command,**kwargs):
            commands.append(command)
            remote=shlex.split(command[-1]);rid=remote[remote.index('--request-id')+1]
            item=({'event':'readiness','requestId':rid,'ready':True,'code':'ready'} if '--check-ready' in remote
                else {'event':'terminal','requestId':rid,'status':'SUCCEEDED','errorCategory':0,'readyForNext':True})
            return type('Result',(),{'returncode':0,'stdout':json.dumps(item),'stderr':''})()
        demo=VbotDemo(network_book=self.book,verification=self.profile,fingerprint_reader=self.keys)
        with patch('vbot_demo.subprocess.run',side_effect=run):
            demo.check_device({'target':'vbot@192.168.0.170'})
            demo.sender('vbot@192.168.0.170','actions/ROCKYOU.json','a'*32)
        self.assertEqual(len(commands),2)
        for command in commands:
            self.assertIn('HostKeyAlias=172.20.10.5',command)
            self.assertIn('StrictHostKeyChecking=yes',command)
            self.assertEqual(command[-2],'vbot@192.168.0.170')
        self.assertTrue(self.book.target_verified('192.168.0.170',FP))

    def test_network_changed_before_dispatch_cancels_instead_of_following_new_ip(self):
        self.demo.status();self.demo.arm({'gameId':'AbCd1234'})
        generation=self.demo.generation;self.demo.busy=True
        self.network=net(mac='11:22:33:44:55:66')
        self.demo._run(self.demo.target,'actions/ROCKYOU.json','a'*32,generation)
        self.sender.assert_not_called();self.assertFalse(self.demo.armed)

if __name__=='__main__':unittest.main()
