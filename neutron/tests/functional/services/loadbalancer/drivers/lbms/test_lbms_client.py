
import mock
from oslo_config import cfg

from neutron.db.loadbalancer import loadbalancer_db

from neutron.tests.unit.db.loadbalancer.test_db_loadbalancer import LoadBalancerPluginDbTestCase
from neutron.tests.unit.db.loadbalancer.test_db_loadbalancer import LoadBalancerMockValidateResourceDeleteMixin


class LoadBalancerLBMSDriverTestCase(LoadBalancerPluginDbTestCase, LoadBalancerMockValidateResourceDeleteMixin):

    def setUp(self, core_plugin=None, lb_plugin=None, lbaas_provider=None,
              ext_mgr=None):
        super(LoadBalancerLBMSDriverTestCase, self).setUp(core_plugin=core_plugin, lb_plugin=lb_plugin,
                                                          lbaas_provider=lbaas_provider, ext_mgr=ext_mgr)
        self.set_default_mock_patch()

    def test_create_pool(self):
        import pdb;
        pdb.set_trace()
        import neutron.services.loadbalancer.drivers.lbms.lbms_client as lbms_driver
        cfg.CONF.set_override(
            "auth_host", "10.64.218.184", "keystone_authtoken")

        cfg.CONF.set_override(
            "auth_port", "35357", "keystone_authtoken")
        cfg.CONF.set_override(
            "auth_protocol", "http", "keystone_authtoken")

        cfg.CONF.set_override(
            "lbms_username", "lbms_user", "lbms_driver")
        cfg.CONF.set_override(
            "lbms_password", "lbms_password", "lbms_driver")
        cfg.CONF.set_override(
            "lbms_tenant", "lbms_tenant", "lbms_driver")

        cfg.CONF.set_override(
            "lbms_uri", "http://d-sjc-00541471.corp.ebay.com:8080/lbms", "lbms_driver")


        lbms_client = lbms_driver.LbmsClient()

        lbms_client.get_lb_health("phxvpxlb01")

        pool = dict()


        pool['name'] = "blesson-test1"
        pool['lb_method'] = "LeastConnection"
        pool['protocol'] = "http"
        lbms_client.create_pool( "phxvpxlb01", pool)

        monitor = dict()
        monitor['name'] = 'blesson-monitor1'
        monitor['type'] = 'HTTP'
        monitor['url_path'] = '/'
        monitor['response_string'] = 'GET'
        monitor['delay'] = 2
        monitor['timeout'] = 1
        monitor['max_retries'] = 2

        pdb.set_trace()
        lbms_client.create_monitor("phxvpxlb01", monitor)


        member = dict()
        member['name'] = 'blesson-member1'
        member['address'] = '2.2.2.2'
        member['protocol_port'] = '80'
        member['weight'] = '10'
        member['admin_state_up'] = True
        pool['health_monitors'] = [monitor['name']]

        lbms_client.create_member("phxvpxlb01", pool, member)



        lbms_client.update_pool("phxvpxlb01", pool)

        vip = dict()
        vip['name'] = 'blesson-vip1'
        vip['address'] = '1.8.8.8'
        vip['protocol_port'] = '80'
        vip['protocol'] = 'http'
        vip['pool'] = pool
        vip['admin_state_up'] = True

        lbms_client.create_vip("phxvpxlb01", vip)



        lbms_client.delete_vip("phxvpxlb01", vip)

        lbms_client.remove_monitor_from_pool("phxvpxlb01", pool, monitor)

        lbms_client.remove_member("phxvpxlb01", pool, member)


        lbms_client.delete_pool( "phxvpxlb01", pool)

        lbms_client.delete_monitor("phxvpxlb01", monitor)






