import logging

from epu.epumanagement.conf import *
from epu.states import InstanceState, InstanceHealthState

log = logging.getLogger(__name__)

class EPUMReactor(object):
    """Handles message-driven sub tasks that do not require locks for critical sections.

    The instance of the EPUManagementService process that hosts a particular EPUMReactor instance
    might not be configured to receive messages.  But when it is receiving messages, they all go
    to the EPUMReactor instance.

    See: https://confluence.oceanobservatories.org/display/syseng/CIAD+CEI+OV+Elastic+Computing
    See: https://confluence.oceanobservatories.org/display/CIDev/EPUManagement+Refactor
    """

    def __init__(self, store, subscribers, provisioner_client, epum_client):
        self.store = store
        self.subscribers = subscribers
        self.provisioner_client = provisioner_client
        self.epum_client = epum_client

    def add_domain(self, caller, domain_id, config, subscriber_name=None,
                subscriber_op=None):
        """See: EPUManagement.msg_add_domain()
        """
        # TODO: parameters are from messages, do legality checks here
        # assert that engine_conf['epuworker_type']['sleeper'] is owned by caller
        log.debug("ADD Domain: %s", config)

        self.store.add_domain(caller, domain_id, config,
            subscriber_name=subscriber_name, subscriber_op=subscriber_op)

    def remove_domain(self, caller, domain_id):
        try:
            domain = self.store.get_domain(caller, domain_id)
        except ValueError:
            return None
        if not domain:
            return None

        self.store.remove_domain(caller, domain_id)

    def list_domains(self, caller):
        return self.store.list_domains_by_owner(caller)

    def describe_domain(self, caller, domain_id):
        try:
            domain = self.store.get_domain(caller, domain_id)
        except ValueError:
            return None
        if not domain:
            return None
        domain_desc = dict(name=domain.domain_id,
            config=domain.get_all_config(),
            instances=[i.to_dict() for i in domain.get_instances()])
        return domain_desc

    def reconfigure_domain(self, caller, domain_id, config):
        """See: EPUManagement.msg_reconfigure_domain()
        """
        # TODO: parameters are from messages, do legality checks here
        domain = self.store.get_domain(caller, domain_id)
        if not domain:
            raise ValueError("Domain does not exist: %s" % domain_id)

        if config.has_key(EPUM_CONF_GENERAL):
            domain.add_general_config(config[EPUM_CONF_GENERAL])
        if config.has_key(EPUM_CONF_ENGINE):
            domain.add_engine_config(config[EPUM_CONF_ENGINE])
        if config.has_key(EPUM_CONF_HEALTH):
            domain.add_health_config(config[EPUM_CONF_HEALTH])

    def subscribe_domain(self, caller, domain_id, subscriber_name, subscriber_op):
        """Subscribe to asynchronous state updates for instances of a domain
        """
        domain = self.store.get_domain(caller, domain_id)
        if not domain:
            raise ValueError("Domain does not exist: %s" % domain_id)

        domain.add_subscriber(subscriber_name, subscriber_op)

    def unsubscribe_domain(self, caller, domain_id, subscriber_name):
        """Subscribe to asynchronous state updates for instances of a domain
        """
        domain = self.store.get_domain(caller, domain_id)
        if not domain:
            raise ValueError("Domain does not exist: %s" % domain_id)

        domain.remove_subscriber(subscriber_name)

    def new_sensor_info(self, content):
        """Handle an incoming sensor message

        @param content Raw sensor content
        """

        # TODO: need a new sensor abstraction; have no way of knowing which epu_state to associate this with
        # TODO: sensor API will change, should include a mandatory field for epu (vs. a general sensor)
        raise NotImplementedError
        #epu_state.new_sensor_item(content)

    def new_instance_state(self, content):
        """Handle an incoming instance state message

        @param content Raw instance state content
        """
        try:
            instance_id = content['node_id']
            state = content['state']
        except KeyError:
            log.warn("Got invalid state message: %s", content)
            return

        if instance_id:
            domain = self.store.get_domain_for_instance_id(instance_id)
            if domain:
                log.debug("Got state %s for instance '%s'", state, instance_id)

                instance = domain.get_instance(instance_id)
                domain.new_instance_state(content, previous=instance)

                # The higher level clients of EPUM only see RUNNING or FAILED (or nothing)
                if content['state'] < InstanceState.RUNNING:
                    return
                elif content['state'] == InstanceState.RUNNING:
                    notify_state = InstanceState.RUNNING
                else:
                    notify_state = InstanceState.FAILED
                try:
                    self.subscribers.notify_subscribers(instance, domain, notify_state)
                except Exception, e:
                    log.error("Error notifying subscribers '%s': %s",
                        instance_id, str(e), exc_info=True)

            else:
                log.warn("Unknown Domain for state message for instance '%s'" % instance_id)
        else:
            log.error("Could not parse instance ID from state message: '%s'" % content)

    def new_heartbeat(self, caller, content, timestamp=None):
        """Handle an incoming heartbeat message

        @param caller Name of heartbeat sender (used for responses via ouagent client). If None, uses node_id
        @param content Raw heartbeat content
        @param timestamp For unit tests
        """

        try:
            instance_id = content['node_id']
            state = content['state']
        except KeyError:
            log.error("Got invalid heartbeat message from '%s': %s", caller, content)
            return

        domain = self.store.get_domain_for_instance_id(instance_id)
        if not domain:
            log.error("Unknown Domain for health message for instance '%s'" % instance_id)
            return

        if not domain.is_health_enabled():
            # The instance should not be sending heartbeats if health is disabled
            log.warn("Ignored health message for instance '%s'" % instance_id)
            return

        instance = domain.get_instance(instance_id)
        if not instance:
            log.error("Could not retrieve instance information for '%s'" % instance_id)
            return

        if state == InstanceHealthState.OK:

            if instance.health not in (InstanceHealthState.OK,
                                       InstanceHealthState.ZOMBIE) and \
               instance.state < InstanceState.TERMINATED:

                # Only updated when we receive an OK heartbeat and instance health turned out to
                # be wrong (e.g. it was missing and now we finally hear from it)
                domain.new_instance_health(instance_id, state, caller=caller)

        else:

            # TODO: We've been talking about having an error report that will only say
            #       "x failed" and then OU agent would have an RPC op that allows doctor
            #       to trigger a "get_error_info()" retrieval before killing it
            # But for now we want OU agent to send full error information.
            # The EPUMStore should key error storage off {node_id + error_time}

            if state != instance.health:
                errors = []
                error_time = content.get('error_time')
                err = content.get('error')
                if err:
                    errors.append(err)
                procs = content.get('failed_processes')
                if procs:
                    errors.extend(p.copy() for p in procs)

                domain.new_instance_health(instance_id, state, error_time, errors, caller)

        # Only update this "last heard" timestamp when the other work is committed.  In situations
        # where a heartbeat is re-queued or never ACK'd and the message is picked up by another
        # EPUM worker, the lack of a timestamp update will give the doctor a better chance to
        # catch health issues.
        domain.set_instance_heartbeat_time(instance_id, timestamp)
