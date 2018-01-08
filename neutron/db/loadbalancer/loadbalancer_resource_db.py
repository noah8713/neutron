from loadbalancer_db import HealthMonitor, Pool, PoolMonitorAssociation
from neutron.db import db_base_plugin_v2, l3_db
from sqlalchemy.orm import exc
from neutron.openstack.common import log as logging

LOG = logging.getLogger(__name__)

__author__ = 'kugandhi'

class LoadBalancerResourceDb(db_base_plugin_v2.CommonDbMixin,
                             l3_db.L3_NAT_db_mixin):

    def get_resource_by_id(self, resource_id, model, context):

        with context.session.begin(subtransactions=True):
            try:
                r = self._get_by_id(context, model, resource_id)
            except exc.NoResultFound:
                LOG.warn('The resource [%s] with id [%s] '
                         'is not found in the db.' % (model, resource_id))
                return None
            return r

    def get_healthmonitor_by_id(self, context, monitor_id):
        return self.get_resource_by_id(monitor_id, HealthMonitor, context)

    def get_healtmonitors_associated_to_pool(self, context, pool_id):
        monitors = []
        pool = self.get_resource_by_id(pool_id, Pool, context)
        for pool_monitor_bindings in pool.monitors:
            monitors.append(self
                .get_resource_by_id(pool_monitor_bindings.monitor_id,
                                    HealthMonitor, context))
        return monitors

    def get_pool(self, context, pool_id):
        return self.get_resource_by_id(pool_id, Pool, context)

    def get_pool_monitor_association(self, context, pool_id, monitor_id,
                                     pool_monitor_association_model):

        with context.session.begin(subtransactions=True):
            try:
                query = self._model_query(context,
                                          pool_monitor_association_model)
                pool_monitor_assc = query\
                .filter(pool_monitor_association_model.pool_id == pool_id,
                        pool_monitor_association_model.monitor_id == monitor_id)\
                .one()
                return pool_monitor_assc
            except Exception as ex:
                LOG.warn('There is no pool monitor binding between pool '\
                         '[%s] and monitor [%s]' % (pool_id, monitor_id))
                LOG.exception(ex)
                return None



