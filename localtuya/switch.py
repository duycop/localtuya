"""
Simple platform to control LOCALLY Tuya switch devices.

Sample config yaml

switch:
  - platform: localtuya
    host: 192.168.0.1
    local_key: 1234567891234567
    device_id: 12345678912345671234
    name: tuya_01
    protocol_version: 3.3
    scan_interval: 1
    interval: 1
"""
import voluptuous as vol
from datetime import timedelta

from homeassistant.components.switch import SwitchDevice, PLATFORM_SCHEMA
from homeassistant.const import (CONF_HOST, CONF_ID, CONF_SWITCHES, CONF_FRIENDLY_NAME, CONF_ICON, CONF_NAME)
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.event import track_time_interval
import logging

from time import time, sleep
from threading import Lock
import socket

REQUIREMENTS = ['pytuya==7.0.4']

CONF_DEVICE_ID = 'device_id'
CONF_LOCAL_KEY = 'local_key'
CONF_PROTOCOL_VERSION = 'protocol_version'
CONF_CURRENT = 'current'
CONF_CURRENT_CONSUMPTION = 'current_consumption'
CONF_VOLTAGE = 'voltage'
CONF_INTERVAL = 'interval'


DEFAULT_ID = '1'
DEFAULT_PROTOCOL_VERSION = 3.3
DEFAULT_INTERVAL = 5

ATTR_CURRENT = 'current'
ATTR_CURRENT_CONSUMPTION = 'current_consumption'
ATTR_VOLTAGE = 'voltage'

UPDATE_RETRY_LIMIT = 10

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_ICON): cv.icon,
    vol.Required(CONF_HOST): cv.string,
    vol.Required(CONF_DEVICE_ID): cv.string,
    vol.Required(CONF_LOCAL_KEY): cv.string,
    vol.Required(CONF_NAME): cv.string,
    vol.Required(CONF_PROTOCOL_VERSION, default=DEFAULT_PROTOCOL_VERSION): vol.Coerce(float),
    vol.Optional(CONF_ID, default=DEFAULT_ID): cv.string,
    vol.Optional(CONF_CURRENT, default='4'): cv.string,
    vol.Optional(CONF_CURRENT_CONSUMPTION, default='5'): cv.string,
    vol.Optional(CONF_VOLTAGE, default='6'): cv.string,
    vol.Optional(CONF_INTERVAL, default=DEFAULT_INTERVAL): cv.string,
})


def setup_platform(hass, config, add_devices, discovery_info=None):
    """Set up of the Tuya switch."""
    from . import pytuya

    _interval = int(config.get(CONF_INTERVAL))
    switches = []
    pytuyadevice = pytuya.OutletDevice(config.get(CONF_DEVICE_ID), config.get(CONF_HOST), config.get(CONF_LOCAL_KEY))
    pytuyadevice.set_version(float(config.get(CONF_PROTOCOL_VERSION)))
    outlet_device = TuyaCache(pytuyadevice, _interval)

    switches.append(
            TuyaDevice(
                outlet_device,
                config.get(CONF_NAME),
                config.get(CONF_ICON),
                config.get(CONF_ID),
                config.get(CONF_CURRENT),
                config.get(CONF_CURRENT_CONSUMPTION),
                config.get(CONF_VOLTAGE)
            )
    )

    add_devices(switches)

    def poll_devices_update(event_time):
        for device in switches:
           device.update()

    track_time_interval(hass, poll_devices_update, timedelta(seconds=_interval))

class TuyaCache:
    """Cache wrapper for pytuya.OutletDevice"""

    def __init__(self, device, interval):
        """Initialize the cache."""
        self._cached_status = ''
        self._cached_status_time = 0
        self._cached_available = False
        self._device = device
        self._interval = interval
        self._lock = Lock()

    def __get_status(self):
        for _ in range(UPDATE_RETRY_LIMIT):
            try:
                self._cached_available = True
                status = self._device.status()
                return status
            except ConnectionError:
                pass
            except socket.timeout:
                pass

        self._cached_available = False
        log.warn(
            "Failed to get status after {} tries".format(UPDATE_RETRY_LIMIT))

    def set_status(self, state, switchid):
        """Change the Tuya switch status and clear the cache."""
        self._cached_status = ''
        self._cached_status_time = 0
        for _ in range(UPDATE_RETRY_LIMIT):
            try:
                self._cached_available = True
                return self._device.set_status(state, switchid)
            except ConnectionError:
                pass
            except socket.timeout:
                pass

        self._cached_available = False
        log.warn(
            "Failed to set status after {} tries".format(UPDATE_RETRY_LIMIT))

    def status(self):
        """Get state of Tuya switch and cache the results."""
        self._lock.acquire()
        try:
            now = time()
            if not self._cached_status or now - self._cached_status_time > self._interval:
                sleep(0.5)
                self._cached_status = self.__get_status()
                self._cached_status_time = time()
                self._cached_available = True
            return self._cached_status
        except:
            self._cached_available = False
            raise
        finally:
            self._lock.release()

    def available(self):
        return self._cached_available

class TuyaDevice(SwitchDevice):
    """Representation of a Tuya switch."""

    def __init__(self, device, name, icon, switchid, attr_current, attr_consumption, attr_voltage):
        """Initialize the Tuya switch."""
        self._device = device
        self._name = name
        self._icon = icon
        self._switch_id = switchid
        self._attr_current = attr_current
        self._attr_consumption = attr_consumption
        self._attr_voltage = attr_voltage

        self._status = None
        self._state = False
        self._available = False

        print('Initialized tuya switch [{}] '.format(name))

        try:
            self._status = self._device.status()
            self._state = self._status['dps'][self._switch_id]
            self._available = True
        except:
            pass

        print('Initialized tuya switch [{}] with switch status [{}] and state [{}]'.format(self._name, self._status, self._state))

    @property
    def name(self):
        """Get name of Tuya switch."""
        return self._name

    @property
    def is_on(self):
        """Check if Tuya switch is on."""
        return self._state

    @property
    def device_state_attributes(self):
        attrs = {}
        try:
            attrs[ATTR_CURRENT] = "{}".format(self._status['dps'][self._attr_current])
            print('attrs[ATTR_CURRENT]'.format(attrs[ATTR_CURRENT]))
            attrs[ATTR_CURRENT_CONSUMPTION] = "{}".format(self._status['dps'][self._attr_consumption]/10)
            print('attrs[ATTR_CURRENT_CONSUMPTION]'.format(attrs[ATTR_CURRENT_CONSUMPTION]))
            attrs[ATTR_VOLTAGE] = "{}".format(self._status['dps'][self._attr_voltage]/10)
            print('attrs[ATTR_VOLTAGE]'.format(attrs[ATTR_VOLTAGE]))
            self._available = True
        except KeyError:
            pass
        return attrs

    @property
    def icon(self):
        """Return the icon."""
        return self._icon

    @property
    def available(self):
        """Return if available."""
        return (self._device.available() and self._available)

    def turn_on(self, **kwargs):
        """Turn Tuya switch on."""
        self._device.set_status(True, self._switch_id)

    def turn_off(self, **kwargs):
        """Turn Tuya switch off."""
        self._device.set_status(False, self._switch_id)

    def update(self):
        """Get state of Tuya switch."""
        try:
            self._status = self._device.status()
            self._state = self._status['dps'][self._switch_id]
            self._available = True
        except:
            self._available = False
            log.debug('update except')
