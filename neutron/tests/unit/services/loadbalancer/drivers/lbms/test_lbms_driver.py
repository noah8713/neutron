
import mock
import neutron.services.loadbalancer.drivers.lbms.lbms_driver as lbms
import neutron.db.agents_db as agents_db
from neutron.db.loadbalancer import loadbalancer_db as lb_db
from neutron.plugins.common import constants
from neutron.tests.unit.db.loadbalancer.test_db_loadbalancer import LoadBalancerPluginDbTestCase
from neutron.tests.unit.db.loadbalancer.test_db_loadbalancer import LoadBalancerMockValidateResourceDeleteMixin


class LoadBalancerLBMSDriverTestCase(LoadBalancerPluginDbTestCase, LoadBalancerMockValidateResourceDeleteMixin):

    def setUp(self, core_plugin=None, lb_plugin=None, lbaas_provider=None,
              ext_mgr=None):
        super(LoadBalancerLBMSDriverTestCase, self).setUp(core_plugin=core_plugin, lb_plugin=lb_plugin,
                                                          lbaas_provider=lbaas_provider, ext_mgr=ext_mgr)
        self.set_default_mock_patch()

    def test_create_pool(self):
        with mock.patch('neutron.services.loadbalancer.drivers.lbms.lbms_client.LbmsClient') as lbms_client:
            with mock.patch('neutron.services.loadbalancer.drivers.lbms.lbms_scheduler.LbmsScheduler') as lbms_schduler:
                with mock.patch(
                        'neutron.services.loadbalancer.drivers.common.agent_driver_base.LoadBalancerCallbacks') as plugin:
                    lbms_driver = lbms.LbmsDriver(plugin)

                    agent = agents_db.Agent()
                    agent.id = 'agent_id'
                    agent.host= 'host'
                    lbms_schduler.schedule.return_value = agent

                    pool = dict()
                    pool['id']  = '1'

                    lbms_driver.create_pool(None, pool)
                    plugin.update_status.assert_called_with(
                        None,
                        lb_db.Pool,
                        pool['id'],
                        constants.ACTIVE,
                        None)


    def test_no_agent_eligible(self):
        with mock.patch('neutron.services.loadbalancer.drivers.lbms.lbms_client.LbmsClient') as lbms_client:
            with mock.patch('neutron.services.loadbalancer.drivers.lbms.lbms_scheduler.LbmsScheduler') as lbms_schduler:
                with mock.patch(
                        'neutron.services.loadbalancer.drivers.common.agent_driver_base.LoadBalancerCallbacks') as plugin:
                    lbms_driver = lbms.LbmsDriver(plugin)
                    with mock.patch.object(
                            lbms_driver, '_get_lbms_agent_hosting_pool') as get_agent:

                        get_agent.return_value = None
                        vip = dict()
                        vip['pool_id'] = 'pool_id_1'
                        vip['id'] = 'vip_id_1'

                        lbms_driver.create_vip(None, vip)
                        plugin.update_status.assert_called_with(
                            None,
                            lb_db.Vip,
                            vip['id'],
                            constants.ERROR,
                            None)

    def test_create_member(self):
        with mock.patch('neutron.services.loadbalancer.drivers.lbms.lbms_client.LbmsClient') as lbms_client:
            with mock.patch('neutron.services.loadbalancer.drivers.lbms.lbms_scheduler.LbmsScheduler') as lbms_schduler:
                with mock.patch(
                        'neutron.services.loadbalancer.drivers.common.agent_driver_base.LoadBalancerCallbacks') as plugin:

                    lbms_driver = lbms.LbmsDriver(plugin)
                    with mock.patch.object(
                            lbms_driver, '_get_lbms_agent_hosting_pool') as get_agent:
                        agent = agents_db.Agent()
                        agent.id = 'agent_id'
                        agent.host= 'host'
                        get_agent.return_value = agent
                        member = dict()
                        member['pool_id']  = 'pool_id_1'
                        member['id'] = 'member_id_1'

                        lbms_driver.create_member(None, member)
                        plugin.update_status.assert_called_with(
                            None,
                            lb_db.Member,
                            member['id'],
                            constants.ACTIVE,
                            None)

    def test_create_vip(self):
        with mock.patch('neutron.services.loadbalancer.drivers.lbms.lbms_client.LbmsClient') as lbms_client:
            with mock.patch('neutron.services.loadbalancer.drivers.lbms.lbms_scheduler.LbmsScheduler') as lbms_schduler:
                with mock.patch(
                        'neutron.services.loadbalancer.drivers.common.agent_driver_base.LoadBalancerCallbacks') as plugin:

                    lbms_driver = lbms.LbmsDriver(plugin)
                    with mock.patch.object(
                            lbms_driver, '_get_lbms_agent_hosting_pool') as get_agent:
                        agent = agents_db.Agent()
                        agent.id = 'agent_id'
                        agent.host= 'host'
                        get_agent.return_value = agent
                        vip = dict()
                        vip['pool_id']  = 'pool_id_1'
                        vip['id'] = 'vip_id_1'

                        lbms_driver.create_vip(None, vip)
                        plugin.update_status.assert_called_with(
                            None,
                            lb_db.Vip,
                            vip['id'],
                            constants.ACTIVE,
                            None)


    def test_update_pool(self):
        import pdb
        pdb.set_trace()
        with mock.patch('neutron.services.loadbalancer.drivers.lbms.lbms_client.LbmsClient') as lbms_client:
            with mock.patch('neutron.services.loadbalancer.drivers.lbms.lbms_scheduler.LbmsScheduler') as lbms_schduler:
                with mock.patch(
                        'neutron.services.loadbalancer.drivers.common.agent_driver_base.LoadBalancerCallbacks') as plugin:

                    lbms_driver = lbms.LbmsDriver(plugin)
                    with mock.patch.object(
                            lbms_driver, '_get_lbms_agent_hosting_pool') as get_agent:
                        agent = agents_db.Agent()
                        agent.id = 'agent_id'
                        agent.host= 'host'
                        get_agent.return_value = agent
                        pool = dict()
                        pool['id'] = '1'
                        pool['health_monitors_status'] = {}

                        lbms_driver.update_pool(None, pool, pool)
                        plugin.update_status.assert_called_with(
                            None,
                            lb_db.Pool,
                            pool['id'],
                            constants.ACTIVE,
                            None)

    def test_update_member(self):
        with mock.patch('neutron.services.loadbalancer.drivers.lbms.lbms_client.LbmsClient') as lbms_client:
            with mock.patch('neutron.services.loadbalancer.drivers.lbms.lbms_scheduler.LbmsScheduler') as lbms_schduler:
                with mock.patch(
                        'neutron.services.loadbalancer.drivers.common.agent_driver_base.LoadBalancerCallbacks') as plugin:

                    lbms_driver = lbms.LbmsDriver(plugin)
                    with mock.patch.object(
                            lbms_driver, '_get_lbms_agent_hosting_pool') as get_agent:
                        agent = agents_db.Agent()
                        agent.id = 'agent_id'
                        agent.host= 'host'
                        get_agent.return_value = agent
                        member = dict()
                        member['pool_id']  = 'pool_id_1'
                        member['id'] = 'member_id_1'

                        lbms_driver.update_member(None, member, member)
                        plugin.update_status.assert_called_with(
                            None,
                            lb_db.Member,
                            member['id'],
                            constants.ACTIVE,
                            None)

    def test_update_vip(self):
        with mock.patch('neutron.services.loadbalancer.drivers.lbms.lbms_client.LbmsClient') as lbms_client:
            with mock.patch('neutron.services.loadbalancer.drivers.lbms.lbms_scheduler.LbmsScheduler') as lbms_schduler:
                with mock.patch(
                        'neutron.services.loadbalancer.drivers.common.agent_driver_base.LoadBalancerCallbacks') as plugin:
                    lbms_driver = lbms.LbmsDriver(plugin)
                    with mock.patch.object(
                            lbms_driver, '_get_lbms_agent_hosting_pool') as get_agent:
                        agent = agents_db.Agent()
                        agent.id = 'agent_id'
                        agent.host = 'host'
                        get_agent.return_value = agent
                        vip = dict()
                        vip['pool_id'] = 'pool_id_1'
                        vip['id'] = 'member_id_1'

                        lbms_driver.update_vip(None, vip, vip)
                        plugin.update_status.assert_called_with(
                            None,
                            lb_db.Vip,
                            vip['id'],
                            constants.ACTIVE,
                            None)


