#!/usr/bin/env python

"""
@file ion/services/cei/provisioner.py
@author Michael Meisinger
@brief service for provisioning operational units (VM instances).
"""

from twisted.python import log
from twisted.internet import defer

from magnet.spawnable import Receiver
from magnet.spawnable import send
from magnet.spawnable import spawn
from magnet.store import Store

from ion.services import BaseService

class ProvisionerService(BaseService):
    none
    