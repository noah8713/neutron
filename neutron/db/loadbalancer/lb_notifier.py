from neutron.openstack.common import log as logging
from neutron.db.models_v2 import HasStatusDescription
#from neutron.openstack.common.notifier import api as notifier_api
from neutron.common import rpc as n_rpc
from neutron.services.loadbalancer import agent_scheduler
from neutron.db import db_base_plugin_v2, l3_db
from oslo_config import cfg

__author__ = 'kugandhi'
LOG = logging.getLogger(__name__)


def find_lb_associated_to_pool(pool_id, context):
    lb_agent = agent_scheduler.LbaasAgentSchedulerDbMixin() \
        .get_lbaas_agent_hosting_pool(context, pool_id)
    if lb_agent:
        return lb_agent['agent']['configurations']['floating_ip']


def create_pool_payload(model, context):
    pool_payload = {
        "pool": {
            "name": model.name,
            "id": model.id,
            "description": model.description,
            "lb_ip": find_lb_associated_to_pool(model.id, context),
            "lb_method": model.lb_method,
            "protocol": model.protocol
        }
    }
    return pool_payload


def create_vip_payload(model, context):
    # the import is done inline because there is cyclic dependencies between lb_notifier,
    # loadbalancer_db and loadbalancer_resource_db
    from loadbalancer_resource_db import LoadBalancerResourceDb

    vip_payload = {
        "vip": {
            "name": model.name,
            "id": model.id,
            "address": LoadBalancerResourceDb().get_ip_by_port(context,
                                                               model.port.id),
            "enabled": model.admin_state_up,
            "port": model.protocol_port,
            "protocol": model.protocol,
            "pool": create_pool_payload(LoadBalancerResourceDb()
                                        .get_pool(context, model.pool_id),
                                        context)['pool'],
            "tenant_id": model.tenant_id
        }
    }
    return vip_payload


def create_member_payload(model, context):
    from loadbalancer_resource_db import LoadBalancerResourceDb

    member_payload = {
        "member": {
            "name": model.id,
            "id": model.id,
            "address": model.address,
            "port": model.protocol_port,
            "weight": model.weight,
            "enabled": model.admin_state_up,
            "pool": create_pool_payload(LoadBalancerResourceDb()\
                    .get_pool(context, model.pool_id), context)['pool']
        }
    }
    monitors = []
    from loadbalancer_resource_db import LoadBalancerResourceDb

    monitor_models = LoadBalancerResourceDb() \
        .get_healtmonitors_associated_to_pool(context, model.pool_id)
    for m_model in monitor_models:
        monitors.append(create_health_monitor_payload(m_model,
                                                      context,
                                                      model.pool_id)['monitor'])

    if len(monitors) > 0:
        member_payload['member']['monitors'] = monitors

    return member_payload


def create_health_monitor_payload(model, context, pool_id):
    monitor = {
        "monitor": {
            "name": model.name,
            "id": model.id,
            "type": model.type,
            "delay": model.delay,
            "timeout": model.timeout,
            "down_time": model.max_retries * model.timeout,
            "enabled": model.admin_state_up,
            "lb_ip": find_lb_associated_to_pool(pool_id, context)
        }
    }

    if hasattr(model, "url_path"):
        monitor['monitor']['url'] = model.url_path

    if hasattr(model, "response_string"):
        monitor['monitor']['response_string'] = model.response_string

    return monitor


def create_pool_monitor_assc_payload(model, context):
    from loadbalancer_resource_db import LoadBalancerResourceDb

    assc_data = {
        "data": {
            "pool": create_pool_payload(LoadBalancerResourceDb()
                                        .get_pool(context, model.pool_id),
                                        context)['pool'],
            "monitor": create_health_monitor_payload(LoadBalancerResourceDb()\
                                     .get_healthmonitor_by_id(context,
                                                              model.monitor_id),
                                     context, model.pool_id)['monitor']
        }
    }
    return assc_data


CREATE_ACTION = 'CREATE'
UPDATE_ACTION = 'UPDATE'
DELETE_ACTION = 'DELETE'
PAYLOAD_KEY = 'payload'

