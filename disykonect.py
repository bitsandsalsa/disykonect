#!/usr/bin/env python
#
# TODO
# 1) fix error when Yubikey or net is disconnected
#RuntimeError: To make asynchronous calls, receive signals or export objects, D-Bus connections #must be attached to a main loop by passing mainloop=... to the constructor or calling dbus.set_#default_main_loop(...)
#
# 2) update StateManager on Upstart events for Yubikey

import argparse
import logging
import multiprocessing

import dbus
import dbus.mainloop.glib
import gobject
import pyudev
from Tkinter import *
import ttk
import tkMessageBox


log = logging.getLogger(__name__)

NM_BUS = 'org.freedesktop.NetworkManager'
NM_OBJECT_PATH = '/org/freedesktop/NetworkManager'
NM_INTERFACE = 'org.freedesktop.NetworkManager'

NM_CONNECTIVITY = {
	'UNKNOWN': 0,
	'NONE': 1,
	'PORTAL': 2,
	'LIMITED': 3,
	'FULL': 4
}
"""from /usr/include/NetworkManager/NetworkManager.h"""

NM_STATE = {
	'UNKNOWN': 0,
	'ASLEEP': 10,
	'DISCONNECTED': 20,
	'DISCONNECTING': 30,
	'CONNECTING': 40,
	'CONNECTED_LOCAL': 50,
	'CONNECTED_SITE': 60,
	'CONNECTED_GLOBAL': 70
}
"""from /usr/include/NetworkManager/NetworkManager.h"""

UPSTART_BUS = 'com.ubuntu.Upstart'
UPSTART_OBJECT_PATH = '/com/ubuntu/Upstart'
UPSTART_INTERFACE = 'com.ubuntu.Upstart0_6'

class StateManager(object):
	"""
	Manages state of Yubikey and network. Currently the state each is just a boolean for connected or not.
	"""
	_prompt_event = multiprocessing.Event()

	def __init__(self, yubikey_state=True, network_state=True):
		self._yubikey_state = yubikey_state
		self._network_state = network_state
		StateManager._gui_proc = multiprocessing.Process(target=StateManager._gui_loop)
		StateManager._gui_proc.start()
		log.debug('GUI process started [{}]'.format(StateManager._gui_proc.pid))

	@property
	def get_yubikey_state(self):
		return self._yubikey_state

	def change_yubikey_state(self, state):
		self._yubikey_state = state
		log.info('yubikey state changed to {}'.format(state))
		self._check_global_state()

	@property
	def get_network_state(self):
		return self._network_state

	def change_network_state(self, state):
		self._network_state = state
		log.info('network state changed to {}'.format(state))
		self._check_global_state()

	def _check_global_state(self):
		if self._yubikey_state and self._network_state:
			self._prompt_event.set()
		else:
			self._prompt_event.clear()

	@classmethod
	def _gui_loop(cls):
		try:
			while True:
				cls._prompt_event.wait()
				prompt_user2('Please disconnect Yubikey or network')
		except KeyboardInterrupt:
			pass

def is_yk_connected():
	"""
	Look in udev database for USB device with a magic attribute value.
	"""
	#XXX: the technique to identify a Yubikey device could be improved
	target_keys = ['ID_VENDOR', 'ID_MODEL']
	target_vals = ['YUBIKEY', 'YUBICO']
	context = pyudev.Context()
	for dev in context.list_devices(subsystem='usb'):
		log.debug('detected USB device path = {}'.format(dev.device_path))
		for key in target_keys:
			val = dev.get(key)
			log.debug('attribute: key={} value={}'.format(key, val))
			if val:
				if val.upper() in target_vals:
					log.info('device appears to be Yubikey: {}'.format(dev.device_path))
					return True
	return False

def is_net_connected():
	bus = dbus.SystemBus()
	nm_obj = bus.get_object(NM_BUS, NM_OBJECT_PATH)
	con_status_num = nm_obj.CheckConnectivity()
	try:
		con_status_str = [s for s,n in NM_CONNECTIVITY.items() if n == con_status_num][0]
	except IndexError:
		con_status_str = 'ERROR: unknown connectivity status'
	log.info('Connection Status = {:d} ("{}")'.format(con_status_num, con_status_str))
	return con_status_num != NM_CONNECTIVITY['NONE']

