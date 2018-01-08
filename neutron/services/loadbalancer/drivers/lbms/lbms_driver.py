import neutron.services.loadbalancer.drivers.abstract_driver as abst_driver
import neutron.services.loadbalancer.drivers.abstract_bulk_driver as abst_bulk_driver
import neutron.services.loadbalancer.drivers.abstract_ssl_extension_driver as abst_ssl_ext
import neutron.services.loadbalancer.agent_scheduler as base_scheduler
from neutron.extensions import bulkloadbalancer
import neutron.services.loadbalancer.drivers.lbms.lbms_client as lbms_client
from neutron.openstack.common import log as logging
from neutron.openstack.common import importutils
from neutron.openstack.common import timeutils
from oslo_config import cfg
from neutron.db.loadbalancer import loadbalancer_db as lb_db
from neutron.db.loadbalancer import lbmsdriver_db as lbmsdriver_db
from neutron.plugins.common import constants

from neutron.extensions import lbaas_agentscheduler
from sqlalchemy.orm import joinedload
import thread
import json
from neutron.openstack.common import loopingcall
from neutron import context as n_ctx
import socket
LOG = logging.getLogger(__name__)

__author__ = 'kugandhi'

LBMS_AGENT_BINARY = 'lbms-lbaas-agent'

class LbmsDriver(abst_driver.LoadBalancerAbstractDriver,
                 abst_bulk_driver.LBaaSAbstractBulkDriver,
                 abst_ssl_ext.LBaaSAbstractSSLDriver):

    def __init__(self, plugin):
        self.lbms_client_api = lbms_client.LbmsClient()
        self.plugin = plugin
        LOG.info('starting the lbms driver')
        self.pool_scheduler = importutils.import_object(
            cfg.CONF.lbms_driver['lbms_loadbalancer_pool_scheduler_driver'], plugin)
        lbms_pending_job_scheduler = LbmsPendingJobScheduler(plugin, self.pool_scheduler)


    def create_pool(self, context, pool):
        lbmsdriverjob_db = self._save_lbmsdriver_job(context=context, action="create_pool", pool=pool)
        thread.start_new_thread(create_pool,
                                 (self.plugin, self.lbms_client_api,
                                  self.pool_scheduler, context, pool, lbmsdriverjob_db['id']))


    def update_pool(self, context, old_pool, pool):
        lbmsdriverjob_db = self._save_lbmsdriver_job(context=context, action="update_pool", old_pool=old_pool, pool=pool)
        thread.start_new_thread(update_pool,
                                (self.plugin, self.lbms_client_api, context, old_pool, pool, lbmsdriverjob_db['id']))

    def delete_pool(self, context, pool):
        lbmsdriverjob_db = self._save_lbmsdriver_job(context=context, action="delete_pool", pool=pool)
        thread.start_new_thread(delete_pool,
                                (self.plugin, self.lbms_client_api, context, pool, lbmsdriverjob_db['id']))

    def create_pool_health_monitor(self, context,
                                   health_monitor,
                                   pool_id):
        lbmsdriverjob_db = self._save_lbmsdriver_job(context=context, action="create_pool_health_monitor",
                                                     health_monitor=health_monitor, pool_id=pool_id)
        thread.start_new_thread(create_pool_health_monitor,
        (self.plugin, self.lbms_client_api, context, health_monitor, pool_id, lbmsdriverjob_db['id']))

    def update_pool_health_monitor(self, context,
                                   old_health_monitor,
                                   health_monitor,
                                   pool_id):
        lbmsdriverjob_db = self._save_lbmsdriver_job(context=context, action="update_pool_health_monitor",
                                                     old_health_monitor=old_health_monitor,
                                                     health_monitor=health_monitor, pool_id=pool_id)
        thread.start_new_thread(update_pool_health_monitor,
                                (self.plugin, self.lbms_client_api, context,
                                 old_health_monitor,health_monitor, pool_id, lbmsdriverjob_db['id']))

    def delete_pool_health_monitor(self, context,
                                   health_monitor,
                                   pool_id):
        lbmsdriverjob_db = self._save_lbmsdriver_job(context=context, action="delete_pool_health_monitor",
                                                     health_monitor=health_monitor, pool_id=pool_id)
        thread.start_new_thread(delete_pool_health_monitor,
                               (self.plugin, self.lbms_client_api, context,
                                health_monitor, pool_id, lbmsdriverjob_db['id']))

    def create_member(self, context, member):
        members = [member]
        lbmsdriverjob_db = self._save_lbmsdriver_job(context=context, action="create_or_update_members",
                                                     members=members)
        thread.start_new_thread(create_or_update_members,
                                (self.plugin, self.lbms_client_api, context, members, lbmsdriverjob_db['id']))

    def update_member(self, context, old_member, member):
        members=[member]
        lbmsdriverjob_db = self._save_lbmsdriver_job(context=context, action="create_or_update_members",
                                                      members=members)
        thread.start_new_thread(create_or_update_members,
                               (self.plugin, self.lbms_client_api, context, members, lbmsdriverjob_db['id']))

    def delete_member(self, context, member):
        members = [member]
        lbmsdriverjob_db = self._save_lbmsdriver_job(context=context, action="delete_members",
                                                     members=members)
        thread.start_new_thread(delete_members,
                               (self.plugin, self.lbms_client_api, context, members, lbmsdriverjob_db['id']))

    def create_vip(self, context, vip):
        lbmsdriverjob_db = self._save_lbmsdriver_job(context=context, action="create_vip",
                                                     vip=vip)
        thread.start_new_thread(create_vip,
                                (self.plugin, self.lbms_client_api, context, vip, lbmsdriverjob_db['id']))


    def update_vip(self, context, old_vip, vip):
        lbmsdriverjob_db = self._save_lbmsdriver_job(context=context, action="update_vip",
                                                     old_vip=old_vip, vip=vip)
        thread.start_new_thread(update_vip, (self.plugin,
                                self.lbms_client_api, context, old_vip, vip, lbmsdriverjob_db['id']))


    def delete_vip(self, context, vip):
        lbmsdriverjob_db = self._save_lbmsdriver_job(context=context, action="delete_vip",
                                                     vip=vip)
        thread.start_new_thread(delete_vip,
                             (self.plugin, self.lbms_client_api, context, vip, lbmsdriverjob_db['id']))


    def stats(self, context, pool_id):
        pass

    def create_members(self, context, members):
        lbmsdriverjob_db = self._save_lbmsdriver_job(context=context, action="create_or_update_members",
                                                     members=members)
        thread.start_new_thread(create_or_update_members,
                                (self.plugin, self.lbms_client_api, context, members, lbmsdriverjob_db['id']))

    def update_members(self, context, old_members, members):
        lbmsdriverjob_db = self._save_lbmsdriver_job(context=context, action="create_or_update_members",
                                                     members=members)
        thread.start_new_thread(create_or_update_members,
                                (self.plugin, self.lbms_client_api, context, members, lbmsdriverjob_db['id']))

    def delete_members(self, context, members):
        lbmsdriverjob_db = self._save_lbmsdriver_job(context=context, action="delete_members",
                                                     members=members)
        thread.start_new_thread(delete_members,
                                (self.plugin, self.lbms_client_api, context, members, lbmsdriverjob_db['id']))


    def create_vip_ssl_certificate_association(self, context, assoc_db_record, ssl_profile_db_record,
                                               cert_db_record, key_db_record,
                                               vip_db_record, cert_chain_db_record=None):
        lbmsdriverjob_db = self._save_lbmsdriver_job(context=context, action="create_vip_ssl_certificate_association",
                                                     assoc_db_record=assoc_db_record,
                                                     cert_db_record=cert_db_record,
                                                     key_db_record=key_db_record,
                                                     vip_db_record=vip_db_record)
        thread.start_new_thread(create_vip_ssl_certificate_association,
                                (self.plugin, self.lbms_client_api, context,
                                 assoc_db_record, cert_db_record, key_db_record,
                                 vip_db_record, lbmsdriverjob_db['id']))


    def delete_vip_ssl_certificate_association(self, context, assoc_db_record, ssl_profile_db_record,
                                               cert_db_record, key_db_record,
                                               vip_db_record, cert_chain_db_record=None,
                                               cert_delete_flag=True,
                                               cert_chain_delete_flag=True,
                                               key_delete_flag=True):

        lbmsdriverjob_db = self._save_lbmsdriver_job(context=context, action="delete_vip_ssl_certificate_association",
                                                     assoc_db_record=assoc_db_record,
                                                     cert_db_record=cert_db_record,
                                                     vip_db_record=vip_db_record)
        thread.start_new_thread(delete_vip_ssl_certificate_association,
                                (self.plugin, self.lbms_client_api, context, assoc_db_record,
                                 cert_db_record, vip_db_record, lbmsdriverjob_db['id']))


    def update_vip_ssl_certificate_association(
            self, context, assoc_db, cert_db, key_db, vip_db,
            cert_chain_db=None):
        # This can achived by calling delete vip assocation and create vip assocation in seq
        pass

    def update_ssl_certificate(self, context, ssl_certificate, vip):
        pass


    def _save_lbmsdriver_job(self, context, action, **kwargs):
        lbmsdb = lbmsdriver_db.LBMSDriverDbMixin()
        LOG.info('kwargs %s', kwargs)
        return lbmsdb.create_job(context, action, json.dumps(kwargs))




