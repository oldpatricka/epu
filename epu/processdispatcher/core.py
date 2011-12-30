import logging
from itertools import ifilter

from epu.states import InstanceState, ProcessState
from epu.processdispatcher.util import node_id_from_eeagent_name


log = logging.getLogger(__name__)


class ProcessRecord(object):
    """A single process request in the system
    """
    def __init__(self, upid, spec, state, subscribers, constraints=None,
                 round=0, priority=0, immediate=False):
        self.upid = upid
        self.spec = spec
        self.state = state
        self.subscribers = subscribers
        self.constraints = constraints
        self.round = round
        self.priority = priority
        self.immediate = immediate

        self.assigned = None

    def check_resource_match(self, resource):
        return match_constraints(self.constraints, resource.properties)


class DeployedNode(object):
    def __init__(self, node_id, dt, properties=None):
        self.node_id = node_id
        self.dt = dt
        self.properties = properties

        self.resources = []


class ExecutionEngineResource(object):
    """A single EE resource
    """
    def __init__(self, node_id, ee_id, slots, properties=None):
        self.node_id = node_id
        self.ee_id = ee_id
        self.properties = properties

        self.last_heartbeat = None
        self.slot_count = slots
        self.processes = {}
        self.pending = set()

        self.enabled = True

    @property
    def available_slots(self):
        if not self.enabled:
            return 0

        return max(0, self.slot_count - len(self.processes) - len(self.pending))

    def disable(self):
        self.enabled = False

    def enable(self):
        self.enabled = True

    def add_pending_process(self, process):
        """Mark a process as pending deployment to this resource
        """
        upid = process.upid
        assert upid in self.pending or self.slot_count > 0, "no slot available"
        assert process.assigned == self.ee_id
        self.pending.add(upid)

    def check_process_match(self, process):
        """Check if this resource is valid for a process' constraints
        """
        return match_constraints(process.constraints, self.properties)


