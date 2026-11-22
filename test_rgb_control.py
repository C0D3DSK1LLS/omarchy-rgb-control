import importlib.util,threading,time,types
from unittest.mock import patch
from pathlib import Path
p=str(Path(__file__).with_name('app.py'))
spec=importlib.util.spec_from_file_location('rgb',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
k=m.Device(-1,m.K70_NAME);k.keyboard=True;k.type='Keyboard';k.zones=['Keyboard'];k.led_count=111
board=m.Device(0,'MSI');board.zones=list(m.ZONE_LEDS)
# A preset must do just one OpenRGB detection, then native colour/brightness.
with patch.object(m,'cli',return_value=(True,'')) as cli,patch.object(m,'keyboard_colour',return_value=(True,'')) as native:
 assert m.write_devices([k,board],'#dc143c',73,lambda _:None,threading.Event())[0]
 assert cli.call_count==1 and cli.call_args.args[0].count('-d')==len(board.zones)
 assert k.name not in cli.call_args.args[0]
 native.assert_called_once_with('#dc143c',73)
with patch.object(m,'cli',return_value=(True,'')) as cli,patch.object(m,'keyboard_colour',return_value=(True,'')):
 assert m.write_devices([k],'#00ff41',80,lambda _:None,threading.Event())[0]
 assert not cli.called
with patch.object(m.subprocess,'run',return_value=types.SimpleNamespace(returncode=0,stdout='Error: invalid mode',stderr='')):
 assert not m.cli(['-l'])[0]
# Exercise the real GLib loop and actual Panel worker methods without a display.
# This sandbox prohibits X11/D-Bus socket binds, so real widget rendering cannot run.
class Control:
 def __init__(self):self.sensitive=True
 def set_sensitive(self,v):self.sensitive=v
 def get_sensitive(self):return self.sensitive
 def set_spinning(self,v):pass
 def set_visible(self,v):pass
 def get_value(self):return 80
 def get_rgba(self):return m.hex_to_rgba(getattr(self,'colour','#00ff41'))
 def set_rgba(self,value):self.colour=m.rgb_to_hex(value)
class Status:
 def set_text(self,value):self.text=value
 def get_text(self):return self.text
 def set_tooltip_text(self,value):pass
 def remove_css_class(self,value):pass
 def add_css_class(self,value):pass
class PanelHarness:
 set_busy=m.Panel.set_busy
 post_status=m.Panel.post_status
 run_job=m.Panel.run_job
 scan=m.Panel.scan
 set_status=m.Panel.set_status
 apply_device=m.Panel.apply_device
 apply_everything=m.Panel.apply_everything
 start_apply=m.Panel.start_apply
 on_close=m.Panel.on_close
 release_keyboard=m.Panel.release_keyboard
 keep_keyboard_alive=m.Panel.keep_keyboard_alive
 def __init__(self):
  self.busy=self.closed=False;self.cancelled=threading.Event()
  self.hardware_lock=threading.Lock();self.keyboard_touched=False;self.keepalive_source=None
  self.actions=[Control()];self.spinner=Control();self.colour_button=Control()
  self.bright=Control();self.status=Status();self.devices=[]
 def show_devices(self,devices):self.devices=devices
 def close(self):self.on_close()
main_id=threading.get_ident();workers=[];ticks=[]
def slow_scan():
 workers.append(threading.get_ident());time.sleep(.55);return [k,board]
def slow_native(colour,brightness):
 workers.append(threading.get_ident());time.sleep(.55);return True,''
def slow_cli(args):
 workers.append(threading.get_ident());time.sleep(.55);return True,''
def pump(seconds):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  for _ in range(20):
   if not m.GLib.MainContext.default().pending():break
   m.GLib.MainContext.default().iteration(False)
  time.sleep(.005)
with patch.object(m,'keyboard_request',return_value=(True,'')),patch.object(m,'parse_devices',side_effect=slow_scan),patch.object(m,'keyboard_colour',side_effect=slow_native),patch.object(m,'cli',side_effect=slow_cli):
 win=PanelHarness();win.scan()
 timer=m.GLib.timeout_add(20,lambda:(ticks.append(time.monotonic()) or True))
 pump(.2);assert win.busy and not win.actions[0].get_sensitive()
 before=len(ticks);pump(.6);assert not win.busy and len(ticks)-before>15
 win.apply_device(k);before=len(ticks);pump(.2);assert win.busy
 win.apply_everything('#ffffff') # Ignored during operation; no concurrent writers.
 pump(.6);assert not win.busy and len(ticks)-before>15
 assert '#00ff41' in win.status.get_text()
 win.apply_everything('#dc143c');before=len(ticks);pump(1.35)
 assert not win.busy and '#dc143c' in win.status.get_text() and len(ticks)-before>35
 # Scan errors must clear busy and surface the error, not pretend zero devices.
 with patch.object(m,'parse_devices',side_effect=RuntimeError('test scan failure')):
  win.scan();pump(.15);assert not win.busy and win.status.get_text()=='test scan failure'
 assert all(ident!=main_id for ident in workers)
 # Closing while a job runs cancels its remaining batch and suppresses UI callbacks.
 win.apply_device(k);pump(.1);win.close();assert win.closed and win.cancelled.is_set();pump(.7)
 m.GLib.source_remove(timer)
print('PASS: batched zones; keyboard bypass; brightness routing; CLI errors; GLib heartbeat during slow scan/apply/preset; no overlapping jobs; scan failure; close during work')

# Mouse supports Direct, but has no Static mode (the real screenshot failure).
mouse=m.Device(2,'Corsair Nightsword');mouse.modes=['Direct','Breathing']
args=m.device_args(mouse,'#00ff41',80)
assert args[args.index('-m')+1]=='Direct'
print('PASS: Nightsword uses supported Direct mode')