class LbmsPendingJobScheduler():

    def __init__(self, plugin, pool_scheduler):
        self.lbms_job_max_retries = \
            int(cfg.CONF.lbms_driver['lbms_job_max_retries'])
        self.lbms_job_retries_interval = \
            int(cfg.CONF.lbms_driver['lbms_job_retires_interval'])
        self.lbms_pending_job_max_wait = \
            int(cfg.CONF.lbms_driver['lbms_pending_job_max_wait'])
        self.lbmsdriver_db_wait_time_to_get_lock = \
            int(cfg.CONF.lbms_driver['lbmsdriver_db_wait_time_to_get_lock'])
        lbmsdriver_db_lock_report = \
            int(cfg.CONF.lbms_driver['lbmsdriver_db_lock_report'])
        pending_job_interval = \
            int(cfg.CONF.lbms_driver['pending_job_interval'])


        LOG.info('initiating the pending job scheduler')
        self.plugin=plugin
        self.pool_scheduler = pool_scheduler
        self.lbms_client_api = lbms_client.LbmsClient()

        if pending_job_interval:
            process_jobs = loopingcall.FixedIntervalLoopingCall(self.process_pending_jobs)
            process_jobs.start(interval=pending_job_interval)

        if lbmsdriver_db_lock_report:
            process_jobs = loopingcall.FixedIntervalLoopingCall(self.update_lock_record)
            process_jobs.start(interval=lbmsdriver_db_lock_report)

    def process_pending_jobs(self):
        try :
            LOG.info('starting the pending job scheduler')
            lbmsdb = lbmsdriver_db.LBMSDriverDbMixin()
            jobs = lbmsdb.get_lbmsdriver_jobs(n_ctx.get_admin_context())
            # Get all jobs after the first try is failed
            pending_jobs = [x for x in jobs if (self.is_job_pending(x['created_at']) and x['id'] != '1')]
            # Check wheather this instance has lock
            if not lbmsdb.has_lock(n_ctx.get_admin_context(), socket.gethostname()):
                LOG.info('unable to get the lock')
                return

            LOG.info('This instance has lock')
            # For each job, call the method which is in the action field
            # Arguments is the combination of  data, plugin client_api, context, job_id
            for job in pending_jobs:
                try :
                    LOG.info('starting the job %s' % job)
                    kwargs = json.loads(job['data'])
                    kwargs['plugin'] = self.plugin
                    if (job['action'] == "create_pool"):
                        kwargs['pool_scheduler'] = self.pool_scheduler

                    kwargs['lbms_client_api'] = self.lbms_client_api
                    kwargs['context'] = n_ctx.get_admin_context()
                    kwargs['job_id'] = job['id']
                    LOG.info(kwargs)
                    globals()[job['action']](**kwargs)

                except Exception, e:
                    LOG.error("retry of job %s failed" % job['id'])
                    LOG.error("exception %s" % str(e))

        except Exception, e:
            LOG.error("Unable to process pending jobs")


    def update_lock_record(self):
        try :
            LOG.info('updating the lock record')
            lbmsdb = lbmsdriver_db.LBMSDriverDbMixin()
            lbmsdb.create_or_update_lock_record(n_ctx.get_admin_context(),
                                                socket.gethostname(),self.lbmsdriver_db_wait_time_to_get_lock)
        except Exception, e:
            LOG.error("Unable to update the lock record")


    def is_job_pending(self, created_by):
        # Get jobs between first try and 30 min. All other jobs are not valid for retry
        if (timeutils.is_older_than(created_by, self.lbms_job_max_retries * self.lbms_job_retries_interval) \
                and (not timeutils.is_older_than(created_by, self.lbms_pending_job_max_wait))):

           return True
        else:
            return False




