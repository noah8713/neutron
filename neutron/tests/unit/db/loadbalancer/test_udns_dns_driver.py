import contextlib

import mock
from oslo_config import cfg


from neutron.tests.unit.db.loadbalancer.test_db_loadbalancer import LoadBalancerPluginDbTestCase
from neutron.tests.unit.db.loadbalancer.test_db_loadbalancer import LoadBalancerMockValidateResourceDeleteMixin


class LoadBalancerUDNSDriverTestCase(LoadBalancerPluginDbTestCase, LoadBalancerMockValidateResourceDeleteMixin):

    def setUp(self, core_plugin=None, lb_plugin=None, lbaas_provider=None,
              ext_mgr=None):
        super(LoadBalancerUDNSDriverTestCase, self).setUp(core_plugin=core_plugin, lb_plugin=lb_plugin,
                                                          lbaas_provider=lbaas_provider, ext_mgr=ext_mgr)
        self.set_default_mock_patch()

    def test_zone(self):
        import neutron.db.loadbalancer.udns_dns_driver as udns_driver
        cfg.CONF.set_override(
            "udns_zone", "Dev:lab.ebayc3.com,ext:lab.ebayc3.com", "dns")

        dns_plugin = (udns_driver.UdnsClient)
        with mock.patch.object(
                dns_plugin, '_get_keystone_token') as gt:
            # Return upper case "D"
            gt.return_value = "Dev"

            udns_client = udns_driver.UdnsClient()

            zone = udns_client.zone("dev")
            self.assertIn(zone,
                          "lab.ebayc3.com")

    def test_view(self):
        import neutron.db.loadbalancer.udns_dns_driver as udns_driver
        cfg.CONF.set_override("udns_view", "dEV:ebay-cloud,ext:public", "dns")

        dns_plugin = (udns_driver.UdnsClient)
        with mock.patch.object(
                dns_plugin, '_get_keystone_token') as gt:
            # Return upper case "D"
            gt.return_value = "Dev"

            udns_client = udns_driver.UdnsClient()

            view = udns_client.view("dev")
            self.assertIn(view,
                          "ebay-cloud")