def nm_state_changed_handler(*args, **kwargs):
	global state_mgr
	new_state_num = kwargs['msg'].get_args_list()[0]

	# pretty print state string
	try:
		new_state_str = [s for s,n in NM_STATE.items() if n == new_state_num][0]
	except IndexError:
		new_state_str = 'ERROR: unknown network state'
	log.info('Network Manager state changed to: {}'.format(new_state_str))

	# update state manager
	if new_state_num not in [NM_STATE['DISCONNECTED'], NM_STATE['DISCONNECTING']]:
		state_mgr.change_network_state(True)
	else:
		state_mgr.change_network_state(False)

def upstart_event_handler(*args, **kwargs):
	event_string, info_list = kwargs['msg'].get_args_list()
	log.info('Upstart event name: {}'.format(event_string))
	log.info('Upstart event info list: {}'.format(', '.join(info_list)))

#TODO: this should work, but is less configurable
def prompt_user2(string):
	window = Tk()

	mainframe = ttk.Frame(window)
	mainframe.grid()

	tkMessageBox.showerror('Yubikey and Network Detected', string, parent=window)

	window.destroy()

def prompt_user(string):
	window = Tk()
	window.title('Yubikey and Network Detected')

	mainframe = ttk.Frame(window, padding='3 12')
	mainframe.grid()

	ttk.Label(mainframe, text=string).grid(column=1, row=1)
	button = ttk.Button(mainframe, text='OK', command=mainframe.quit)
	button.grid(column=1, row=2)

	for child in mainframe.winfo_children(): child.grid_configure(padx=5, pady=5)

	window.bind('<Return>', button.invoke)

	window.mainloop()

def init():
	log.debug('Entering initialization...')

	while True:
		yk_connected = is_yk_connected()
		log.debug('Yubikey connected? {}'.format(yk_connected))
		net_connected = is_net_connected()
		log.debug('network connected? {}'.format(net_connected))

		if yk_connected and net_connected:
			prompt_user2('Please disconnect Yubikey or network')
		else:
			break

	log.debug('Initialization done.')

	return (yk_connected, net_connected)

def wait_loop(yk_connected=True, net_connected=True):
	log.debug('Entering wait loop...')

	global state_mgr
	state_mgr = StateManager(yk_connected, net_connected)

	dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

	bus = dbus.SystemBus()
	bus.add_signal_receiver(
		nm_state_changed_handler,
		signal_name='StateChanged',
		dbus_interface=NM_INTERFACE,
		bus_name=NM_BUS,
		path=NM_OBJECT_PATH,
		message_keyword='msg'
	)
	bus.add_signal_receiver(
		upstart_event_handler,
		signal_name='EventEmitted',
		dbus_interface=UPSTART_INTERFACE,
		bus_name=UPSTART_BUS,
		path=UPSTART_OBJECT_PATH,
		message_keyword='msg'
	)

	loop = gobject.MainLoop()
	loop.run()
	log.debug('Wait loop done.')

def main(args):
	logging.basicConfig(level=logging.ERROR)
	if args.verbose == 1:
		log.setLevel(logging.WARNING)
	elif args.verbose == 2:
		log.setLevel(logging.INFO)
	elif args.verbose >= 3:
		log.setLevel(logging.DEBUG)

	yk_connected, net_connected = init()
	wait_loop(yk_connected, net_connected)

def parse_args():
	description = 'Monitor Network Manager and Yubikey for mutual exclusivity'
	parser = argparse.ArgumentParser(description=description)
	parser.add_argument(
		'-v','--verbose',
		action='count',
		help='verbosity level. 0: minimal, 1: warnings, 2: informational, 3: debug.'
	)
	return parser.parse_args()

if __name__ == '__main__':
	main(parse_args())