def create_pool(plugin, lbms_client_api, pool_scheduler, context, pool, job_id):
    LOG.info('calling create pool %s' % pool)
    try:
        agent = pool_scheduler.schedule(plugin, context, pool)
        if not agent:
            raise lbaas_agentscheduler.NoEligibleLbaasAgent(pool_id=pool['id'])
        lbms_client_api.create_pool(agent.host, pool)
        plugin.update_status(
            context,
            lb_db.Pool,
            pool['id'],
            constants.ACTIVE,
            "lb="+ agent.host)
    except Exception, e:
        LOG.error("Unexpected error in creating pool: %s" % e)
        plugin.update_status(
            context,
            lb_db.Pool,
            pool['id'],
            constants.ERROR,
            "lb=" + agent.host)
    _delete_lbmsdriver_job(context, job_id)


def update_pool(plugin, lbms_client_api, context, old_pool, pool, job_id):
    LOG.info('update pool %s' % pool)
    try:
        agent = _get_lbms_agent_hosting_pool(context, pool)
        if not agent:
            raise lbaas_agentscheduler.NoEligibleLbaasAgent(pool_id=pool['id'])
        _set_monitors_for_pool(plugin, context, pool)
        LOG.info('pool with monitor names %s' % pool)
        lbms_client_api.update_pool(agent.host, pool)
        plugin.update_status(
            context,
            lb_db.Pool,
            pool['id'],
            constants.ACTIVE,
            None)
    except Exception, e:
        LOG.error("Unexpected error in updating pool: %s" % e)
        plugin.update_status(
            context,
            lb_db.Pool,
            pool['id'],
            constants.ERROR,
            None)
    _delete_lbmsdriver_job(context, job_id)


