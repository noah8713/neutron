# Copyright (c) 2013 OpenStack Foundation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import mock
from oslo_config import cfg
from webob import exc
import datetime

from neutron.openstack.common import timeutils


from neutron.api import extensions
from neutron.api.v2 import attributes
from neutron.common import constants
from neutron import context
from neutron.db import servicetype_db as st_db
from neutron.extensions import agent
from neutron.extensions import lbaas_agentscheduler
from neutron.extensions import loadbalancer
from neutron import manager
from neutron.plugins.common import constants as plugin_const
from neutron.tests.unit.db.loadbalancer import test_db_loadbalancer
from neutron.tests.unit.openvswitch import test_agent_scheduler
from neutron.tests.unit import test_agent_ext_plugin
from neutron.tests.unit import test_db_plugin as test_plugin
from neutron.tests.unit import test_extensions

LBAAS_HOSTA = 'hosta'





class F5LBaaSAgentSchedulerTestCase(test_agent_ext_plugin.AgentDBTestMixIn,
                                  test_db_loadbalancer.LoadBalancerTestMixin,
                                  test_plugin.NeutronDbPluginV2TestCase):
    fmt = 'json'
    plugin_str = 'neutron.plugins.ml2.plugin.Ml2Plugin'

    def setUp(self):
        # Save the global RESOURCE_ATTRIBUTE_MAP
        self.saved_attr_map = {}
        for resource, attrs in attributes.RESOURCE_ATTRIBUTE_MAP.iteritems():
            self.saved_attr_map[resource] = attrs.copy()
        service_plugins = {
            'lb_plugin_name': test_db_loadbalancer.DB_LB_PLUGIN_KLASS}

        #default provider should support agent scheduling
        cfg.CONF.set_override(
            'service_provider',
            [('LOADBALANCER:lbaas:neutron.services.'
              'loadbalancer.drivers.haproxy.plugin_driver.'
              'HaproxyOnHostPluginDriver:default')],
            'service_providers')

        # need to reload provider configuration
        st_db.ServiceTypeManager._instance = None

        super(F5LBaaSAgentSchedulerTestCase, self).setUp(
            self.plugin_str, service_plugins=service_plugins)
        ext_mgr = extensions.PluginAwareExtensionManager.get_instance()
        self.ext_api = test_extensions.setup_extensions_middleware(ext_mgr)
        self.adminContext = context.get_admin_context()
        # Add the resources to the global attribute map
        # This is done here as the setup process won't
        # initialize the main API router which extends
        # the global attribute map
        attributes.RESOURCE_ATTRIBUTE_MAP.update(
            agent.RESOURCE_ATTRIBUTE_MAP)
        self.addCleanup(self.restore_attribute_map)

    def restore_attribute_map(self):
        # Restore the original RESOURCE_ATTRIBUTE_MAP
        attributes.RESOURCE_ATTRIBUTE_MAP = self.saved_attr_map



    def test_get_pools_associated_with_lb_agents(self):
        import neutron.services.loadbalancer.agent_scheduler as agent_scheduler
        agent_plugin = agent_scheduler.LbaasAgentSchedulerDbMixin

        import neutron.db.agents_db as agent_db
        agent_1 = agent_db.Agent()
        agent_1.binary = 'f5'
        agent_1.host = 'vlbaascloud2-1-6938:41e468a0-a4fc-534e-a29d-92f0511c1980'
        agent_1.admin_state_up = 1
        agent_1.heartbeat_timestamp = timeutils.utcnow()
        agent_2 = agent_db.Agent()
        agent_2.binary = 'f5'
        agent_2.host = 'newoe-1-6938:41e468a0-a4fc-534e-a29d-92f0511c1980'
        agent_2.admin_state_up = 1
        agent_2.heartbeat_timestamp = timeutils.utcnow()
        agent_3 = agent_db.Agent()
        agent_3.binary = 'f5'
        agent_3.host = 'simpledf-1-6938:41e468a0-a4fc-534e-a29d-92f0511c1980'
        agent_3.admin_state_up = 1
        agent_3.heartbeat_timestamp = timeutils.utcnow()


        agents = [agent_1, agent_2, agent_3]


        pool_1 = {
            'id': '1'
        }
        pool_2 = {
            'id': '2'
        }
        pool_3 = {
            'id': '3'
        }


        pools = [pool_1, pool_2, pool_3]
        pool_map = {'pools': pools}

        with mock.patch.object(
                agent_plugin, 'get_lbaas_agents') as gt:
            gt.return_value = agents
            with mock.patch.object(
                    agent_plugin, 'list_pools_on_pool_agent_binding') as lp:
                lp.return_value = pool_map
                lbaas_agentscheduler = agent_scheduler.LbaasAgentSchedulerDbMixin()

                pool_ids = lbaas_agentscheduler._get_pools_associated_with_agent_lb(context=None, host='vlbaascloud2-1-6938:41e468a0-a4fc-534e-a29d-92f0511c1980')
                self.assertIn(pool_ids[0],'1')


                pool_ids = lbaas_agentscheduler._get_pools_associated_with_agent_lb(context=None, host='simpledf-1-6938:41e468a0-a4fc-534e-a29d-92f0511c1980')
                self.assertIn(pool_ids[0], '3')








    def test_get_pools_associated_with_agent(self):
        import neutron.services.loadbalancer.agent_scheduler as agent_scheduler
        agent_plugin = agent_scheduler.LbaasAgentSchedulerDbMixin



        import neutron.db.agents_db as agent_db
        agent_1 = agent_db.Agent()
        agent_1.binary = 'f5'
        agent_1.admin_state_up = 1
        agent_1.heartbeat_timestamp = timeutils.utcnow()
        agent_1.configurations = '{"icontrol_endpoints": {"10.64.217.10": {"device_name": "host-10-64-217-10.stratus.lvs.ebay.com", "platform": "Virtual Edition", "version": "BIG-IP_v11.5.1", "serial_number": "842e5d32-f83d-4a9a-263939bb53e2"}}, "request_queue_depth": 0, "environment_prefix": "", "tunneling_ips": [], "floating_ip": null, "services": 12, "environment_capacity_score": 0, "tunnel_types": [], "environment_group_number": 1, "scheduler_props": {"vpc_subnet_list": {"dev": ["c3c6add7-a32c-446b-85be-695c53d5aeb0"]}}, "bridge_mappings": {}, "global_routed_mode": true}'
        agent_1.host = 'f5_host1:123'
        agent_2 = agent_db.Agent()
        agent_2.binary = 'f5'
        agent_2.host = 'f5_host2:123'
        agent_2.heartbeat_timestamp = timeutils.utcnow()
        agent_2.admin_state_up = 1
        agent_2.configurations = '{"icontrol_endpoints": {"10.64.217.10": {"device_name": "host-10-64-217-10.stratus.lvs.ebay.com", "platform": "Virtual Edition", "version": "BIG-IP_v11.5.1", "serial_number": "842e5d32-f83d-4a9a-263939bb53e2"}}, "request_queue_depth": 0, "environment_prefix": "", "tunneling_ips": [], "floating_ip": null, "services": 12, "environment_capacity_score": 0, "tunnel_types": [], "environment_group_number": 1, "scheduler_props": {"vpc_subnet_list": {"dev": ["c3c6add7-a32c-446b-85be-695c53d5aeb0"]}}, "bridge_mappings": {}, "global_routed_mode": true}'
        agent_3 = agent_db.Agent()
        agent_3.binary = 'f5'
        agent_3.host = 'f5_host3:123'
        agent_3.admin_state_up = 1
        agent_3.heartbeat_timestamp = timeutils.utcnow()
        agent_3.configurations = '{"icontrol_endpoints": {"10.64.217.10": {"device_name": "host-10-64-217-10.stratus.lvs.ebay.com", "platform": "Virtual Edition", "version": "BIG-IP_v11.5.1", "serial_number": "842e5d32-f83d-4a9a-263939bb53e2"}}, "request_queue_depth": 0, "environment_prefix": "", "tunneling_ips": [], "floating_ip": null, "services": 12, "environment_capacity_score": 0, "tunnel_types": [], "environment_group_number": 1, "scheduler_props": {"vpc_subnet_list": {"dev": ["c3c6add7-a32c-446b-85be-695c53d5aeb0"]}}, "bridge_mappings": {}, "global_routed_mode": true}'


        agents = [agent_1, agent_2, agent_3]


        pool_1 = {
            'id': '1'
        }
        pool_2 = {
            'id': '2'
        }
        pool_3 = {
            'id': '3'
        }
        pool_4 = {
            'id': '4'
        }
        pool_5 = {
            'id': '5'
        }
        pool_6 = {
            'id': '6'
        }
        pool_7 = {
            'id': '7'
        }
        pool_8 = {
            'id': '8'
        }
        pool_9 = {
            'id': '9'
        }
        pool_10 = {
            'id': '10'
        }

        pools = [pool_1, pool_2, pool_3, pool_4, pool_5, pool_6, pool_7, pool_8, pool_9, pool_10]
        pool_map = {'pools': pools}

        with mock.patch.object(
                agent_plugin, 'get_lbaas_agents') as gt:
            gt.return_value = agents
            with mock.patch.object(
                    agent_plugin, 'list_pools_on_pool_agent_binding') as lp:
                lp.return_value = pool_map
                lbaas_agentscheduler = agent_scheduler.LbaasAgentSchedulerDbMixin()

                pool_ids = lbaas_agentscheduler._get_pools_associated_with_agent_lb(context=None, host='f5_host1:123')
                self.assertIn(pool_ids[0],'1')
                self.assertIn(pool_ids[1],'2')
                self.assertIn(pool_ids[2],'3')

                pool_ids = lbaas_agentscheduler._get_pools_associated_with_agent_lb(context=None, host='f5_host2:123')
                self.assertIn(pool_ids[0], '4')
                self.assertIn(pool_ids[1], '5')
                self.assertIn(pool_ids[2], '6')

                pool_ids = lbaas_agentscheduler._get_pools_associated_with_agent_lb(context=None, host='f5_host3:123')
                self.assertIn(pool_ids[0], '7')
                self.assertIn(pool_ids[1], '8')
                self.assertIn(pool_ids[2], '9')
                self.assertIn(pool_ids[3], '10')

    def test_get_pools_associated_with_agent_with_no_pools(self):
        import neutron.services.loadbalancer.agent_scheduler as agent_scheduler
        agent_plugin = agent_scheduler.LbaasAgentSchedulerDbMixin

        import neutron.db.agents_db as agent_db
        agent_1 = agent_db.Agent()
        agent_1.binary = 'f5'
        agent_1.host = 'f5_host4'
        agent_2 = agent_db.Agent()
        agent_2.binary = 'f5'
        agent_2.host = 'f5_host2'
        agent_3 = agent_db.Agent()
        agent_3.binary = 'f5'
        agent_3.host = 'f5_host3'

        agents = [agent_1, agent_2, agent_3]


        pools = []
        pool_map = {'pools': pools}

        with mock.patch.object(
                agent_plugin, 'get_lbaas_agents') as gt:
            gt.return_value = agents
            with mock.patch.object(
                    agent_plugin, 'list_pools_on_pool_agent_binding') as lp:
                lp.return_value = pool_map
                lbaas_agentscheduler = agent_scheduler.LbaasAgentSchedulerDbMixin()

                lbaas_agentscheduler._get_pools_associated_with_agent_lb(context=None, host='f5_host1')


    def test_get_pools_associated_with_agent_more_and_pools_less(self):
        import neutron.services.loadbalancer.agent_scheduler as agent_scheduler
        agent_plugin = agent_scheduler.LbaasAgentSchedulerDbMixin

        import neutron.db.agents_db as agent_db
        agent_1 = agent_db.Agent()
        agent_1.binary = 'f5'
        agent_1.configurations = '{"icontrol_endpoints": {"10.64.217.10": {"device_name": "host-10-64-217-10.stratus.lvs.ebay.com", "platform": "Virtual Edition", "version": "BIG-IP_v11.5.1", "serial_number": "842e5d32-f83d-4a9a-263939bb53e2"}}, "request_queue_depth": 0, "environment_prefix": "", "tunneling_ips": [], "floating_ip": null, "services": 12, "environment_capacity_score": 0, "tunnel_types": [], "environment_group_number": 1, "scheduler_props": {"vpc_subnet_list": {"dev": ["c3c6add7-a32c-446b-85be-695c53d5aeb0"]}}, "bridge_mappings": {}, "global_routed_mode": true}'
        agent_1.host = 'f5_host1:123'
        agent_1.admin_state_up = 1
        agent_1.heartbeat_timestamp = timeutils.utcnow()
        agent_1.id = 1
        agent_2 = agent_db.Agent()
        agent_2.binary = 'f5'
        agent_2.host = 'f5_host2:123'
        agent_2.id = 2
        agent_2.admin_state_up = 1
        agent_2.heartbeat_timestamp = timeutils.utcnow()
        agent_2.configurations = '{"icontrol_endpoints": {"10.64.217.10": {"device_name": "host-10-64-217-10.stratus.lvs.ebay.com", "platform": "Virtual Edition", "version": "BIG-IP_v11.5.1", "serial_number": "842e5d32-f83d-4a9a-263939bb53e2"}}, "request_queue_depth": 0, "environment_prefix": "", "tunneling_ips": [], "floating_ip": null, "services": 12, "environment_capacity_score": 0, "tunnel_types": [], "environment_group_number": 1, "scheduler_props": {"vpc_subnet_list": {"dev": ["c3c6add7-a32c-446b-85be-695c53d5aeb0"]}}, "bridge_mappings": {}, "global_routed_mode": true}'
        agent_3 = agent_db.Agent()
        agent_3.binary = 'f5'
        agent_3.host = 'f5_host3:321'
        agent_3.admin_state_up = 1
        agent_3.heartbeat_timestamp = timeutils.utcnow()
        agent_3.id = 3
        agent_3.configurations = '{"icontrol_endpoints": {"10.64.217.10": {"device_name": "host-10-64-217-10.stratus.lvs.ebay.com", "platform": "Virtual Edition", "version": "BIG-IP_v11.5.1", "serial_number": "842e5d32-f83d-4a9a-263939bb53e2"}}, "request_queue_depth": 0, "environment_prefix": "", "tunneling_ips": [], "floating_ip": null, "services": 12, "environment_capacity_score": 0, "tunnel_types": [], "environment_group_number": 1, "scheduler_props": {"vpc_subnet_list": {"dev": ["c3c6add7-a32c-446b-85be-695c53d5aeb0"]}}, "bridge_mappings": {}, "global_routed_mode": true}'
        agent_4 = agent_db.Agent()
        agent_4.binary = 'f5'
        agent_4.host = 'f5_host4:456'
        agent_4.id = 4
        agent_5 = agent_db.Agent()
        agent_5.binary = 'NetScalar'
        agent_5.host = 'Netscalar'

        agents = [agent_1, agent_2, agent_3, agent_4, agent_5]


        pool_1 = {
            'id': '1'
        }
        pool_2 = {
            'id': '2'
        }
        pool_3 = {
            'id': '3'
        }


        pools = [pool_1, pool_2, pool_3]
        pool_map = {'pools': pools}

        with mock.patch.object(
                agent_plugin, 'get_lbaas_agents') as gt:
            gt.return_value = agents
            with mock.patch.object(
                    agent_plugin, 'list_pools_on_pool_agent_binding') as lp:
                lp.return_value = pool_map
                lbaas_agentscheduler = agent_scheduler.LbaasAgentSchedulerDbMixin()

                pool_ids = lbaas_agentscheduler._get_pools_associated_with_agent_lb(context=None, host='f5_host1:123')
                self.assertIn(pool_ids[0],'1')


                pool_ids = lbaas_agentscheduler._get_pools_associated_with_agent_lb(context=None, host='f5_host2:123')
                self.assertIn(pool_ids[0], '2')
                self.assertIn(pool_ids[1], '3')


                pool_ids = lbaas_agentscheduler._get_pools_associated_with_agent_lb(context=None, host='f5_host3:321')
                self.assertIn(pool_ids[0], '1')
                self.assertIn(pool_ids[1], '2')
                self.assertIn(pool_ids[2], '3')

                pool_ids = lbaas_agentscheduler._get_pools_associated_with_agent_lb(context=None, host='f5_host4:456')
                self.assertIsNone(pool_ids)




    def test_get_pools_associated_with_agent_down(self):
        import neutron.services.loadbalancer.agent_scheduler as agent_scheduler
        agent_plugin = agent_scheduler.LbaasAgentSchedulerDbMixin

        import neutron.db.agents_db as agent_db
        agent_1 = agent_db.Agent()
        agent_1.binary = 'f5'
        agent_1.host = 'f5_host1:123'
        agent_1.admin_state_up = 1
        agent_1.heartbeat_timestamp = datetime.datetime(2015, 9, 24, 6, 28, 51, 212113)
        agent_1.id = 1
        agent_2 = agent_db.Agent()
        agent_2.binary = 'f5'
        agent_2.host = 'f5_host2:123'
        agent_2.id = 2
        agent_2.admin_state_up = 0
        agent_2.heartbeat_timestamp = timeutils.utcnow()
        agent_3 = agent_db.Agent()
        agent_3.binary = 'f5'
        agent_3.host = 'f5_host3:123'
        agent_3.admin_state_up = 1
        agent_3.heartbeat_timestamp = timeutils.utcnow()
        agent_3.id = 3

        agents = [agent_1, agent_2, agent_3]


        pool_1 = {
            'id': '1'
        }
        pool_2 = {
            'id': '2'
        }
        pool_3 = {
            'id': '3'
        }


        pools = [pool_1, pool_2, pool_3]
        pool_map = {'pools': pools}

        with mock.patch.object(
                agent_plugin, 'get_lbaas_agents') as gt:
            gt.return_value = agents
            with mock.patch.object(
                    agent_plugin, 'list_pools_on_pool_agent_binding') as lp:
                lp.return_value = pool_map
                lbaas_agentscheduler = agent_scheduler.LbaasAgentSchedulerDbMixin()




                pool_ids = lbaas_agentscheduler._get_pools_associated_with_agent_lb(context=None, host='f5_host3:123')
                self.assertIn(pool_ids[0], '1')
                self.assertIn(pool_ids[1], '2')
                self.assertIn(pool_ids[2], '3')

                pool_ids = lbaas_agentscheduler._get_pools_associated_with_agent_lb(context=None, host='f5_host3')







class F5LBaaSAgentSchedulerTestCaseXML(F5LBaaSAgentSchedulerTestCase):
    fmt = 'xml'