class ProcessDispatcherCore(object):
    """Service that fields requests from application engines and operators
    for process launches and termination.

    The PD has several responsibilities:

        - Receive and process requests from clients. These requests dictate
          which processes should be running. There may also be information
          queries about the state of the system.

        - Track available execution engine resources. It subscribes to a feed
          of DT deployment information from EPUM and uses this along with
          direct EEAgent heartbeats to determine available and healthy
          resources.

        - Maintain a priority queue of runnable WAITING processes. Matchmake
          processes with available resources and send dispatch requests to
          EEAgents. When resources are not available, escalate to EPUM for
          more DTs of a compatible type.

        - Track state of all processes in the system. When a process dies or
          is killed, attempt to replace it (and perhaps give it a higher
          launch priority than other WAITING processes). If a process
          repeatedly fails on its own (not due to VMs dying wholesale), mark
          it as FAILED and report to client.

    """

    def __init__(self, name, ee_registry, eeagent_client, epum_client, notifier):
        self.name = name
        self.ee_registry = ee_registry
        self.eeagent_client = eeagent_client
        self.epum_client = epum_client
        self.notifier = notifier

        self.processes = {}
        self.resources = {}
        self.nodes = {}

        self.queue = []

    def initialize(self):
        #TODO not registering needs on-demand yet, just registering
        # base needs on initialize
        for engine_spec in self.ee_registry:
            base_need = engine_spec.base_need

            log.debug("Registering need for %d instances of DT %s", base_need,
                      engine_spec.deployable_type)
            self.epum_client.register_need(engine_spec.deployable_type, {},
                                           base_need, self.name, "dt_state")

    def dispatch_process(self, upid, spec, subscribers, constraints=None, immediate=False):
        """Dispatch a new process into the system

        @param upid: unique process identifier
        @param spec: description of what is started
        @param subscribers: where to send status updates of this process
        @param constraints: optional scheduling constraints (IaaS site? other stuff?)
        @param immediate: don't provision new resources if no slots are available
        @rtype: L{ProcessRecord}
        @return: description of process launch status


        This is an RPC-style call that returns quickly, as soon as a decision is made:

            1. If a matching slot is available, dispatch begins and a PENDING
               response is sent. Further updates are sent to subscribers.

            2. If no matching slot is available, behavior depends on immediate flag
               - If immediate is True, an error is returned
               - If immediate is False, a provision request is sent and
                 WAITING is returned. Further updates are sent to subscribers.

        At the point of return, the request is either pending (and guaranteed
        to be followed through til error or success), or has failed.


        Retry
        =====
        If a call to this operation times out without a reply, it can safely
        be retried. The upid and other parameters will be used to ensure that
        nothing is repeated. If the service fields an operation request that
        it thinks has already been acknowledged, it will return the current
        state of the process (or a defined AlreadyDidThatError if that is too
        difficult).
        """
        try:
            if upid in self.processes:
                return self.processes[upid]

            process = ProcessRecord(upid, spec, ProcessState.REQUESTED,
                                   subscribers, constraints, immediate=immediate)

            self.processes[upid] = process

            self._matchmake_process(process)
            return process
        except Exception:
            log.exception("faillll")
            raise

    def _matchmake_process(self, process):
        """Match process against available resources and dispatch if matched

        @param process:
        @return:
        """

        # do an inefficient search, shrug
        not_full = ifilter(lambda r: r.available_slots > 0,
                           self.resources.itervalues())
        matching = filter(process.check_resource_match, not_full)

        if not matching:

            if process.immediate:
                log.info("Process %s: no available slots. "+
                         "REJECTED due to immediate flag", process.upid)
                process.state = ProcessState.REJECTED

            else:
                log.info("Process %s: no available slots. WAITING in queue",
                     process.upid)

                process.state = ProcessState.WAITING
                self.queue.append(process)

            return

        else:
            # pick a resource with the lowest available slot count, cheating
            # way to try and enforce compaction for now.
            resource = min(matching, key=lambda r: r.slot_count)

            self._dispatch_matched_process(process, resource)

    def _dispatch_matched_process(self, process, resource):
        """Enact a match between process and resource
        """
        ee = resource.ee_id

        log.info("Process %s assigned slot on %s. PENDING!", process.upid, ee)

        process.assigned = ee
        process.state = ProcessState.PENDING

        resource.add_pending_process(process)

        self.eeagent_client.launch_process(ee, process.upid, process.round,
                                           process.spec['run_type'],
                                           process.spec['parameters'])

    def terminate_process(self, upid):
        """
        Kill a running process
        @param upid: ID of process
        @rtype: L{ProcessState}
        @return: description of process termination status

        This is an RPC-style call that returns quickly, as soon as termination
        of the process has begun (TERMINATING state).

        Retry
        =====
        If a call to this operation times out without a reply, it can safely
        be retried. Termination of processes should be an idempotent operation
        here and at the EEAgent. It is important that eeids not be repeated to
        faciliate this.
        """

        #TODO process might not exist
        process = self.processes[upid]

        if process.state >= ProcessState.TERMINATED:
            return process

        if process.assigned is None:
            process.state = ProcessState.TERMINATED
            return process

        self.eeagent_client.terminate_process(process.assigned, upid,
                                              process.round)

        process.state = ProcessState.TERMINATING
        return process

    def dt_state(self, node_id, deployable_type, state, properties=None):
        """
        Handle updates about available instances of deployable types.

        @param node_id: unique instance identifier
        @param deployable_type: type of instance
        @param state: EPU state of instance
        @param properties: Optional properties about this instance
        @return:

        This operation is the recipient of a "subscription" the PD makes to
        DT state updates. Calls to this operation are NOT RPC-style.

        This information is used for two purposes:

            1. To correlate EE agent heartbeats with a DT and various deploy
               information (site, allocation, security groups, etc).

            2. To detect EEs which have been killed due to underlying death
               of a resource (VM).
        """

        if state == InstanceState.RUNNING:
            if node_id not in self.nodes:
                node = DeployedNode(node_id, deployable_type, properties)
                self.nodes[node_id] = node
                log.info("DT resource %s is %s", node_id, state)
                log.debug("nodes: %s", self.nodes)

        elif state in (InstanceState.TERMINATING, InstanceState.TERMINATED):
            # reschedule processes running on node

            node = self.nodes.get(node_id)
            if node is None:
                log.warn("Got dt_state for unknown node %s in state %s",
                         node_id, state)
                return

            # first walk resources and mark ineligible for scheduling
            for resource in node.resources:
                resource.disable()

            # go through resources on this node and reschedule any processes
            for resource in node.resources:
                for upid in resource.processes:

                    process = self.processes.get(upid)
                    if process is None:
                        continue

                    # send a last ditch terminate just in case
                    if process.state < ProcessState.TERMINATED:
                        self.eeagent_client.terminate_process(resource.ee_id,
                                                              upid,
                                                              process.round)

                    if process.state == ProcessState.TERMINATING:

                        #what luck
                        process.state = ProcessState.TERMINATED
                        self.notifier.notify_process(process)

                    elif process.state < ProcessState.TERMINATING:
                        log.debug("Rescheduling process %s from failing node %s",
                                  upid, node_id)

                        process.round += 1
                        process.assigned = None
                        process.state = ProcessState.DIED_REQUESTED
                        self.notifier.notify_process(process)
                        self._matchmake_process(process)
                        self.notifier.notify_process(process)

            del self.nodes[node_id]
            for resource in node.resources:
                del self.resources[resource.ee_id]

    def ee_heartbeart(self, sender, beat):
        """Incoming heartbeat from an EEAgent

        @param sender: ION name of sender
        @param beat: information about running processes
        @return:

        When an EEAgent starts, it immediately begins sending heartbeats to
        the PD. The first received heartbeat will trigger the PD to mark the
        EE as available in its slot tables, and potentially start deploying
        some WAITING process requests.

        The heartbeat message will consist of at least these fields:
            - node id - unique ID for the provisioned resource (VM) the EE runs on
            - timestamp - time heartbeat was generated
            - processes - list of running process IDs
            - slot_count - number of available slots
        """

        node_id = node_id_from_eeagent_name(sender)

        processes = beat['processes']

        resource = self.resources.get(sender)
        if resource is None:
            # first heartbeat from this EE

            node = self.nodes.get(node_id)
            if node is None:
                log.warn("EE heartbeat from unknown node. Still booting? "+
                         "node_id=%s sender=%s known nodes=%s", node_id, sender, self.nodes)

                # TODO I'm thinking the best thing to do here is query EPUM
                # for the state of this node in case the initial dt_state
                # update got lost. Note that we shouldn't go ahead and
                # schedule processes onto this EE until we get the RUNNING
                # dt_state update -- there could be a failure later on in
                # the contextualization process that triggers the node to be
                # terminated.

                return

            if node.properties:
                properties = node.properties.copy()
            else:
                properties = {}

            engine_spec = self.ee_registry.get_engine_by_dt(node.dt)
            slots = engine_spec.slots

            # just making engine type a generic property/constraint for now,
            # until it is clear something more formal is needed.
            properties['engine_type'] = engine_spec.engine_id

            resource = ExecutionEngineResource(node_id, sender, slots, properties)
            self.resources[sender] = resource
            node.resources.append(resource)

            log.info("Got first heartbeat from EEAgent %s on node %s",
                     sender, node_id)

        running_upids = []
        for procstate in processes:
            upid = procstate['upid']
            round = procstate['round']
            state = procstate['state']

            #TODO hack to handle how states are formatted in EEAgent heartbeat
            if isinstance(state, (list,tuple)):
                state = "-".join(str(s) for s in state)

            if state <= ProcessState.RUNNING:
                running_upids.append(upid)

            process = self.processes.get(upid)
            if not process:
                log.warn("EE reports process %s that is unknown!", upid)
                continue

            if round < process.round:
                # skip heartbeat info for processes that are already redeploying
                continue

            if upid in resource.pending:
                resource.pending.remove(upid)

            if state == process.state:
                continue

            if process.state == ProcessState.PENDING and \
               state == ProcessState.RUNNING:

                log.info("Process %s is %s", upid, state)

                # mark as running and notify subscriber
                process.state = ProcessState.RUNNING
                self.notifier.notify_process(process)

            elif state in (ProcessState.TERMINATED, ProcessState.FAILED):

                # process has died in resource. Obvious culprit is that it was
                # killed on request.
                log.info("Process %s is %s", upid, state)

                if process.state == ProcessState.TERMINATING:
                    # mark as terminated and notify subscriber
                    process.state = ProcessState.TERMINATED
                    process.assigned = None
                    self.notifier.notify_process(process)

                # otherwise it needs to be rescheduled
                elif process.state in (ProcessState.PENDING,
                                    ProcessState.RUNNING):

                    process.state = ProcessState.DIED_REQUESTED
                    process.assigned = None
                    process.round += 1
                    self.notifier.notify_process(process)
                    self._matchmake_process(process)

                # send cleanup request to EEAgent now that we have dealt
                # with the dead process
                self.eeagent_client.cleanup_process(sender, upid, round)

        resource.processes = running_upids
        
        if self.queue and resource.available_slots:
            self._consider_resource(resource)

    def dump(self):
        resources = {}
        processes = {}
        state = dict(resources=resources, processes=processes)

        for resource in self.resources.itervalues():
            resource_dict = dict(ee_id=resource.ee_id,
                                 node_id=resource.node_id,
                                 processes=resource.processes,
                                 slot_count=resource.slot_count)
            resources[resource.ee_id] = resource_dict

        for process in self.processes.itervalues():
            process_dict = dict(upid=process.upid, round=process.round,
                                state=process.state,
                                assigned=process.assigned)
            processes[process.upid] = process_dict

        return state

    def _consider_resource(self, resource):
        """Consider a resource that has had new slots become available

        Because we operate in a single-threaded mode in this lightweight
        prototype, we don't need to worry about other half-finished requests.

        @param resource: The resource with new slots
        @return: None
        """
        matched = set()
        for process in ifilter(resource.check_process_match, self.queue):

            if not resource.available_slots:
                break

            matched.add(process.upid)
            self._dispatch_matched_process(process, resource)

        # dumb slow whatever.
        if matched:
            self.queue = [p for p in self.queue if p.upid not in matched]


def match_constraints(constraints, properties):
    """Match process constraints against resource properties

    Simple equality matches for now.
    """
    if constraints is None:
        return True

    for key,value in constraints.iteritems():
        if value is None:
            continue

        if properties is None:
            return False

        advertised = properties.get(key)
        if advertised is None:
            return False

        if isinstance(value,(list,tuple)):
            if not advertised in value:
                return False
        else:
            if advertised != value:
                return False

    return True