def delete_pool(plugin, lbms_client_api, context, pool, job_id):
    LOG.info('calling delete pool %s' % pool)
    try:
        agent = _get_lbms_agent_hosting_pool(context, pool)
        if not agent:
            raise lbaas_agentscheduler.NoEligibleLbaasAgent(pool_id=pool['id'])
        lbms_client_api.delete_pool(agent.host, pool)
        plugin._delete_db_pool(context, pool['id'])

    except Exception, e:
        LOG.error("Unexpected error in deleting pool: %s" % e)
        plugin.update_status(
            context,
            lb_db.Pool,
            pool['id'],
            constants.ERROR,
            None)
    _delete_lbmsdriver_job(context, job_id)

def create_pool_health_monitor(plugin, lbms_client_api, context, health_monitor, pool_id, job_id):
    LOG.info('calling create healthmonitor %s' % health_monitor)
    try:
        pool = _get_pool(plugin, context, pool_id=pool_id)
        LOG.info('pool %s'% pool)
        agent = _get_lbms_agent_hosting_pool(context, pool)
        if not agent:
            raise lbaas_agentscheduler.NoEligibleLbaasAgent(pool_id=pool['id'])
        lbms_client_api.create_monitor(agent.host, health_monitor)
        _set_monitors_for_pool(plugin, context, pool, health_monitor)
        LOG.info('pool with monitor names %s' % pool)
        lbms_client_api.update_pool(agent.host, pool)
        plugin.update_pool_health_monitor(
            context,
            health_monitor['id'],
            pool['id'],
            constants.ACTIVE,
            None)

    except Exception, e:
        LOG.error("Unexpected error in adding health monitor: %s" % e)
        plugin.update_pool_health_monitor(
            context,
            health_monitor['id'],
            pool['id'],
            constants.ERROR,
            None)
    _delete_lbmsdriver_job(context, job_id)

