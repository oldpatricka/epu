import logging
import uuid

from epu.decisionengine.engineapi import Engine
from epu.states import InstanceState, InstanceHealthState


log = logging.getLogger(__name__)

class MockDomain(object):

    def __init__(self, owner):
        self.owner = owner

class MockInstances(object):

    def __init__(self, site, state=InstanceState.REQUESTING):
        self.site = site
        self.state = state
        self.instance_id = 'ami-' + str(uuid.uuid4()).split('-')[0]

class MockState(object):

    def __init__(self, instances=None):
        self.instances = {}
        if instances is not None:
            for i in instances:
                self.instances[i.instance_id] = i

class MockControl(object):

    def __init__(self):
        self._launch_calls = 0
        self._destroy_calls = 0
        self.domain = MockDomain("user")

        self.site_launch_calls = {}
        self.site_destroy_calls = {}
        self.instances = []

    def get_state(self):
        return MockState(self.instances)

    def launch(self, dt_name, sites_name, instance_type, caller=None):
        self._launch_calls  = self._launch_calls + 1

        if sites_name not in self.site_launch_calls:
            self.site_launch_calls[sites_name] = 0
        self.site_launch_calls[sites_name] = self.site_launch_calls[sites_name] + 1

        instance = MockInstances(sites_name)
        self.instances.append(instance)

        launch_id = str(uuid.uuid4())
        instance_ids = [instance.instance_id,]
        return (launch_id, instance_ids)

    def destroy_instances(self, instanceids, caller=None):
        found_insts = []
        for i in self.instances:
            if i.instance_id in instanceids:
                found_insts.append(i)

        if len(found_insts) != len(instanceids):
            raise Exception("Some instances ids were not found")

        for i in found_insts:
            if i.site not in self.site_destroy_calls:
                self.site_launch_calls[i.site] = 0
            self.site_launch_calls[i.site] = self.site_launch_calls[i.site] + 1
            i.state = InstanceState.TERMINATING

        self._destroy_calls  = self._destroy_calls + len(instanceids)

    def get_instances(self, site=None, states=None):
        instances = self.instances[:]

        if site:
            instances = [i for i in instances if i.site == site]
        if states:
            instances = [i for i in instances if i.state in states]

        return instances

class MockProvisionerClient(object):
    """See the IProvisionerClient class.
    """
    def __init__(self):
        self.provision_count = 0
        self.terminate_node_count = 0
        self.launched_instance_ids = []
        self.terminated_instance_ids = []
        self.deployable_types_launched = []
        self.launches = []
        self.epum = None

    def _set_epum(self, epum):
        # circular ref, only in this mock/unit test situation
        self.epum = epum

    def provision(self, launch_id, instance_ids, deployable_type, subscribers,
                  site, allocation=None, vars=None, caller=None):
        self.provision_count += 1
        log.debug("provision() count %d", self.provision_count)
        self.launched_instance_ids.extend(instance_ids)
        for _ in instance_ids:
            self.deployable_types_launched.append(deployable_type)

        record = dict(launch_id=launch_id, dt=deployable_type,
            instance_ids=instance_ids, site=site, allocation=allocation,
            subscribers=subscribers, vars=vars)
        self.launches.append(record)

    def terminate_nodes(self, nodes, caller=None):
        self.terminate_node_count += len(nodes)
        self.terminated_instance_ids.extend(nodes)
        if self.epum:
            for node in nodes:
                content = {"node_id": node, "state": InstanceState.TERMINATING}
                self.epum.msg_instance_info(None, content)

    def terminate_all(self, rpcwait=False, retries=5, poll=1.0):
        log.debug("terminate_all()")

    def dump_state(self, nodes, force_subscribe=None):
        log.debug("dump_state()")

class MockSubscriberNotifier(object):
    """See the ISubscriberNotifier class
    """
    def __init__(self):
        self.notify_by_name_called = 0
        self.receiver_names = []
        self.operations = []
        self.messages = []

    def notify_by_name(self, receiver_name, operation, message):
        """The name is translated into the appropriate messaging-layer object.
        @param receiver_name Message layer name
        @param operation The operation to call on that name
        @param message dict to send
        """
        log.debug("EPUM notification for %s:%s: %s", receiver_name, operation,
                  message)
        self.notify_by_name_called += 1
        self.receiver_names.append(receiver_name)
        self.operations.append(operation)
        self.messages.append(message)

class MockOUAgentClient(object):
    """See the IOUAgentClient class
    """
    def __init__(self):
        self.epum = None
        self.dump_state_called = 0
        self.heartbeats_sent = 0
        self.respond_to_dump_state = False
        
    def dump_state(self, target_address, mock_timestamp=None):
        self.dump_state_called += 1
        if self.epum and self.respond_to_dump_state:
            # In Mock mode, we know that node_id and the OUAgent address are equal things, by convention
            content = {'node_id':target_address, 'state':InstanceHealthState.OK}
            self.epum.msg_heartbeat(None, content, timestamp=mock_timestamp)
            self.heartbeats_sent += 1

    def _set_epum(self, epum):
        # circular ref, only in this mock/unit test situation
        self.epum = epum

class MockDecisionEngine01(Engine):
    """
    Counts only
    """

    def __init__(self):
        Engine.__init__(self)
        self.initialize_count = 0
        self.initialize_conf = None
        self.decide_count = 0
        self.reconfigure_count = 0

    def initialize(self, control, state, conf=None):
        self.initialize_count += 1
        self.initialize_conf = conf

    def decide(self, *args):
        self.decide_count += 1

    def reconfigure(self, *args):
        self.reconfigure_count += 1

class MockDecisionEngine02(Engine):
    """
    Fails only
    """

    def __init__(self):
        Engine.__init__(self)
        self.initialize_count = 0
        self.initialize_conf = None
        self.decide_count = 0
        self.reconfigure_count = 0

    def initialize(self, control, state, conf=None):
        self.initialize_count += 1
        self.initialize_conf = conf

    def decide(self, *args):
        self.decide_count += 1
        raise Exception("decide disturbance")

    def reconfigure(self, *args):
        self.reconfigure_count += 1
        raise Exception("reconfigure disturbance")
