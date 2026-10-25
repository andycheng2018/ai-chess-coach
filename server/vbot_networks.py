"""Local network/address memory. Detection reads Mac settings, never probes peers."""
from __future__ import annotations
import copy
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import uuid

PATH = Path(__file__).resolve().parents[1]/'vbot-demo'/'networks.local.json'


def normalize_target(value):
    value = str(value or '').strip().removeprefix('vbot@')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,252}', value):
        raise ValueError('Enter a robot IP or SSH hostname, without spaces, options or another username.')
    if re.fullmatch(r'[0-9.]+', value):
        try: address = ipaddress.IPv4Address(value)
        except ValueError: raise ValueError('Enter a valid robot IPv4 address.') from None
        if not address.is_private or address.is_loopback or address.is_unspecified or address.is_multicast or str(address)=='255.255.255.255':
            raise ValueError('Remember a private LAN robot address.')
    return 'vbot@'+value


def _read(argv, run):
    try:
        result = run(argv, capture_output=True, text=True, timeout=3, check=False)
        return result.stdout.strip() if result.returncode == 0 else ''
    except (OSError, subprocess.SubprocessError):
        return ''


def network_identity(*, interface, local_ip, netmask, gateway, gateway_mac=None, ssid=None):
    try:
        address = ipaddress.IPv4Address(local_ip)
        router = ipaddress.IPv4Address(gateway)
        if str(netmask).startswith('0x'):netmask=str(ipaddress.IPv4Address(int(netmask,16)))
        subnet = ipaddress.IPv4Network(f'{local_ip}/{netmask}', strict=False)
        if address not in subnet or router not in subnet or not address.is_private:
            raise ValueError('Non-local default route')
    except ValueError:
        return {'id':None,'message':'A local IPv4 network could not be identified. Enter the robot address manually.'}
    if gateway_mac:
        try:
            parts=gateway_mac.lower().split(':')
            if len(parts)!=6 or any(not re.fullmatch('[0-9a-f]{1,2}',p) for p in parts):raise ValueError()
            gateway_mac=':'.join(p.zfill(2) for p in parts)
            if gateway_mac=='00:00:00:00:00:00':gateway_mac=None
        except ValueError:gateway_mac=None
    anchor = {'subnet':str(subnet),'gateway':str(router),
              'routerMac':gateway_mac} if gateway_mac else {'subnet':str(subnet),'gateway':str(router),'ssid':ssid}
    key = hashlib.sha256(json.dumps(anchor,sort_keys=True).encode()).hexdigest() if gateway_mac or ssid else None
    return {'id':key,'interface':interface,'localIp':str(address),'subnet':str(subnet),'gateway':str(router),
            'gatewayMac':gateway_mac,'ssid':ssid,
            'identitySource':'router' if gateway_mac else 'ssid' if ssid else 'unknown',
            'message':None if ssid else 'Wi-Fi name unavailable; using the local router fingerprint.' if key
                else 'Network name and router identity are unavailable; addresses will not be matched by subnet alone.'}


def detect_network(run=subprocess.run):
    route = _read(['/sbin/route','-n','get','default'],run)
    fields=dict(re.findall(r'^\s*(gateway|interface):\s*(\S+)',route,re.M))
    interface=fields.get('interface','')
    if not re.fullmatch(r'en\d+',interface):
        return {'id':None,'message':'No physical LAN default route detected. VPN/unknown routes require a manual robot address.'}
    config=_read(['/sbin/ifconfig',interface],run)
    address=re.search(r'\binet (\d+\.\d+\.\d+\.\d+) netmask (\S+)',config)
    if not address or not fields.get('gateway'):
        return {'id':None,'message':'Mac LAN address unavailable. Enter the robot address manually.'}
    wifi=_read(['/usr/sbin/networksetup','-getairportnetwork',interface],run)
    ssid=wifi.split(': ',1)[1].strip() if wifi.startswith('Current Wi-Fi Network: ') else None
    arp=_read(['/usr/sbin/arp','-n',fields['gateway']],run)  # cache lookup only
    mac=re.search(r'\bat ([0-9a-f:]+) on ',arp,re.I)
    return network_identity(interface=interface,local_ip=address[1],netmask=address[2],gateway=fields['gateway'],
                            gateway_mac=mac[1] if mac else None,ssid=ssid)