def update_pool_health_monitor(plugin, lbms_client_api, context, old_health_monitor, health_monitor, pool_id, job_id):
    LOG.info('update monitor %s' % health_monitor)
    try:
        pool = _get_pool(plugin, context, pool_id=pool_id)
        agent = _get_lbms_agent_hosting_pool(context, pool)
        if not agent:
            raise lbaas_agentscheduler.NoEligibleLbaasAgent(pool_id=pool['id'])
        _set_monitors_for_pool(plugin, context, pool)
        LOG.info('pool with monitor names %s' % pool)
        lbms_client_api.update_monitor(agent.host, health_monitor)

    except Exception, e:
        # There is no status where it can update the error. So let the client know
        # about the issue
        LOG.error("Unexpected error in updating health monitor: %s" % e)

    _delete_lbmsdriver_job(context, job_id)


def delete_pool_health_monitor(plugin, lbms_client_api, context, health_monitor, pool_id, job_id):
    LOG.info('calling delete healthmonitor %s' % health_monitor)
    try:
        pool = _get_pool(plugin, context, pool_id=pool_id)
        LOG.info('pool %s'% pool)
        agent = _get_lbms_agent_hosting_pool(context, pool)
        if not agent:
            raise lbaas_agentscheduler.NoEligibleLbaasAgent(pool_id=pool['id'])
        # Remove the health monitor from the pool and
        # then delete the monitor
        lbms_client_api.remove_monitor_from_pool(agent.host, pool, health_monitor)
        plugin._delete_db_pool_health_monitor(
            context,
            health_monitor['id'],
            pool['id'])
        try :
            if _check_monitor_deletion_pre_conditions(context, health_monitor):
                # There is a chance that delete monitor can still fail even after checking in LBaaS DB
                # The reason is if the monitor is used outside of lbaas
                lbms_client_api.delete_monitor(agent.host, health_monitor)

        except Exception, e:
            LOG.info("Unable to delete the monitor. Maybe the monitor is "
                     "associated with other pools %s" % e)

    except Exception, e:
        LOG.error("Unexpected error in deleting health monitor: %s" % e)
        plugin.update_pool_health_monitor(
            context,
            health_monitor['id'],
            pool['id'],
            constants.ERROR,
            None)
    _delete_lbmsdriver_job(context, job_id)


def create_vip(plugin, lbms_client_api, context, vip, job_id):
    LOG.info('calling create vip %s' % vip)
    try:
        pool = _get_pool(plugin, context, pool_id=vip['pool_id'])
        LOG.info('pool %s'% pool)
        agent = _get_lbms_agent_hosting_pool(context, pool)
        if not agent:
            raise lbaas_agentscheduler.NoEligibleLbaasAgent(pool_id=pool['id'])
        lbms_client_api.create_vip(agent.host, vip, pool)
        plugin.update_status(
            context,
            lb_db.Vip,
            vip['id'],
            constants.ACTIVE,
            None)
    except Exception, e:
        LOG.error("Unexpected error in creating vip: %s" % e)
        plugin.update_status(
            context,
            lb_db.Vip,
            vip['id'],
            constants.ERROR,
            None)

    _delete_lbmsdriver_job(context, job_id)


