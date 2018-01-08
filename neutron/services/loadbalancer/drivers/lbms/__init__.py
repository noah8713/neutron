from neutron.openstack.common import log as logging
from oslo_config import cfg

__author__ = 'kugandhi'

LBMS_DRIVER_OPTS = [
    cfg.StrOpt(
        'lbms_uri',
        help=_('The URL to reach the LBMS endpoint.'),
    ),
    cfg.StrOpt(
        'lbms_username',
        help=_('Username to invoke LBMS API.'),
    ),
    cfg.StrOpt(
        'lbms_password',
        help=_('Password to invoke LBMS API.'),
    ),
    cfg.StrOpt(
        'lbms_tenant',
        help=_('lbms KS tenant')
    ),
    cfg.IntOpt(
        'report_interval',
        default=60,
        help=_('Check the interval for the lbs in LBMS in seconds')
    ),
    cfg.StrOpt(
        'lbms_loadbalancer_pool_scheduler_driver',
        default='neutron.services.loadbalancer.drivers.lbms.lbms_scheduler.LbmsScheduler'
    ),
    cfg.StrOpt(
        'keystone_token_regeneration_interval',
        default='39600',
        help=_('keystone token regeneration interval in seconds same as 11 hrs'),
    ),
    cfg.StrOpt(
        'request_max_retries',
        default='5',
        help=_('Max number of request retries'),
    ),
    cfg.StrOpt(
        'request_retries_interval',
        default='5',
        help=_('Max number of request retries'),
    ),
    cfg.StrOpt(
        'lbms_job_max_retries',
        default='60',
        help=_('Max number of request retries'),
    ),
    cfg.StrOpt(
        'lbms_job_retires_interval',
        default='5',
        help=_('Interval for lbms job check'),
    ),
    cfg.StrOpt(
        'lbms_pending_job_max_wait',
        default='1800',
        help=_('Interval until pending jobs are retried'),
    ),
    cfg.StrOpt(
        'lbmsdriver_db_wait_time_to_get_lock',
        default='50',
        help=_('Wait time until getting the lock in lbmsjob db'),
    ),
    cfg.StrOpt(
        'lbmsdriver_db_lock_report',
        default='20',
        help=_('Interval for lock update'),
    ),
    cfg.StrOpt(
        'pending_job_interval',
        default='60',
        help=_('pending_job_interval'),
    )

]

cfg.CONF.register_opts(LBMS_DRIVER_OPTS, 'lbms_driver')