class NetworkBook:
    def __init__(self,path=PATH,detector=detect_network,clock=time.monotonic):
        self.path=Path(path);self.detector=detector;self.clock=clock
        self.lock=threading.RLock();self.detected=None;self.detected_at=float('-inf')
        self.data={'version':1,'networks':{}};self.error=None
        try:
            if self.path.exists():
                if self.path.stat().st_size>1048576:raise ValueError('Network memory is too large.')
                data=json.loads(self.path.read_text())
                if not isinstance(data,dict) or data.get('version')!=1 or not isinstance(data.get('networks'),dict):
                    raise ValueError('Network memory format is unsupported.')
                if len(data['networks'])>256:raise ValueError('Too many network profiles.')
                for key,item in data['networks'].items():
                    if not re.fullmatch('[0-9a-f]{64}',key) or not isinstance(item,dict) or not isinstance(item.get('addresses'),list):
                        raise ValueError('Invalid network profile.')
                    if (not isinstance(item.get('label'),str) or not isinstance(item.get('identity'),dict)
                            or item['identity'].get('id')!=key):raise ValueError('Invalid network metadata.')
                    if len(item['addresses'])>16:raise ValueError('Too many addresses in a network profile.')
                    for entry in item['addresses']:
                        if not isinstance(entry,dict) or normalize_target(entry.get('target'))!=entry['target']:
                            raise ValueError('Invalid remembered address.')
                        for field in ['createdAt','lastVerifiedAt','lastUsedAt']:
                            value=entry.get(field)
                            if value is not None and (not isinstance(value,(int,float)) or isinstance(value,bool) or value<0):
                                raise ValueError('Invalid address timestamp.')
                        if entry.get('lastVerifiedAt') and not re.fullmatch(r'SHA256:[A-Za-z0-9+/]{43}',entry.get('hostKeyFingerprint') or ''):
                            raise ValueError('Invalid remembered robot identity.')
                self.data=data
        except (OSError,ValueError,TypeError,KeyError):
            self.error='Network memory could not be read. Existing data was preserved; automatic address selection is off.'
    def current(self,force=False):
        with self.lock:
            if force or self.detected is None or self.clock()-self.detected_at>=5:
                try:self.detected=self.detector()
                except Exception:self.detected={'id':None,'message':'Network detection unavailable. Enter the robot address manually.'}
                self.detected_at=self.clock()
            return dict(self.detected)
    def _write(self):
        if self.error:raise ValueError(self.error)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temp=self.path.with_name('.'+self.path.name+'.'+uuid.uuid4().hex+'.tmp')
        try:
            with open(os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as stream:
                json.dump(self.data,stream,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
            os.replace(temp,self.path)
        finally:
            if temp.exists():temp.unlink()
    def remember(self,target,*,label='',fingerprint=None,verified=False,network_id=None):
        target=normalize_target(target)
        with self.lock:
            network=self.current(force=True)
            if not network.get('id') or network_id is not None and network_id!=network['id']:
                raise ValueError('The network changed or cannot be identified. Save the address again on the intended network.')
            if self.error:raise ValueError(self.error)
            host=target.removeprefix('vbot@')
            try:
                address=ipaddress.IPv4Address(host)
            except ValueError:address=None
            if address and (address not in ipaddress.IPv4Network(network['subnet']) or str(address)==network['localIp'] or str(address)==network['gateway']):
                raise ValueError('Use the robot address on the current LAN, not this Mac, its router, or another network.')
            if verified and not re.fullmatch(r'SHA256:[A-Za-z0-9+/]{43}',fingerprint or ''):
                raise ValueError('A matching robot SSH identity is required to verify an address.')
            original=copy.deepcopy(self.data)
            profiles=self.data['networks']
            if network['id'] not in profiles and len(profiles)>=256:raise ValueError('Network memory is full.')
            profile=profiles.setdefault(network['id'],{'label':network.get('ssid') or 'Saved network','identity':network,'addresses':[]})
            if label:profile['label']=str(label).strip()[:80]
            entry=next((e for e in profile['addresses'] if e['target']==target),None)
            if entry is None:
                if len(profile['addresses'])>=16:raise ValueError('This network already has 16 remembered addresses.')
                entry={'target':target,'createdAt':int(time.time()*1000),'lastVerifiedAt':None,'hostKeyFingerprint':None}
                profile['addresses'].append(entry)
            entry['lastUsedAt']=max(int(time.time()*1000),max((e.get('lastUsedAt') or 0 for e in profile['addresses']),default=0)+1)
            if verified:
                entry.update(lastVerifiedAt=int(time.time()*1000),hostKeyFingerprint=fingerprint)
            profile['identity']=network
            try:self._write()
            except Exception:
                self.data=original
                raise
            return self.snapshot()
    def target_verified(self,target,fingerprint):
        if not fingerprint or self.error:return False
        try:target=normalize_target(target)
        except ValueError:return False
        with self.lock:
            return any(e['target']==target and e.get('lastVerifiedAt') and e.get('hostKeyFingerprint')==fingerprint
                       for p in self.data['networks'].values() for e in p['addresses'])
    def snapshot(self):
        with self.lock:
            current=self.current();profile=self.data['networks'].get(current.get('id'),{}) if not self.error else {}
            addresses=sorted(profile.get('addresses',[]),key=lambda e:e.get('lastUsedAt') or e.get('lastVerifiedAt') or e.get('createdAt') or 0,reverse=True)
            return {'current':current,'label':profile.get('label'),'addresses':[dict(e) for e in addresses],
                    'suggestedTarget':addresses[0]['target'] if addresses else None,'error':self.error,
                    'profiles':[{'id':key,'label':p['label'],'targets':[e['target'] for e in p['addresses']]}
                                for key,p in self.data['networks'].items()]}