def update_vip(plugin, lbms_client_api, context, old_vip, vip, job_id):
    LOG.info('update vip %s' % vip)
    try:
        pool = _get_pool(plugin, context, pool_id=vip['pool_id'])
        LOG.info('pool %s' % pool)
        agent = _get_lbms_agent_hosting_pool(context, pool)
        if not agent:
            raise lbaas_agentscheduler.NoEligibleLbaasAgent(pool_id=pool['id'])

        lbms_client_api.update_vip(agent.host, vip, pool)
        plugin.update_status(
            context,
            lb_db.Vip,
            vip['id'],
            constants.ACTIVE,
            None)
    except Exception, e:
        LOG.error("Unexpected error in updating pool: %s" % e)
        plugin.update_status(
            context,
            lb_db.Vip,
            vip['id'],
            constants.ERROR,
            None)

    _delete_lbmsdriver_job(context, job_id)


def delete_vip(plugin, lbms_client_api, context, vip, job_id):
    LOG.info('calling delete vip %s' % vip)
    try:
        pool = _get_pool(plugin, context, pool_id=vip['pool_id'])
        LOG.info('pool %s'% pool)
        agent = _get_lbms_agent_hosting_pool(context, pool)
        if not agent:
            raise lbaas_agentscheduler.NoEligibleLbaasAgent(pool_id=pool['id'])
        lbms_client_api.delete_vip(agent.host, vip)
        plugin._delete_db_vip(
            context,
            vip['id']
            )
    except Exception, e:
        LOG.error("Unexpected error in deleting vip: %s" % e)
        plugin.update_status(
            context,
            lb_db.Vip,
            vip['id'],
            constants.ERROR,
            None)

    _delete_lbmsdriver_job(context, job_id)


def create_or_update_members(plugin, lbms_client_api, context, members, job_id):
    LOG.info('calling create or update members %s' % members)
    try:
        pool = _get_pool(plugin, context, pool_id=members[0]['pool_id'])
        LOG.info('pool %s'% pool)
        agent = _get_lbms_agent_hosting_pool(context, pool)
        if not agent:
            raise lbaas_agentscheduler.NoEligibleLbaasAgent(pool_id=pool['id'])
        _set_monitors_for_pool(plugin, context, pool)
        LOG.info('pool with monitor names %s' % pool)
        lbms_client_api.create_or_update_members(agent.host, pool, members)
        with context.session.begin(subtransactions=True):
            for member in members:
                plugin.update_status(
                    context,
                    lb_db.Member,
                    member['id'],
                    constants.ACTIVE,
                    None)
    except Exception, e:
        LOG.error("Unexpected error in creating member: %s" % e)
        with context.session.begin(subtransactions=True):
            for member in members:
                plugin.update_status(
                    context,
                    lb_db.Member,
                    member['id'],
                    constants.ERROR,
                    None)

    _delete_lbmsdriver_job(context, job_id)

def delete_members(plugin, lbms_client_api, context, members, job_id):
    LOG.info('calling delete_members %s' % members)
    try:
        pool = _get_pool(plugin, context, pool_id=members[0]['pool_id'])
        LOG.info('pool %s'% pool)
        agent = _get_lbms_agent_hosting_pool(context, pool)
        if not agent:
            raise lbaas_agentscheduler.NoEligibleLbaasAgent(pool_id=pool['id'])

        lbms_client_api.delete_members(agent.host, pool, members)
        with context.session.begin(subtransactions=True):
            for member in members:
                plugin._delete_db_member(
                    context,
                    member['id'],
                )
    except Exception, e:
        LOG.error("Unexpected error in creating member: %s" % e)
        with context.session.begin(subtransactions=True):
            for member in members:
                plugin.update_status(
                    context,
                    lb_db.Member,
                    member['id'],
                    constants.ERROR,
                    None)

    _delete_lbmsdriver_job(context, job_id)