# A meta data dictionary that maps object to action and notification topic.
OBJECT_TO_ACTION_AND_TOPIC_DICT = {
    "Pool": {
        CREATE_ACTION: "pool.creation.end",
        DELETE_ACTION: "pool.deletion.end",
        UPDATE_ACTION: "pool.updating.end",
        PAYLOAD_KEY: create_pool_payload

    },
    "Vip": {
        CREATE_ACTION: "vip.creation.end",
        DELETE_ACTION: "vip.deletion.end",
        UPDATE_ACTION: "vip.updating.end",
        PAYLOAD_KEY: create_vip_payload
    },
    "Member": {
        CREATE_ACTION: "member.creation.end",
        DELETE_ACTION: "member.deletion.end",
        UPDATE_ACTION: "member.updating.end",
        PAYLOAD_KEY: create_member_payload
    },
    "Monitor": {
        DELETE_ACTION: "monitor.deletion.end",
        UPDATE_ACTION: "monitor.updating.end",
        PAYLOAD_KEY: create_health_monitor_payload
    },
    "PoolMonitorAssociation": {
        CREATE_ACTION: "pool.monitor.association.end",
        DELETE_ACTION: "pool.monitor.disassociation.end",
        PAYLOAD_KEY: create_pool_monitor_assc_payload
    }
}


def find_action(resource, new_status):
    """
    Determine the action performed based on the status.
    :param resource:
    :param status:
    :return:
    """
    if resource and isinstance(resource, HasStatusDescription):
        old_status = resource.status

        if old_status == new_status:
            return None
        elif old_status == 'PENDING_CREATE' and new_status == 'ACTIVE':
            return CREATE_ACTION
        elif old_status == 'PENDING_UPDATE' and new_status == 'ACTIVE':
            return UPDATE_ACTION
        elif old_status == 'PENDING_DELETE' and new_status is None:
            return DELETE_ACTION
        else:
            return None


def _notify(context, model, new_status, resource):
    action = find_action(resource, new_status)
    if action and resource:
        notification_topic = OBJECT_TO_ACTION_AND_TOPIC_DICT\
                            [model.__name__][action]
        LOG.info('sending a notification [%s] ' % notification_topic)
        if cfg.CONF.lbaas_notification:
            n_rpc.init(cfg.CONF)
            notifier = n_rpc.get_notifier('notifications.info')
            notifier.info(context,
                          notification_topic,
                          OBJECT_TO_ACTION_AND_TOPIC_DICT[model.__name__]\
                 [PAYLOAD_KEY](resource, context))
        else:
            LOG.info('Sending notification has been turned off.')
    else:
        LOG.info('not sending any notification'
                 ' for [%s] entity type.' % (model.__name__))


def send_notification(context, model, model_id, new_status=None):
    from loadbalancer_resource_db import LoadBalancerResourceDb

    resource = LoadBalancerResourceDb().get_resource_by_id(model_id,
                                                           model,
                                                           context)
    _notify(context, model, new_status, resource)


def send_resource_notification(context, model, resource, new_status=None):
    _notify(context, model, new_status, resource)


def update_or_create_notify(method):
    """
    A decorator to send an appropriate lb notifications.
    :param method:
    :return:
    """

    def wrapper(*args, **kwargs):
        model = args[2]
        model_id = args[3]
        new_status = args[4]
        context = args[1]

        # send the notification
        send_notification(context, model, model_id, new_status)

        # Call the decorated method.
        return method(*args, **kwargs)

    return wrapper


def delete_notify(model):
    def delete_notify_wrapper(method):
        def wrapper(*args, **kwargs):
            context = args[1]
            model_id = args[2]

            # send the notification
            send_notification(context, model, model_id)

            return method(*args, **kwargs)

        return wrapper

    return delete_notify_wrapper


def notify_pool_monitor_association(pool_monitor_association_model):
    def notify_pool_monitor_association_wrapper(method):
        def wrapper(*args, **kwargs):
            context = args[1]
            monitor_id = args[2]
            pool_id = args[3]

            status = None
            # status only required on updates.
            if method.__name__.startswith('update'):
                status = args[4]

            from loadbalancer_resource_db import LoadBalancerResourceDb

            pool_monitor_assc = LoadBalancerResourceDb() \
                .get_pool_monitor_association(context,
                                              pool_id,
                                              monitor_id,
                                              pool_monitor_association_model)

            # send notification
            send_resource_notification(context, pool_monitor_association_model,
                                       pool_monitor_assc, status)

            return method(*args, **kwargs)

        return wrapper

    return notify_pool_monitor_association_wrapper