def create_vip_ssl_certificate_association(plugin, lbms_client_api, context, assoc_db_record,
                                           cert_db_record, key_db_record,
                                           vip_db_record,  job_id):

    LOG.info('calling create_vip_ssl_certificate_association %s' % vip_db_record['pool_id'])
    try:
        pool = _get_pool(plugin, context, pool_id=vip_db_record['pool_id'])
        LOG.info('pool %s' % pool)
        agent = _get_lbms_agent_hosting_pool(context, pool)
        if not agent:
            raise lbaas_agentscheduler.NoEligibleLbaasAgent(pool_id=pool['id'])

        lbms_client_api.create_vip_ssl_certificate_association(agent.host, cert_db_record,
                                                               key_db_record, vip_db_record)
        plugin.update_vip_ssl_cert_assoc_status(context, assoc_db_record['id'],
                                                constants.ACTIVE, None, None)
    except Exception, e:
        LOG.error("Unexpected error in create_vip_ssl_certificate_association: %s" % e)
        plugin.update_vip_ssl_cert_assoc_status(context, assoc_db_record['id'],
                                                constants.ERROR, None, None)

    _delete_lbmsdriver_job(context, job_id)


def delete_vip_ssl_certificate_association(plugin, lbms_client_api, context, assoc_db_record,
                                           cert_db_record, vip_db_record, job_id):

    LOG.info('calling delete_vip_ssl_certificate_association %s' % vip_db_record['pool_id'])
    try:
        pool = _get_pool(plugin, context, pool_id=vip_db_record['pool_id'])
        LOG.info('pool %s' % pool)
        agent = _get_lbms_agent_hosting_pool(context, pool)
        if not agent:
            raise lbaas_agentscheduler.NoEligibleLbaasAgent(pool_id=pool['id'])

        lbms_client_api.delete_vip_ssl_certificate_association(agent.host, cert_db_record,
                                                               vip_db_record)
        plugin.delete_vip_ssl_cert_assoc(context, assoc_db_record['id'])

    except Exception, e:
        LOG.error("Unexpected error in delete_vip_ssl_certificate_association: %s" % e)
        plugin.update_vip_ssl_cert_assoc_status(context, assoc_db_record['id'],
                                                constants.ERROR, None, None)

    _delete_lbmsdriver_job(context, job_id)

def _get_pool(
        plugin, context, pool_id=None):
    try:
        pool = plugin.get_pool(context, pool_id)
    except:
        LOG.error("get_service_by_pool_id: Pool not found %s" %
                  pool_id)
        return None

    return pool

def _set_monitors_for_pool(plugin, context, pool, current_health_monitor = None):
    healthmonitor_names =[]
    for healthmonitor_status in pool['health_monitors_status']:
        # Add the currently added monitor as well as all active ones
        if (healthmonitor_status['status'] == constants.ACTIVE) \
                or (current_health_monitor != None and
                            current_health_monitor['id'] == healthmonitor_status['monitor_id']):
            healthmonitor = plugin.get_health_monitor(context, healthmonitor_status['monitor_id'])
            healthmonitor_names.append(healthmonitor['name'])

    pool['health_monitors'] = healthmonitor_names


def _check_monitor_deletion_pre_conditions(context, monitor):
    LOG.info('monitor id %s' % monitor)
    pool_monitor_association = context.session.query(lb_db.PoolMonitorAssociation)\
        .filter_by(monitor_id=monitor['id']).first()
    LOG.info('pool_monitor_association %s' % pool_monitor_association)
    if pool_monitor_association:
        LOG.info('Cannot delete the health monitor pool. It is associated with pool %s' % pool_monitor_association['pool_id'])
        return False
    else:
        return True


def _get_lbms_agent_hosting_pool(context, pool):
    query = context.session.query(base_scheduler.PoolLoadbalancerAgentBinding)
    query = query.options(joinedload('agent'))
    binding = query.get(pool['id'])

    if (binding and binding.agent.is_active
        and binding.agent.admin_state_up):
        LOG.info('selected the agent=%s' % binding.agent.host)
        return binding.agent


def _delete_lbmsdriver_job(context, job_id):
    LOG.info("deleting the lbmsdriver job %s" % job_id)
    lbmsdb = lbmsdriver_db.LBMSDriverDbMixin()
    lbmsdb.delete_job(context, job_id)




