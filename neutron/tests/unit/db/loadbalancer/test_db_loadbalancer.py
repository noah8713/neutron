# Copyright (c) 2012 OpenStack Foundation.
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

import contextlib

import mock
from oslo_config import cfg
import testtools
import webob.exc

from neutron.api import extensions
from neutron.common import config
from neutron.common import exceptions as n_exc
from neutron import context
from neutron.db.loadbalancer import loadbalancer_db as ldb
from neutron.db import servicetype_db as sdb
import neutron.extensions
from neutron.extensions import loadbalancer
from neutron.extensions import bulkloadbalancer
from neutron import manager
from neutron.plugins.common import constants
from neutron.services.loadbalancer import (
    plugin as loadbalancer_plugin
)
from neutron.services.loadbalancer.drivers import abstract_driver, abstract_bulk_driver
from neutron.services import provider_configuration as pconf
from neutron.tests.unit import test_db_plugin
import random
import string



DB_CORE_PLUGIN_KLASS = 'neutron.db.db_base_plugin_v2.NeutronDbPluginV2'
DB_LB_PLUGIN_KLASS = (
    "neutron.services.loadbalancer."
    "plugin.LoadBalancerPlugin"
)
NOOP_DRIVER_KLASS = ('neutron.tests.unit.db.loadbalancer.test_db_loadbalancer.'
                     'NoopLbaaSDriver')

FORCEDELETE_NOOP_DRIVER_KLASS = ('neutron.tests.unit.db.loadbalancer.test_db_loadbalancer.'
                                 'ForceDeleteNoopLbaaSDriver')

extensions_path = ':'.join(neutron.extensions.__path__)

_subnet_id = "0c798ed8-33ba-11e2-8b28-000c291c4d14"


class NoopLbaaSDriver(abstract_driver.LoadBalancerAbstractDriver, abstract_bulk_driver.LBaaSAbstractBulkDriver):
    """A dummy lbass driver that that only performs object deletion."""

    def __init__(self, plugin):
        self.plugin = plugin

    def create_vip(self, context, vip):
        pass

    def update_vip(self, context, old_vip, vip):
        pass

    def delete_vip(self, context, vip):
        self.plugin._delete_db_vip(context, vip["id"])

    def create_pool(self, context, pool):
        pass

    def update_pool(self, context, old_pool, pool):
        pass

    def delete_pool(self, context, pool):
        self.plugin._delete_db_pool(context, pool["id"])

    def stats(self, context, pool_id):
        return {"bytes_in": 0,
                "bytes_out": 0,
                "active_connections": 0,
                "total_connections": 0}

    def create_member(self, context, member):
        pass

    def update_member(self, context, old_member, member):
        pass

    def create_members(self, context, members):
        pass

    def delete_members(self, context, members):
        pass

    def update_members(self, context, old_members, members):
        pass

    def delete_member(self, context, member):
        self.plugin._delete_db_member(context, member["id"])

    def update_pool_health_monitor(self, context, old_health_monitor,
                                   health_monitor,
                                   pool_association):
        pass

    def create_pool_health_monitor(self, context,
                                   health_monitor, pool_id):
        pass

    def delete_pool_health_monitor(self, context, health_monitor, pool_id):
        self.plugin._delete_db_pool_health_monitor(
            context, health_monitor["id"],
            pool_id
        )


class LoadBalancerTestMixin(object):
    resource_prefix_map = dict(
        (k, constants.COMMON_PREFIXES[constants.LOADBALANCER])
        for k in loadbalancer.RESOURCE_ATTRIBUTE_MAP.keys()
    )
    for k in bulkloadbalancer.RESOURCE_ATTRIBUTE_MAP.keys():
        resource_prefix_map[k] = constants.COMMON_PREFIXES[constants.LOADBALANCER]


    def _get_vip_optional_args(self):
        return ('description', 'subnet_id', 'address',
                'session_persistence', 'connection_limit')

    def _create_vip(self, fmt, name, pool_id, protocol, protocol_port,
                    admin_state_up, expected_res_status=None, **kwargs):
        data = {'vip': {'name': name,
                        'pool_id': pool_id,
                        'protocol': protocol,
                        'protocol_port': protocol_port,
                        'admin_state_up': admin_state_up,
                        'tenant_id': self._tenant_id}}
        args = self._get_vip_optional_args()
        for arg in args:
            if arg in kwargs and kwargs[arg] is not None:
                data['vip'][arg] = kwargs[arg]

        lb_plugin = (manager.NeutronManager.
                 get_instance().
                 get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                ps.return_value = kwargs['subnet_id']
                vip_req = self.new_create_request('vips', data, fmt)
                vip_res = vip_req.get_response(self.ext_api)
                if expected_res_status:
                    self.assertEqual(vip_res.status_int, expected_res_status)

                return vip_res

    def _create_pool(self, fmt, name, lb_method, protocol, admin_state_up,
                     expected_res_status=None, **kwargs):
        data = {'pool': {'name': name,
                         'subnet_id': _subnet_id,
                         'lb_method': lb_method,
                         'protocol': protocol,
                         'admin_state_up': admin_state_up,
                         'tenant_id': self._tenant_id,
                         'tenant_vpc' : self._tenant_vpc}}
        for arg in ('description', 'provider', 'subnet_id'):
            if arg in kwargs and kwargs[arg] is not None:
                data['pool'][arg] = kwargs[arg]
        lb_plugin = (manager.NeutronManager.
                 get_instance().
                 get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                ps.return_value = _subnet_id
                pool_req = self.new_create_request('pools', data, fmt)
                pool_res = pool_req.get_response(self.ext_api)
                if expected_res_status:
                    self.assertEqual(pool_res.status_int, expected_res_status)

                return pool_res

    def _create_member(self, fmt, address, protocol_port, admin_state_up,
                       expected_res_status=None, **kwargs):
        data = {'member': {'address': address,
                           'protocol_port': protocol_port,
                           'admin_state_up': admin_state_up,
                           'tenant_id': self._tenant_id}}
        for arg in ('weight', 'pool_id'):
            if arg in kwargs and kwargs[arg] is not None:
                data['member'][arg] = kwargs[arg]

        member_req = self.new_create_request('members', data, fmt)
        member_res = member_req.get_response(self.ext_api)
        if expected_res_status:
            self.assertEqual(member_res.status_int, expected_res_status)

        return member_res

    def _create_members(self, fmt, addresses, protocol_port, admin_state_up,
                        expected_res_status=None, **kwargs):
        data = {}
        members = []
        for address in addresses:
            member = {'member':
                          {'address': address,
                           'protocol_port': protocol_port,
                           'admin_state_up': admin_state_up,
                           'tenant_id': self._tenant_id
                          }
                     }
            for arg in ('weight', 'pool_id'):
                if arg in kwargs and kwargs[arg] is not None:
                    member['member'][arg] = kwargs[arg]
            members.append(member)
        data['members'] = members
        member_req = self.new_create_request('members', data, fmt)
        member_res = member_req.get_response(self.ext_api)
        if expected_res_status:
            self.assertEqual(member_res.status_int, expected_res_status)
        return member_res

    def _create_members_bulk(self, fmt, addresses, protocol_port, admin_state_up,
                             expected_res_status=None, **kwargs):
        request = {}
        data = {
            'action': 'create',
            'tenant_id': self._tenant_id
        }
        members = []
        for address in addresses:
            member = {'member':
                          {'address': address,
                           'protocol_port': protocol_port,
                           'admin_state_up': admin_state_up,
                           'tenant_id': self._tenant_id
                          }
                     }
            for arg in ('weight', 'pool_id'):
                if arg in kwargs and kwargs[arg] is not None:
                    member['member'][arg] = kwargs[arg]
            members.append(member)

        data['members'] = members
        request['bulk_members'] = data
        bulk_request = self.new_create_request('bulk_members', request, fmt)
        bulk_res = bulk_request.get_response(self.ext_api)
        if expected_res_status:
            self.assertEqual(bulk_res.status_int, expected_res_status)
        return bulk_res

    def _delete_members(self, fmt, member_ids, expected_res_status=None, **kwargs):
        request = {}
        data = {
            'action': 'delete',
            'members':  member_ids,
            'tenant_id': self._tenant_id
        }
        request['bulk_members'] = data
        bulk_request = self.new_create_request('bulk_members', request, fmt)
        bulk_res = bulk_request.get_response(self.ext_api)
        if expected_res_status:
            self.assertEqual(bulk_res.status_int, expected_res_status)
        return bulk_res

    def _update_members(self, fmt, members, expected_res_status=None, **kwargs):
        request = {}
        data = {
            'action': 'update',
            'members':  members,
            'tenant_id': self._tenant_id
        }
        request['bulk_members'] = data
        bulk_request = self.new_create_request('bulk_members', request, fmt)
        bulk_res = bulk_request.get_response(self.ext_api)
        if expected_res_status:
            self.assertEqual(bulk_res.status_int, expected_res_status)
        return bulk_res

    def _create_health_monitor(self, fmt, type, delay, timeout, max_retries,
                               admin_state_up, expected_res_status=None,
                               **kwargs):
        data = {'health_monitor': {'type': type,
                                   'delay': delay,
                                   'timeout': timeout,
                                   'max_retries': max_retries,
                                   'admin_state_up': admin_state_up,
                                   'tenant_id': self._tenant_id,
                                   'name' : 'test_health_monitor_' + self._random_key(3)}}
        for arg in ('http_method', 'path', 'expected_code'):
            if arg in kwargs and kwargs[arg] is not None:
                data['health_monitor'][arg] = kwargs[arg]

        req = self.new_create_request('health_monitors', data, fmt)

        res = req.get_response(self.ext_api)
        if expected_res_status:
            self.assertEqual(res.status_int, expected_res_status)

        return res

    def _random_key(self, length):
        key = ''
        for i in range(length):
            key += random.choice(string.lowercase + string.uppercase + string.digits)
        return key


    @contextlib.contextmanager
    def vip(self, fmt=None, name='vip1', pool=None, subnet=None,
            protocol='HTTP', protocol_port=80, admin_state_up=True,
            do_delete=True, **kwargs):
        if not fmt:
            fmt = self.fmt

        with test_db_plugin.optional_ctx(subnet, self.subnet) as tmp_subnet:
            with test_db_plugin.optional_ctx(pool, self.pool) as tmp_pool:
                pool_id = tmp_pool['pool']['id']
                res = self._create_vip(fmt,
                                       name,
                                       pool_id,
                                       protocol,
                                       protocol_port,
                                       admin_state_up,
                                       subnet_id=tmp_subnet['subnet']['id'],
                                       **kwargs)
                if res.status_int >= webob.exc.HTTPClientError.code:
                    raise webob.exc.HTTPClientError(
                        explanation=_("Unexpected error code: %s") %
                        res.status_int
                    )
                vip = self.deserialize(fmt or self.fmt, res)
                yield vip

                if do_delete:
                    lb_plugin = (manager.NeutronManager.
                         get_instance().
                         get_service_plugins()[constants.LOADBALANCER])
                    with mock.patch.object(lb_plugin, '_get_cos_by_tenant_id') as gc:
                        gc.return_value = "dev"

                        with mock.patch.object(lb_plugin, '_validate_resource_delete') as vrd:
                            vrd.return_value = True
                            self._delete('vips', vip['vip']['id'])

    @contextlib.contextmanager
    def pool(self, fmt=None, name='pool1', lb_method='ROUND_ROBIN',
             protocol='HTTP', admin_state_up=True, do_delete=True,
             **kwargs):
        if not fmt:
            fmt = self.fmt
        res = self._create_pool(fmt,
                                name,
                                lb_method,
                                protocol,
                                admin_state_up,
                                **kwargs)
        if res.status_int >= webob.exc.HTTPClientError.code:
            raise webob.exc.HTTPClientError(
                explanation=_("Unexpected error code: %s") % res.status_int
            )
        pool = self.deserialize(fmt or self.fmt, res)
        yield pool
        if do_delete:
            lb_plugin = (manager.NeutronManager.
                         get_instance().
                         get_service_plugins()[constants.LOADBALANCER])
            with mock.patch.object(lb_plugin, '_get_cos_by_tenant_id') as gc:
                gc.return_value = "dev"

                with mock.patch.object(lb_plugin, '_validate_resource_delete') as vrd:
                    vrd.return_value = True
                    self._delete('pools', pool['pool']['id'])


    @contextlib.contextmanager
    def member(self, fmt=None, address='192.168.1.100', protocol_port=80,
               admin_state_up=True, do_delete=True, **kwargs):
        if not fmt:
            fmt = self.fmt
        res = self._create_member(fmt,
                                  address,
                                  protocol_port,
                                  admin_state_up,
                                  **kwargs)
        if res.status_int >= webob.exc.HTTPClientError.code:
            raise webob.exc.HTTPClientError(
                explanation=_("Unexpected error code: %s") % res.status_int
            )
        member = self.deserialize(fmt or self.fmt, res)
        yield member
        if do_delete:
            self._delete('members', member['member']['id'])

    @contextlib.contextmanager
    def members(self, fmt=None, addresses=None, protocol_port=80,
                admin_state_up=True, do_delete=True, **kwargs):
        if not fmt:
            fmt = self.fmt
        if not addresses:
            addresses = ['192.168.1.100']
        res = self._create_members(fmt,
                                  addresses,
                                  protocol_port,
                                  admin_state_up,
                                  **kwargs)
        if res.status_int >= webob.exc.HTTPClientError.code:
            raise webob.exc.HTTPClientError(
                explanation=_("Unexpected error code: %s") % res.status_int
            )
        member = self.deserialize(fmt or self.fmt, res)
        yield member
        if do_delete:
            self._delete('members', member['member']['id'])

    @contextlib.contextmanager
    def create_members(self, fmt=None, addresses=None, protocol_port=80,
                admin_state_up=True, do_delete=True, **kwargs):
        if not fmt:
            fmt = self.fmt
        if not addresses:
            addresses = ['192.168.1.100']
        res = self._create_members_bulk(fmt,
                                        addresses,
                                        protocol_port,
                                        admin_state_up,
                                        **kwargs)
        if res.status_int >= webob.exc.HTTPClientError.code:
            raise webob.exc.HTTPClientError(
                explanation=_("Unexpected error code: %s") % res.status_int
            )
        member = self.deserialize(fmt or self.fmt, res)
        yield member
        if do_delete:
            self._delete('members', member['member']['id'])


    @contextlib.contextmanager
    def delete_members(self, fmt=None, member_ids=None, **kwargs):
        res = self._delete_members(fmt, member_ids)
        if res.status_int >= webob.exc.HTTPClientError.code:
            raise webob.exc.HTTPClientError(
                explanation=_("Unexpected error code: %s") % res.status_int
            )
        members = self.deserialize(fmt or self.fmt, res)
        yield members

    @contextlib.contextmanager
    def update_members(self, members, fmt=None, **kwargs):
        res = self._update_members(fmt, members)
        if res.status_int >= webob.exc.HTTPClientError.code:
            raise webob.exc.HTTPClientError(
                explanation=_("Unexpected error code: %s") % res.status_int
            )
        members = self.deserialize(fmt or self.fmt, res)
        yield members


    @contextlib.contextmanager
    def health_monitor(self, fmt=None, type='TCP',
                       delay=30, timeout=10, max_retries=3,
                       admin_state_up=True,
                       do_delete=True, **kwargs):
        if not fmt:
            fmt = self.fmt
        res = self._create_health_monitor(fmt,
                                          type,
                                          delay,
                                          timeout,
                                          max_retries,
                                          admin_state_up,
                                          **kwargs)
        if res.status_int >= webob.exc.HTTPClientError.code:
            raise webob.exc.HTTPClientError(
                explanation=_("Unexpected error code: %s") % res.status_int
            )
        health_monitor = self.deserialize(fmt or self.fmt, res)
        the_health_monitor = health_monitor['health_monitor']
        # make sure:
        # 1. When the type is HTTP/S we have HTTP related attributes in
        #    the result
        # 2. When the type is not HTTP/S we do not have HTTP related
        #    attributes in the result
        http_related_attributes = ('http_method', 'url_path', 'expected_codes')
        if type in ['HTTP', 'HTTPS']:
            for arg in http_related_attributes:
                self.assertIsNotNone(the_health_monitor.get(arg))
        else:
            for arg in http_related_attributes:
                self.assertIsNone(the_health_monitor.get(arg))
        yield health_monitor
        if do_delete:
            self._delete('health_monitors', the_health_monitor['id'])


class LoadBalancerMockValidateResourceDeleteMixin(object):

    def set_default_mock_patch(self):
        validate_resource_delete_patcher = mock.patch('neutron.services.loadbalancer.plugin.LoadBalancerPlugin._validate_resource_delete')
        validate_resource_delete_driver = mock.MagicMock()
        validate_resource_delete_patcher.start().return_value = validate_resource_delete_driver
        validate_resource_delete_driver.return_value = True


class LoadBalancerPluginDbTestCase(LoadBalancerTestMixin,
                                   test_db_plugin.NeutronDbPluginV2TestCase):
    def setUp(self, core_plugin=None, lb_plugin=None, lbaas_provider=None,
              ext_mgr=None):
        service_plugins = {'lb_plugin_name': DB_LB_PLUGIN_KLASS}
        if not lbaas_provider:
            lbaas_provider = (
                constants.LOADBALANCER +
                ':lbaas:' + NOOP_DRIVER_KLASS + ':default')
        cfg.CONF.set_override('service_provider',
                              [lbaas_provider],
                              'service_providers')
        #force service type manager to reload configuration:
        sdb.ServiceTypeManager._instance = None

        super(LoadBalancerPluginDbTestCase, self).setUp(
            ext_mgr=ext_mgr,
            service_plugins=service_plugins
        )

        if not ext_mgr:
                self.plugin = loadbalancer_plugin.LoadBalancerPlugin()
                with mock.patch.object(self.plugin, '_get_tenant_vpc',return_value="dev"):
                    with mock.patch.object(self.plugin, 'pick_subnet_id',return_value=_subnet_id):
                        with mock.patch.object(self.plugin, '_validate_resource_delete', return_value=False):
                            ext_mgr = extensions.PluginAwareExtensionManager(
                                extensions_path,
                                {constants.LOADBALANCER: self.plugin}
                            )
                            app = config.load_paste_app('extensions_test_app')
                            self.ext_api = extensions.ExtensionMiddleware(app, ext_mgr=ext_mgr)

        get_lbaas_agent_patcher = mock.patch(
            'neutron.services.loadbalancer.agent_scheduler'
            '.LbaasAgentSchedulerDbMixin.get_lbaas_agent_hosting_pool')
        mock_lbaas_agent = mock.MagicMock()
        get_lbaas_agent_patcher.start().return_value = mock_lbaas_agent
        mock_lbaas_agent.__getitem__.return_value = {'host': 'host'}

        create_aptr_udns_driver_patcher = mock.patch('neutron.db.loadbalancer.loadbalancer_db.LoadBalancerPluginDb._create_aptr_record')
        create_aptr_mock_udns_driver = mock.MagicMock()
        create_aptr_udns_driver_patcher.start().return_value = create_aptr_mock_udns_driver
        create_aptr_mock_udns_driver.return_value = None

        delete_aptr_udns_driver_patcher = mock.patch('neutron.db.loadbalancer.loadbalancer_db.LoadBalancerPluginDb._delete_aptr_record')
        delete_aptr_mock_udns_driver = mock.MagicMock()
        delete_aptr_udns_driver_patcher.start().return_value = delete_aptr_mock_udns_driver
        delete_aptr_mock_udns_driver.return_value = None
        self._subnet_id = _subnet_id


class TestLoadBalancerBulk(LoadBalancerPluginDbTestCase, LoadBalancerMockValidateResourceDeleteMixin):

    def setUp(self, core_plugin=None, lb_plugin=None, lbaas_provider=None,
              ext_mgr=None):
        super(TestLoadBalancerBulk, self).setUp(core_plugin=core_plugin, lb_plugin=lb_plugin,
                                            lbaas_provider=lbaas_provider,ext_mgr=ext_mgr)
        self.set_default_mock_patch()

    def test_create_members(self):
        lb_plugin = (manager.NeutronManager.
                 get_instance().
                 get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                ps.return_value = _subnet_id

                with mock.patch.object(
                    lb_plugin, '_get_cos_by_tenant_id') as gc:
                    gc.return_value = "dev"
                    with self.pool() as pool:
                        pool_id = pool['pool']['id']

                        with self.members(addresses=['192.168.1.100','192.168.1.101'],
                                          protocol_port=80,
                                          pool_id=pool_id,
                                          do_delete=False) as members:

                                req = self.new_show_request('pools',
                                                            pool_id,
                                                            fmt=self.fmt)
                                pool_update = self.deserialize(
                                    self.fmt,
                                    req.get_response(self.ext_api)
                                )
                                self.assertIn(members['members'][0]['id'],
                                              pool_update['pool']['members'])
                                self.assertIn(members['members'][1]['id'],
                                              pool_update['pool']['members'])

    def test_create_members_bulk(self):
        lb_plugin = (manager.NeutronManager.
                 get_instance().
                 get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                ps.return_value = _subnet_id

                with mock.patch.object(
                    lb_plugin, '_get_cos_by_tenant_id') as gc:
                    gc.return_value = "dev"
                    with self.pool() as pool:
                        pool_id = pool['pool']['id']

                        with self.create_members(addresses=['192.168.1.100','192.168.1.101'],
                                                  protocol_port=80,
                                                  pool_id=pool_id,
                                                  do_delete=False) as members:

                                req = self.new_show_request('pools',
                                                            pool_id,
                                                            fmt=self.fmt)
                                pool_update = self.deserialize(
                                    self.fmt,
                                    req.get_response(self.ext_api)
                                )
                                self.assertIn(members['members'][0]['id'],
                                              pool_update['pool']['members'])
                                self.assertIn(members['members'][1]['id'],
                                              pool_update['pool']['members'])

    def test_delete_members_bulk(self):

        lb_plugin = (manager.NeutronManager.get_instance()
                                           .get_service_plugins()[constants.LOADBALANCER])

        with mock.patch.object(lb_plugin, '_get_tenant_vpc') as gt:
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                ps.return_value = _subnet_id

                with mock.patch.object(
                    lb_plugin, '_get_cos_by_tenant_id') as gc:
                    gc.return_value = "dev"
                    with self.pool() as pool:
                        pool_id = pool['pool']['id']

                        with self.members(addresses=['192.168.1.100','192.168.1.101'],
                                          protocol_port=80,
                                          pool_id=pool_id,
                                          do_delete=False) as members:
                            resource_ids = [members['members'][0]['id'], members['members'][1]['id']]
                            with self.delete_members(member_ids=resource_ids):
                                member_delete_resp = []
                                for res in resource_ids:
                                    req = self.new_show_request('members',
                                                            res,
                                                            fmt=self.fmt)
                                    member_del = self.deserialize(self.fmt, req.get_response(self.ext_api))
                                    member_delete_resp.append(member_del)

                                self.assertEqual(2, len(member_delete_resp))
                                self.assertEqual(constants.PENDING_DELETE, member_delete_resp[0]['member']['status'])
                                self.assertEqual(constants.PENDING_DELETE, member_delete_resp[1]['member']['status'])

    def test_update_members_bulk(self):
        lb_plugin = (manager.NeutronManager.
                 get_instance().
                 get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                ps.return_value = _subnet_id

                with mock.patch.object(
                    lb_plugin, '_get_cos_by_tenant_id') as gc:
                    gc.return_value = "dev"
                    with self.pool() as pool:
                        pool_id = pool['pool']['id']

                        with self.create_members(addresses=['192.168.1.100','192.168.1.101'],
                                                  protocol_port=80,
                                                  pool_id=pool_id,
                                                  do_delete=False) as members:

                                req = self.new_show_request('pools',
                                                            pool_id,
                                                            fmt=self.fmt)
                                pool_update = self.deserialize(
                                    self.fmt,
                                    req.get_response(self.ext_api)
                                )
                                self.assertIn(members['members'][0]['id'],
                                              pool_update['pool']['members'])
                                self.assertIn(members['members'][1]['id'],
                                              pool_update['pool']['members'])

                                ## update the members weight
                                member_update_resp = []
                                for mem in members['members']:
                                    member_update_resp.append({
                                        'member': {
                                            'id': mem['id'],
                                            'pool_id': mem['pool_id'],
                                            'weight': 5
                                        }
                                    })
                                with self.update_members(member_update_resp) as updated_members:
                                    self.assertEqual(5, updated_members['members'][0]['weight'])
                                    self.assertEqual(5, updated_members['members'][1]['weight'])
                                    self.assertEqual(constants.PENDING_UPDATE, updated_members['members'][0]['status'])
                                    self.assertEqual(constants.PENDING_UPDATE, updated_members['members'][1]['status'])


class TestLoadBalancer(LoadBalancerPluginDbTestCase, LoadBalancerMockValidateResourceDeleteMixin):

    def setUp(self, core_plugin=None, lb_plugin=None, lbaas_provider=None,
              ext_mgr=None):
        super(TestLoadBalancer, self).setUp(core_plugin=core_plugin, lb_plugin=lb_plugin,
                                            lbaas_provider=lbaas_provider,ext_mgr=ext_mgr)
        self.set_default_mock_patch()

    def test_create_vip(self, **extras):
        expected = {
            'name': 'vip1',
            'description': '',
            'protocol_port': 80,
            'protocol': 'HTTP',
            'connection_limit': -1,
            'admin_state_up': True,
            'status': 'PENDING_CREATE',
            'tenant_id': self._tenant_id,
        }

        expected.update(extras)

        with self.subnet() as subnet:
            expected['subnet_id'] = subnet['subnet']['id']

            name = expected['name']

            lb_plugin = (manager.NeutronManager.
                             get_instance().
                             get_service_plugins()[constants.LOADBALANCER])
            with mock.patch.object(
                lb_plugin, '_get_tenant_vpc') as gt:
                #some exception that can show up in port creation
                gt.return_value = "dev"

                with mock.patch.object(
                    lb_plugin, 'pick_subnet_id') as ps:
                    #some exception that can show up in port creation
                    ps.return_value = subnet['subnet']['id']

                    with mock.patch.object(
                        lb_plugin, '_get_cos_by_tenant_id') as gc:
                        #some exception that can show up in port creation
                        gc.return_value = "dev"

                        with self.vip(name=name, subnet=subnet, **extras) as vip:
                            for k in ('id', 'address', 'port_id', 'pool_id'):
                                self.assertTrue(vip['vip'].get(k, None))

                            self.assertEqual(
                                dict((k, v)
                                     for k, v in vip['vip'].items() if k in expected),
                                expected
                            )
            return vip

    def test_create_vip_create_port_fails(self):
        with self.subnet() as subnet:
            lb_plugin = (manager.NeutronManager.
                             get_instance().
                             get_service_plugins()[constants.LOADBALANCER])

            with mock.patch.object(
                lb_plugin, '_get_tenant_vpc') as gt:
                #some exception that can show up in port creation
                gt.return_value = "dev"

                with mock.patch.object(
                    lb_plugin, 'pick_subnet_id') as ps:
                    #some exception that can show up in port creation
                    ps.return_value = subnet['subnet']['id']
                    with self.pool() as pool:
                        with mock.patch.object(
                            lb_plugin, '_create_port_for_vip') as cp:
                            #some exception that can show up in port creation
                            cp.side_effect = n_exc.IpAddressGenerationFailure(
                                net_id=subnet['subnet']['network_id'])
                            self._create_vip(self.fmt, "vip",
                                             pool['pool']['id'], "HTTP", "80", True,
                                             subnet_id=subnet['subnet']['id'],
                                             expected_res_status=409)
                            req = self.new_list_request('vips')
                            res = self.deserialize(self.fmt,
                                                   req.get_response(self.ext_api))
                            self.assertFalse(res['vips'])


    def test_create_vip_twice_for_same_pool(self):
        """Test loadbalancer db plugin via extension and directly."""
        with self.subnet() as subnet:
            lb_plugin = (manager.NeutronManager.
                             get_instance().
                             get_service_plugins()[constants.LOADBALANCER])

            with mock.patch.object(
                lb_plugin, '_get_tenant_vpc') as gt:
                #some exception that can show up in port creation
                gt.return_value = "dev"

                with mock.patch.object(
                    lb_plugin, 'pick_subnet_id') as ps:
                    #some exception that can show up in port creation
                    ps.return_value = subnet['subnet']['id']

                    with mock.patch.object(
                        lb_plugin, '_get_cos_by_tenant_id') as gc:
                        #some exception that can show up in port creation
                        gc.return_value = "dev"
                        with self.pool(name="pool1") as pool:
                            with mock.patch.object(
                                lb_plugin, '_get_tenant_vpc') as gt:
                                #some exception that can show up in port creation
                                gt.return_value = "dev"
                                with self.vip(name='vip1', subnet=subnet, pool=pool):
                                    vip_data = {
                                        'name': 'vip1',
                                        'pool_id': pool['pool']['id'],
                                        'description': '',
                                        'protocol_port': 80,
                                        'protocol': 'HTTP',
                                        'connection_limit': -1,
                                        'admin_state_up': True,
                                        'status': 'PENDING_CREATE',
                                        'tenant_id': self._tenant_id,
                                        'session_persistence': ''
                                    }
                                    with mock.patch.object(loadbalancer_plugin.LoadBalancerPlugin, '_get_tenant_vpc',return_value="dev"):
                                        with mock.patch.object(loadbalancer_plugin.LoadBalancerPlugin, 'pick_subnet_id',return_value=subnet['subnet']['id']):
                                            self.assertRaises(loadbalancer.LBNameNotUnique,
                                                              self.plugin.create_vip,
                                                              context.get_admin_context(),
                                                              {'vip': vip_data})

    def test_update_vip_raises_vip_exists(self):
        with self.subnet() as subnet:
            lb_plugin = (manager.NeutronManager.
                 get_instance().
                 get_service_plugins()[constants.LOADBALANCER])
            with mock.patch.object(
                lb_plugin, '_get_tenant_vpc') as gt:
                #some exception that can show up in port creation
                gt.return_value = "dev"

                with mock.patch.object(
                    lb_plugin, 'pick_subnet_id') as ps:
                    #some exception that can show up in port creation
                    ps.return_value = subnet['subnet']['id']

                    with mock.patch.object(
                        lb_plugin, '_get_cos_by_tenant_id') as gc:
                        #some exception that can show up in port creation
                        gc.return_value = "dev"
                        with contextlib.nested(
                            self.pool(name="pool1"),
                            self.pool(name="pool2")
                        ) as (pool1, pool2):
                            with contextlib.nested(
                                self.vip(name='vip1', subnet=subnet, pool=pool1),
                                self.vip(name='vip2', subnet=subnet, pool=pool2)
                            ) as (vip1, vip2):
                                vip_data = {
                                    'id': vip2['vip']['id'],
                                    'name': 'vip1',
                                    'pool_id': pool1['pool']['id'],
                                }
                                self.assertRaises(loadbalancer.VipExists,
                                                  self.plugin.update_vip,
                                                  context.get_admin_context(),
                                                  vip2['vip']['id'],
                                                  {'vip': vip_data})

    def test_update_vip_change_pool(self):

        with self.subnet() as subnet:
            lb_plugin = (manager.NeutronManager.
             get_instance().
             get_service_plugins()[constants.LOADBALANCER])
            with mock.patch.object(
                lb_plugin, '_get_tenant_vpc') as gt:
                #some exception that can show up in port creation
                gt.return_value = "dev"

                with mock.patch.object(
                    lb_plugin, 'pick_subnet_id') as ps:
                    #some exception that can show up in port creation
                    ps.return_value = subnet['subnet']['id']

                    with mock.patch.object(
                        lb_plugin, '_get_cos_by_tenant_id') as gc:
                        #some exception that can show up in port creation
                        gc.return_value = "dev"
                        with contextlib.nested(
                            self.pool(name="pool1"),
                            self.pool(name="pool2")
                        ) as (pool1, pool2):
                            with self.vip(name='vip1', subnet=subnet, pool=pool1) as vip:
                                # change vip from pool1 to pool2
                                vip_data = {
                                    'id': vip['vip']['id'],
                                    'name': 'vip1',
                                    'pool_id': pool2['pool']['id'],
                                }
                                ctx = context.get_admin_context()
                                self.plugin.update_vip(ctx,
                                                       vip['vip']['id'],
                                                       {'vip': vip_data})
                                db_pool2 = (ctx.session.query(ldb.Pool).
                                            filter_by(id=pool2['pool']['id']).one())
                                db_pool1 = (ctx.session.query(ldb.Pool).
                                            filter_by(id=pool1['pool']['id']).one())
                                # check that pool1.vip became None
                                self.assertIsNone(db_pool1.vip)
                                # and pool2 got vip
                                self.assertEqual(db_pool2.vip.id, vip['vip']['id'])

    def test_create_vip_with_invalid_values(self):
        invalid = {
            'protocol': 'UNSUPPORTED',
            'protocol_port': 'NOT_AN_INT',
            'protocol_port': 1000500,
            'subnet': {'subnet': {'id': 'invalid-subnet'}}
        }

        for param, value in invalid.items():
            kwargs = {'name': 'the-vip', param: value}
            with testtools.ExpectedException(webob.exc.HTTPClientError):
                with self.vip(**kwargs):
                    pass

    def test_create_vip_with_address(self):
        self.test_create_vip(address='10.0.0.7')

    def test_create_vip_with_address_outside_subnet(self):
        with testtools.ExpectedException(webob.exc.HTTPClientError):
            self.test_create_vip(address='9.9.9.9')

    def test_create_vip_with_session_persistence(self):
        self.test_create_vip(session_persistence={'type': 'HTTP_COOKIE'})

    def test_create_vip_with_session_persistence_with_app_cookie(self):
        sp = {'type': 'APP_COOKIE', 'cookie_name': 'sessionId'}
        self.test_create_vip(session_persistence=sp)

    def test_create_vip_with_session_persistence_unsupported_type(self):
        with testtools.ExpectedException(webob.exc.HTTPClientError):
            self.test_create_vip(session_persistence={'type': 'UNSUPPORTED'})

    def test_create_vip_with_unnecessary_cookie_name(self):
        sp = {'type': "SOURCE_IP", 'cookie_name': 'sessionId'}
        with testtools.ExpectedException(webob.exc.HTTPClientError):
            self.test_create_vip(session_persistence=sp)

    def test_create_vip_with_session_persistence_without_cookie_name(self):
        sp = {'type': "APP_COOKIE"}
        with testtools.ExpectedException(webob.exc.HTTPClientError):
            self.test_create_vip(session_persistence=sp)

    def test_create_vip_with_protocol_mismatch(self):
        lb_plugin = (manager.NeutronManager.
                     get_instance().
                     get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            #some exception that can show up in port creation
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                #some exception that can show up in port creation
                ps.return_value = self._subnet_id
                with self.pool(protocol='TCP') as pool:
                    with testtools.ExpectedException(webob.exc.HTTPClientError):
                        self.test_create_vip(pool=pool, protocol='HTTP')

    def test_update_vip_with_protocol_mismatch(self):
        with self.subnet() as subnet:
            lb_plugin = (manager.NeutronManager.
                         get_instance().
                         get_service_plugins()[constants.LOADBALANCER])
            with mock.patch.object(
                lb_plugin, '_get_tenant_vpc') as gt:
                #some exception that can show up in port creation
                gt.return_value = "dev"

                with mock.patch.object(
                    lb_plugin, 'pick_subnet_id') as ps:
                    #some exception that can show up in port creation
                    ps.return_value = subnet['subnet']['id']

                    with mock.patch.object(
                        lb_plugin, '_get_cos_by_tenant_id') as gc:
                        #some exception that can show up in port creation
                        gc.return_value = "dev"

                        with self.pool(protocol='TCP',name="poolproto") as pool:
                            with self.vip(protocol='HTTP',subnet=subnet) as vip:
                                data = {'vip': {'pool_id': pool['pool']['id']}}
                                req = self.new_update_request('vips', data, vip['vip']['id'])
                                res = req.get_response(self.ext_api)
                                self.assertEqual(res.status_int,
                                                 webob.exc.HTTPClientError.code)

    def test_reset_session_persistence(self):
        name = 'vip4'
        session_persistence = {'type': "HTTP_COOKIE"}

        update_info = {'vip': {'session_persistence': None}}

        with self.subnet(cidr="10.0.6.0/24") as subnet:

            lb_plugin = (manager.NeutronManager.
                     get_instance().
                     get_service_plugins()[constants.LOADBALANCER])
            with mock.patch.object(
                lb_plugin, '_get_tenant_vpc') as gt:
                #some exception that can show up in port creation
                gt.return_value = "dev"

                with mock.patch.object(
                    lb_plugin, 'pick_subnet_id') as ps:
                    #some exception that can show up in port creation
                    ps.return_value = subnet['subnet']['id']

                    with mock.patch.object(
                        lb_plugin, '_get_cos_by_tenant_id') as gc:
                        #some exception that can show up in port creation
                        gc.return_value = "dev"

                        with self.vip(name=name, session_persistence=session_persistence) as v:
                            # Ensure that vip has been created properly
                            self.assertEqual(v['vip']['session_persistence'],
                                             session_persistence)

                            # Try resetting session_persistence
                            req = self.new_update_request('vips', update_info, v['vip']['id'])
                            res = self.deserialize(self.fmt, req.get_response(self.ext_api))

                            self.assertEqual(session_persistence, res['vip']['session_persistence'])

    def test_update_vip(self):
        name = 'new-vip'
        keys = [('name', name),
                ('address', "10.0.0.2"),
                ('protocol_port', 80),
                ('connection_limit', 100),
                ('admin_state_up', False),
                ('status', 'PENDING_UPDATE')]

        with self.subnet() as subnet:

            lb_plugin = (manager.NeutronManager.
                         get_instance().
                         get_service_plugins()[constants.LOADBALANCER])
            with mock.patch.object(
                lb_plugin, '_get_tenant_vpc') as gt:
                #some exception that can show up in port creation
                gt.return_value = "dev"

                with mock.patch.object(
                    lb_plugin, 'pick_subnet_id') as ps:
                    #some exception that can show up in port creation
                    ps.return_value =  subnet['subnet']['id']

                    with mock.patch.object(
                        lb_plugin, '_get_cos_by_tenant_id') as gc:
                        #some exception that can show up in port creation
                        gc.return_value = "dev"

                        with self.vip(name=name,subnet=subnet) as vip:
                            keys.append(('subnet_id', vip['vip']['subnet_id']))
                            data = {'vip': {'name': name,
                                            'connection_limit': 100,
                                            'session_persistence':
                                            {'type': "APP_COOKIE",
                                             'cookie_name': "jesssionId"},
                                            'admin_state_up': False}}
                            req = self.new_update_request('vips', data, vip['vip']['id'])
                            res = self.deserialize(self.fmt, req.get_response(self.ext_api))
                            for k, v in keys:
                                self.assertEqual(res['vip'][k], v)

    def test_delete_vip(self):
        with self.subnet(cidr="10.0.5.0/24") as subnet:
            lb_plugin = (manager.NeutronManager.
                     get_instance().
                     get_service_plugins()[constants.LOADBALANCER])
            with mock.patch.object(
                lb_plugin, '_get_tenant_vpc') as gt:
                #some exception that can show up in port creation
                gt.return_value = "dev"

                with mock.patch.object(
                    lb_plugin, 'pick_subnet_id') as ps:
                    #some exception that can show up in port creation
                    ps.return_value = subnet['subnet']['id']

                    with mock.patch.object(
                        lb_plugin, '_get_cos_by_tenant_id') as gc:
                        #some exception that can show up in port creation
                        gc.return_value = "dev"

                        with self.pool(name="poolvipdelete"):
                            with self.vip(do_delete=False) as vip:
                                req = self.new_delete_request('vips',
                                                              vip['vip']['id'])
                                res = req.get_response(self.ext_api)
                                self.assertEqual(res.status_int, webob.exc.HTTPNoContent.code)

    def test_delete_vip_with_resource_delete_validation(self):

        with self.subnet(cidr="10.0.5.0/24") as subnet:
            lb_plugin = (manager.NeutronManager.
                     get_instance().
                     get_service_plugins()[constants.LOADBALANCER])
            with mock.patch.object(
                lb_plugin, '_get_tenant_vpc') as gt:
                #some exception that can show up in port creation
                gt.return_value = "dev"

                with mock.patch.object(
                    lb_plugin, 'pick_subnet_id') as ps:
                    #some exception that can show up in port creation
                    ps.return_value = subnet['subnet']['id']

                    with mock.patch.object(
                        lb_plugin, '_get_cos_by_tenant_id') as gc:
                        #some exception that can show up in port creation
                        gc.return_value = "dev"

                        with self.pool(name="poolvipdelete", do_delete=True):

                            with self.vip(do_delete=True) as vip:

                                with mock.patch.object(lb_plugin, '_validate_resource_delete') as vrd:
                                    vrd.return_value = False

                                    with mock.patch.object(lb_plugin, '_get_driver_for_pool') as gdp:
                                        req = self.new_delete_request('vips',
                                                                      vip['vip']['id'])
                                        res = req.get_response(self.ext_api)
                                        response_code = res.status_int
                                        if response_code != 204:
                                            self.fail('response code expected is 204. observed '
                                                      '[' + str(res.status_int) + ']')
                                        else:
                                            assert not gdp.called


    def test_show_vip(self):
        name = "vip-show"
        keys = [('name', name),
                ('address', "10.0.0.10"),
                ('protocol_port', 80),
                ('protocol', 'HTTP'),
                ('connection_limit', -1),
                ('admin_state_up', True),
                ('status', 'PENDING_CREATE')]
        with self.subnet() as subnet:
            lb_plugin = (manager.NeutronManager.
                 get_instance().
                 get_service_plugins()[constants.LOADBALANCER])
            with mock.patch.object(
                lb_plugin, '_get_tenant_vpc') as gt:
                #some exception that can show up in port creation
                gt.return_value = "dev"

                with mock.patch.object(
                    lb_plugin, 'pick_subnet_id') as ps:
                    #some exception that can show up in port creation
                    ps.return_value = subnet['subnet']['id']

                    with mock.patch.object(
                        lb_plugin, '_get_cos_by_tenant_id') as gc:
                        #some exception that can show up in port creation
                        gc.return_value = "dev"
                        with self.vip(name=name, subnet=subnet, address='10.0.0.10') as vip:
                            req = self.new_show_request('vips',
                                                        vip['vip']['id'])
                            res = self.deserialize(self.fmt, req.get_response(self.ext_api))
                            for k, v in keys:
                                self.assertEqual(res['vip'][k], v)

    def test_list_vips(self):
        name = "vips-list"
        keys = [('name', name),
                ('address', "10.0.0.2"),
                ('protocol_port', 80),
                ('protocol', 'HTTP'),
                ('connection_limit', -1),
                ('admin_state_up', True),
                ('status', 'PENDING_CREATE')]
        with self.subnet() as subnet:
            lb_plugin = (manager.NeutronManager.
                 get_instance().
                 get_service_plugins()[constants.LOADBALANCER])
            with mock.patch.object(
                lb_plugin, '_get_tenant_vpc') as gt:
                #some exception that can show up in port creation
                gt.return_value = "dev"

                with mock.patch.object(
                    lb_plugin, 'pick_subnet_id') as ps:
                    #some exception that can show up in port creation
                    ps.return_value = subnet['subnet']['id']

                    with mock.patch.object(
                        lb_plugin, '_get_cos_by_tenant_id') as gc:
                        #some exception that can show up in port creation
                        gc.return_value = "dev"
                        with self.vip(name=name, subnet=subnet) as vip:
                            keys.append(('subnet_id', vip['vip']['subnet_id']))
                            req = self.new_list_request('vips')
                            res = self.deserialize(self.fmt, req.get_response(self.ext_api))
                            self.assertEqual(len(res['vips']), 1)
                            for k, v in keys:
                                self.assertEqual(res['vips'][0][k], v)

    def test_list_vips_with_sort_emulated(self):
        with self.subnet() as subnet:
            lb_plugin = (manager.NeutronManager.
                 get_instance().
                 get_service_plugins()[constants.LOADBALANCER])
            with mock.patch.object(
                lb_plugin, '_get_tenant_vpc') as gt:
                #some exception that can show up in port creation
                gt.return_value = "dev"

                with mock.patch.object(
                    lb_plugin, 'pick_subnet_id') as ps:
                    #some exception that can show up in port creation
                    ps.return_value = subnet['subnet']['id']

                    with mock.patch.object(
                        lb_plugin, '_get_cos_by_tenant_id') as gc:
                        #some exception that can show up in port creation
                        gc.return_value = "dev"
                        with contextlib.nested(
                            self.pool(name="poolsort1"),
                            self.pool(name="poolsort2"),
                            self.pool(name="poolsort3")
                        ) as (pool1, pool2,pool3):
                            with contextlib.nested(
                                self.vip(pool=pool1, name='vip1', subnet=subnet, protocol_port=81),
                                self.vip(pool=pool2, name='vip2', subnet=subnet, protocol_port=82),
                                self.vip(pool=pool3, name='vip3', subnet=subnet, protocol_port=82)
                            ) as (vip1, vip2, vip3):
                                self._test_list_with_sort(
                                    'vip',
                                    (vip1, vip3, vip2),
                                    [('protocol_port', 'asc'), ('name', 'desc')]
                )

    def test_list_vips_with_pagination_emulated(self):
        with self.subnet() as subnet:
            lb_plugin = (manager.NeutronManager.
                 get_instance().
                 get_service_plugins()[constants.LOADBALANCER])
            with mock.patch.object(
                lb_plugin, '_get_tenant_vpc') as gt:
                #some exception that can show up in port creation
                gt.return_value = "dev"

                with mock.patch.object(
                    lb_plugin, 'pick_subnet_id') as ps:
                    #some exception that can show up in port creation
                    ps.return_value = subnet['subnet']['id']

                    with mock.patch.object(
                        lb_plugin, '_get_cos_by_tenant_id') as gc:
                        #some exception that can show up in port creation
                        gc.return_value = "dev"
                        with contextlib.nested(
                            self.pool(name="poolpage1"),
                            self.pool(name="poolpage2"),
                            self.pool(name="poolpage3")
                        ) as (pool1, pool2,pool3):
                            with contextlib.nested(self.vip(pool=pool1, name='vip1', subnet=subnet),
                                                   self.vip(pool=pool2, name='vip2', subnet=subnet),
                                                   self.vip(pool=pool3, name='vip3', subnet=subnet)
                                                   ) as (vip1, vip2, vip3):
                                self._test_list_with_pagination('vip',
                                                                (vip1, vip2, vip3),
                                                                ('name', 'asc'), 2, 2)

    def test_list_vips_with_pagination_reverse_emulated(self):
        with self.subnet() as subnet:
            lb_plugin = (manager.NeutronManager.
                 get_instance().
                 get_service_plugins()[constants.LOADBALANCER])
            with mock.patch.object(
                lb_plugin, '_get_tenant_vpc') as gt:
                #some exception that can show up in port creation
                gt.return_value = "dev"

                with mock.patch.object(
                    lb_plugin, 'pick_subnet_id') as ps:
                    #some exception that can show up in port creation
                    ps.return_value = subnet['subnet']['id']

                    with mock.patch.object(
                        lb_plugin, '_get_cos_by_tenant_id') as gc:
                        #some exception that can show up in port creation
                        gc.return_value = "dev"
                        with contextlib.nested(
                            self.pool(name="poolsort1"),
                            self.pool(name="poolsort2"),
                            self.pool(name="poolsort3")
                        ) as (pool1, pool2,pool3):
                            with contextlib.nested(self.vip(pool=pool1, name='vip1', subnet=subnet),
                                                   self.vip(pool=pool2, name='vip2', subnet=subnet),
                                                   self.vip(pool=pool3, name='vip3', subnet=subnet)
                                                   ) as (vip1, vip2, vip3):
                                self._test_list_with_pagination_reverse('vip',
                                                                        (vip1, vip2, vip3),
                                                                        ('name', 'asc'), 2, 2)

    def test_create_pool_with_invalid_values(self):
        name = 'pool3'

        pool = self.pool(name=name, protocol='UNSUPPORTED')
        self.assertRaises(webob.exc.HTTPClientError, pool.__enter__)

        pool = self.pool(name=name, lb_method='UNSUPPORTED')
        self.assertRaises(webob.exc.HTTPClientError, pool.__enter__)

    def test_create_pool_with_calling_caseinsensitive_subnet(self,
             fmt=None, name='pool1', lb_method='ROUND_ROBIN',
             protocol='HTTP', admin_state_up=True, do_delete=True,
             expected_res_status=201, **kwargs):

        cfg.CONF.set_override('lbaas_vpc_vip_subnets',
                              '''{"dev":["0c798ed8-33ba-11e2-8b28-000c291c4d14"],"mpt-prod":["48f8c505-4b09-4432-918b-3fe54eb20ff2"]}'''
                              )
        data = {'pool': {'name': name,
                         'subnet_id': _subnet_id,
                         'lb_method': lb_method,
                         'protocol': protocol,
                         'admin_state_up': admin_state_up,
                         'tenant_id': self._tenant_id,
                         'tenant_vpc' : self._tenant_vpc}}
        for arg in ('description', 'provider', 'subnet_id'):
            if arg in kwargs and kwargs[arg] is not None:
                data['pool'][arg] = kwargs[arg]
        lb_plugin = (manager.NeutronManager.
                 get_instance().
                 get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            # Return upper case "D"
            gt.return_value = "Dev"
            pool_req = self.new_create_request('pools', data, fmt)
            pool_res = pool_req.get_response(self.ext_api)
            if expected_res_status:
                self.assertEqual(pool_res.status_int, expected_res_status)

            return pool_res


    def _create_pool_directly_via_plugin(self, provider_name):

        #default provider will be haproxy
        prov1 = (constants.LOADBALANCER +
                 ':lbaas:' + NOOP_DRIVER_KLASS)
        prov2 = (constants.LOADBALANCER +
                 ':haproxy:neutron.services.loadbalancer.'
                 'drivers.haproxy.plugin_driver.HaproxyOnHostPluginDriver'
                 ':default')
        cfg.CONF.set_override('service_provider',
                              [prov1, prov2],
                              'service_providers')
        sdb.ServiceTypeManager._instance = None
        with mock.patch.object(loadbalancer_plugin.LoadBalancerPlugin, '_get_tenant_vpc',return_value="dev"):
            with mock.patch.object(loadbalancer_plugin.LoadBalancerPlugin, 'pick_subnet_id',return_value=_subnet_id):
                self.plugin = loadbalancer_plugin.LoadBalancerPlugin()
                with self.subnet() as subnet:
                    ctx = context.get_admin_context()
                    #create pool with another provider - lbaas
                    #which is noop driver
                    pool = {'name': 'pool1',
                            'subnet_id': subnet['subnet']['id'],
                            'lb_method': 'ROUND_ROBIN',
                            'protocol': 'HTTP',
                            'admin_state_up': True,
                            'tenant_id': self._tenant_id,
                            'provider': provider_name,
                            'label':'',
                            'description': ''}
                    self.plugin.create_pool(ctx, {'pool': pool})
                    assoc = ctx.session.query(sdb.ProviderResourceAssociation).one()
                    self.assertEqual(assoc.provider_name,
                                     pconf.normalize_provider_name(provider_name))

    def test_create_pool_another_provider(self):
        self._create_pool_directly_via_plugin('lbaas')

    def test_create_pool_unnormalized_provider_name(self):
        self._create_pool_directly_via_plugin('LBAAS')

    def test_create_pool_unexisting_provider(self):
        self.assertRaises(
            pconf.ServiceProviderNotFound,
            self._create_pool_directly_via_plugin, 'unexisting')


    def test_create_pool(self):
        name = "pool1"
        keys = [('name', name),
                ('subnet_id', self._subnet_id),
                ('tenant_id', self._tenant_id),
                ('protocol', 'HTTP'),
                ('lb_method', 'ROUND_ROBIN'),
                ('admin_state_up', True),
                ('status', 'PENDING_CREATE')]


        lb_plugin = (manager.NeutronManager.
                             get_instance().
                             get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            #some exception that can show up in port creation
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                #some exception that can show up in port creation
                ps.return_value = self._subnet_id

                with self.pool(name=name) as pool:
                    for k, v in keys:
                        self.assertEqual(pool['pool'][k], v)

    def test_create_pool_with_members(self):
        name = "pool2"

        lb_plugin = (manager.NeutronManager.
                             get_instance().
                             get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            #some exception that can show up in port creation
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                #some exception that can show up in port creation
                ps.return_value = self._subnet_id
                with self.pool(name=name) as pool:
                    pool_id = pool['pool']['id']
                    res1 = self._create_member(self.fmt,
                                               '192.168.1.100',
                                               '80',
                                               True,
                                               pool_id=pool_id,
                                               weight=1)
                    req = self.new_show_request('pools',
                                                pool_id,
                                                fmt=self.fmt)
                    pool_updated = self.deserialize(
                        self.fmt,
                        req.get_response(self.ext_api)
                    )

                    member1 = self.deserialize(self.fmt, res1)
                    self.assertEqual(member1['member']['id'],
                                     pool_updated['pool']['members'][0])
                    self.assertEqual(len(pool_updated['pool']['members']), 1)

                    keys = [('address', '192.168.1.100'),
                            ('protocol_port', 80),
                            ('weight', 1),
                            ('pool_id', pool_id),
                            ('admin_state_up', True),
                            ('status', 'PENDING_CREATE')]
                    for k, v in keys:
                        self.assertEqual(member1['member'][k], v)
                    self._delete('members', member1['member']['id'])

    def test_delete_pool(self):
        lb_plugin = (manager.NeutronManager.
                     get_instance().
                     get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            #some exception that can show up in port creation
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                #some exception that can show up in port creation
                ps.return_value = self._subnet_id
                with self.pool(do_delete=False) as pool:
                    with self.member(do_delete=False,
                                     pool_id=pool['pool']['id']):
                        req = self.new_delete_request('pools',
                                                      pool['pool']['id'])
                        res = req.get_response(self.ext_api)
                        self.assertEqual(res.status_int, webob.exc.HTTPNoContent.code)

    def test_delete_pool_preserve_state(self):
        with self.subnet(cidr="10.0.5.0/24") as subnet:
            lb_plugin = (manager.NeutronManager.
                         get_instance().
                         get_service_plugins()[constants.LOADBALANCER])
            with mock.patch.object(
                lb_plugin, '_get_tenant_vpc') as gt:
                #some exception that can show up in port creation
                gt.return_value = "dev"

                with mock.patch.object(
                    lb_plugin, 'pick_subnet_id') as ps:
                    #some exception that can show up in port creation
                    ps.return_value = subnet['subnet']['id']

                    with mock.patch.object(
                        lb_plugin, '_get_cos_by_tenant_id') as gc:
                        #some exception that can show up in port creation
                        gc.return_value = "dev"
                        with self.pool(do_delete=False) as pool:
                            with self.vip(pool=pool):
                                req = self.new_delete_request('pools',
                                                              pool['pool']['id'])
                                res = req.get_response(self.ext_api)
                                self.assertEqual(res.status_int, webob.exc.HTTPConflict.code)
                                req = self.new_show_request('pools',
                                                            pool['pool']['id'],
                                                            fmt=self.fmt)
                                res = req.get_response(self.ext_api)
                                self.assertEqual(res.status_int, webob.exc.HTTPOk.code)
                                res = self.deserialize(self.fmt,
                                                       req.get_response(self.ext_api))
                                self.assertEqual(res['pool']['status'],
                                                 constants.PENDING_CREATE)
                            req = self.new_delete_request('pools',
                                                          pool['pool']['id'])

    def test_show_pool(self):
        name = "pool1"
        keys = [('name', name),
                ('subnet_id', self._subnet_id),
                ('tenant_id', self._tenant_id),
                ('protocol', 'HTTP'),
                ('lb_method', 'ROUND_ROBIN'),
                ('admin_state_up', True),
                ('status', 'PENDING_CREATE')]

        lb_plugin = (manager.NeutronManager.
                     get_instance().
                     get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            #some exception that can show up in port creation
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                #some exception that can show up in port creation
                ps.return_value = self._subnet_id
                with self.pool(name=name) as pool:
                    req = self.new_show_request('pools',
                                                pool['pool']['id'],
                                                fmt=self.fmt)
                    res = self.deserialize(self.fmt, req.get_response(self.ext_api))
                    for k, v in keys:
                        self.assertEqual(res['pool'][k], v)

    def test_list_pools_with_sort_emulated(self):
        lb_plugin = (manager.NeutronManager.
                     get_instance().
                     get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            #some exception that can show up in port creation
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                #some exception that can show up in port creation
                ps.return_value = self._subnet_id
                with contextlib.nested(self.pool(name='p1'),
                                       self.pool(name='p2'),
                                       self.pool(name='p3')
                                       ) as (p1, p2, p3):
                    self._test_list_with_sort('pool', (p3, p2, p1),
                                              [('name', 'desc')])

    def test_list_pools_with_pagination_emulated(self):
        lb_plugin = (manager.NeutronManager.
                     get_instance().
                     get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            #some exception that can show up in port creation
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                #some exception that can show up in port creation
                ps.return_value = self._subnet_id
                with contextlib.nested(self.pool(name='p1'),
                                       self.pool(name='p2'),
                                       self.pool(name='p3')
                                       ) as (p1, p2, p3):
                    self._test_list_with_pagination('pool',
                                                    (p1, p2, p3),
                                                    ('name', 'asc'), 2, 2)



    def test_list_pools_with_pagination_reverse_emulated(self):
        lb_plugin = (manager.NeutronManager.
                     get_instance().
                     get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            #some exception that can show up in port creation
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                #some exception that can show up in port creation
                ps.return_value = self._subnet_id
                with contextlib.nested(self.pool(name='p1'),
                                       self.pool(name='p2'),
                                       self.pool(name='p3')
                                       ) as (p1, p2, p3):
                    self._test_list_with_pagination_reverse('pool',
                                                            (p1, p2, p3),
                                                            ('name', 'asc'), 2, 2)

    def test_create_member(self):
        lb_plugin = (manager.NeutronManager.
                 get_instance().
                 get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            #some exception that can show up in port creation
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                #some exception that can show up in port creation
                ps.return_value = _subnet_id

                with mock.patch.object(
                    lb_plugin, '_get_cos_by_tenant_id') as gc:
                    #some exception that can show up in port creation
                    gc.return_value = "dev"
                    with self.pool() as pool:
                        pool_id = pool['pool']['id']
                        with self.member(address='192.168.1.100',
                                         protocol_port=80,
                                         pool_id=pool_id) as member1:
                            with self.member(address='192.168.1.101',
                                             protocol_port=80,
                                             pool_id=pool_id) as member2:
                                req = self.new_show_request('pools',
                                                            pool_id,
                                                            fmt=self.fmt)
                                pool_update = self.deserialize(
                                    self.fmt,
                                    req.get_response(self.ext_api)
                                )
                                self.assertIn(member1['member']['id'],
                                              pool_update['pool']['members'])
                                self.assertIn(member2['member']['id'],
                                              pool_update['pool']['members'])

    def test_create_same_member_in_same_pool_raises_member_exists(self):
        lb_plugin = (manager.NeutronManager.
                     get_instance().
                     get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            #some exception that can show up in port creation
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                #some exception that can show up in port creation
                ps.return_value = self._subnet_id
                with self.subnet():
                    with self.pool(name="pool1") as pool:
                        pool_id = pool['pool']['id']
                        with self.member(address='192.168.1.100',
                                         protocol_port=80,
                                         pool_id=pool_id):
                            member_data = {
                                'address': '192.168.1.100',
                                'protocol_port': 80,
                                'weight': 1,
                                'admin_state_up': True,
                                'pool_id': pool_id
                            }
                            self.assertRaises(loadbalancer.MemberAlreadyExistsInPool,
                                              self.plugin.create_member,
                                              context.get_admin_context(),
                                              {'member': member_data})

    def test_update_member(self):
        lb_plugin = (manager.NeutronManager.
                 get_instance().
                 get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            #some exception that can show up in port creation
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                #some exception that can show up in port creation
                ps.return_value = _subnet_id

                with mock.patch.object(
                    lb_plugin, '_get_cos_by_tenant_id') as gc:
                    #some exception that can show up in port creation
                    gc.return_value = "dev"

                    with self.pool(name="pool1") as pool1:
                        with self.pool(name="pool2") as pool2:
                            keys = [('address', "192.168.1.100"),
                                    ('tenant_id', self._tenant_id),
                                    ('protocol_port', 80),
                                    ('weight', 10),
                                    ('pool_id', pool2['pool']['id']),
                                    ('admin_state_up', False),
                                    ('status', 'PENDING_UPDATE')]
                            with self.member(pool_id=pool1['pool']['id']) as member:
                                req = self.new_show_request('pools',
                                                            pool1['pool']['id'],
                                                            fmt=self.fmt)
                                pool1_update = self.deserialize(
                                    self.fmt,
                                    req.get_response(self.ext_api)
                                )
                                self.assertEqual(len(pool1_update['pool']['members']), 1)

                                req = self.new_show_request('pools',
                                                            pool2['pool']['id'],
                                                            fmt=self.fmt)
                                pool2_update = self.deserialize(
                                    self.fmt,
                                    req.get_response(self.ext_api)
                                )
                                self.assertEqual(len(pool1_update['pool']['members']), 1)
                                self.assertEqual(len(pool2_update['pool']['members']), 0)

                                data = {'member': {'pool_id': pool2['pool']['id'],
                                                   'weight': 10,
                                                   'admin_state_up': False}}
                                req = self.new_update_request('members',
                                                              data,
                                                              member['member']['id'])
                                res = self.deserialize(
                                    self.fmt,
                                    req.get_response(self.ext_api)
                                )
                                for k, v in keys:
                                    self.assertEqual(res['member'][k], v)

                                req = self.new_show_request('pools',
                                                            pool1['pool']['id'],
                                                            fmt=self.fmt)
                                pool1_update = self.deserialize(
                                    self.fmt,
                                    req.get_response(self.ext_api)
                                )

                                req = self.new_show_request('pools',
                                                            pool2['pool']['id'],
                                                            fmt=self.fmt)
                                pool2_update = self.deserialize(
                                    self.fmt,
                                    req.get_response(self.ext_api)
                                )

                                self.assertEqual(len(pool2_update['pool']['members']), 1)
                                self.assertEqual(len(pool1_update['pool']['members']), 0)


    def test_delete_member(self):
        lb_plugin = (manager.NeutronManager.
                 get_instance().
                 get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            #some exception that can show up in port creation
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                #some exception that can show up in port creation
                ps.return_value = _subnet_id

                with mock.patch.object(
                    lb_plugin, '_get_cos_by_tenant_id') as gc:
                    #some exception that can show up in port creation
                    gc.return_value = "dev"
                    with self.pool() as pool:
                        pool_id = pool['pool']['id']
                        with self.member(pool_id=pool_id,
                                         do_delete=False) as member:
                            req = self.new_delete_request('members',
                                                          member['member']['id'])
                            res = req.get_response(self.ext_api)
                            self.assertEqual(res.status_int, webob.exc.HTTPNoContent.code)

                            req = self.new_show_request('pools',
                                                        pool_id,
                                                        fmt=self.fmt)
                            pool_update = self.deserialize(
                                self.fmt,
                                req.get_response(self.ext_api)
                            )
                            self.assertEqual(len(pool_update['pool']['members']), 0)

    def test_show_member(self):
        lb_plugin = (manager.NeutronManager.
                 get_instance().
                 get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            #some exception that can show up in port creation
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                #some exception that can show up in port creation
                ps.return_value = _subnet_id

                with mock.patch.object(
                    lb_plugin, '_get_cos_by_tenant_id') as gc:
                    #some exception that can show up in port creation
                    gc.return_value = "dev"
                    with self.pool() as pool:
                        keys = [('address', "192.168.1.100"),
                                ('tenant_id', self._tenant_id),
                                ('protocol_port', 80),
                                ('weight', 1),
                                ('pool_id', pool['pool']['id']),
                                ('admin_state_up', True),
                                ('status', 'PENDING_CREATE')]
                        with self.member(pool_id=pool['pool']['id']) as member:
                            req = self.new_show_request('members',
                                                        member['member']['id'],
                                                        fmt=self.fmt)
                            res = self.deserialize(
                                self.fmt,
                                req.get_response(self.ext_api)
                            )
                            for k, v in keys:
                                self.assertEqual(res['member'][k], v)

    def test_list_members_with_sort_emulated(self):
        lb_plugin = (manager.NeutronManager.
                 get_instance().
                 get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            #some exception that can show up in port creation
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                #some exception that can show up in port creation
                ps.return_value = _subnet_id

                with mock.patch.object(
                    lb_plugin, '_get_cos_by_tenant_id') as gc:
                    #some exception that can show up in port creation
                    gc.return_value = "dev"
                    with self.pool() as pool:
                        with contextlib.nested(self.member(pool_id=pool['pool']['id'],
                                                           protocol_port=81),
                                               self.member(pool_id=pool['pool']['id'],
                                                           protocol_port=82),
                                               self.member(pool_id=pool['pool']['id'],
                                                           protocol_port=83)
                                               ) as (m1, m2, m3):
                            self._test_list_with_sort('member', (m3, m2, m1),
                                                      [('protocol_port', 'desc')])

    def test_list_members_with_pagination_emulated(self):
        lb_plugin = (manager.NeutronManager.
                 get_instance().
                 get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            #some exception that can show up in port creation
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                #some exception that can show up in port creation
                ps.return_value = _subnet_id

                with mock.patch.object(
                    lb_plugin, '_get_cos_by_tenant_id') as gc:
                    #some exception that can show up in port creation
                    gc.return_value = "dev"
                    with self.pool() as pool:
                        with contextlib.nested(self.member(pool_id=pool['pool']['id'],
                                                           protocol_port=81),
                                               self.member(pool_id=pool['pool']['id'],
                                                           protocol_port=82),
                                               self.member(pool_id=pool['pool']['id'],
                                                           protocol_port=83)
                                               ) as (m1, m2, m3):
                            self._test_list_with_pagination(
                                'member', (m1, m2, m3), ('protocol_port', 'asc'), 2, 2
                            )

    def test_list_members_with_pagination_reverse_emulated(self):
        lb_plugin = (manager.NeutronManager.
                 get_instance().
                 get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            #some exception that can show up in port creation
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                #some exception that can show up in port creation
                ps.return_value = _subnet_id

                with mock.patch.object(
                    lb_plugin, '_get_cos_by_tenant_id') as gc:
                    #some exception that can show up in port creation
                    gc.return_value = "dev"
                    with self.pool() as pool:
                        with contextlib.nested(self.member(pool_id=pool['pool']['id'],
                                                           protocol_port=81),
                                               self.member(pool_id=pool['pool']['id'],
                                                           protocol_port=82),
                                               self.member(pool_id=pool['pool']['id'],
                                                           protocol_port=83)
                                               ) as (m1, m2, m3):
                            self._test_list_with_pagination_reverse(
                                'member', (m1, m2, m3), ('protocol_port', 'asc'), 2, 2
                            )

    def test_create_healthmonitor(self):
        keys = [('type', "TCP"),
                ('tenant_id', self._tenant_id),
                ('delay', 30),
                ('timeout', 10),
                ('max_retries', 3),
                ('admin_state_up', True)]
        with self.health_monitor() as monitor:
            for k, v in keys:
                self.assertEqual(monitor['health_monitor'][k], v)

    def test_create_health_monitor_with_timeout_delay_invalid(self):
        data = {'health_monitor': {'type': type,
                                   'delay': 3,
                                   'timeout': 6,
                                   'max_retries': 2,
                                   'admin_state_up': True,
                                   'tenant_id': self._tenant_id}}
        req = self.new_create_request('health_monitors', data, self.fmt)
        res = req.get_response(self.ext_api)
        self.assertEqual(webob.exc.HTTPBadRequest.code, res.status_int)

    def test_update_health_monitor_with_timeout_delay_invalid(self):
        with self.health_monitor() as monitor:
            data = {'health_monitor': {'delay': 10,
                                       'timeout': 20,
                                       'max_retries': 2,
                                       'admin_state_up': False}}
            req = self.new_update_request("health_monitors",
                                          data,
                                          monitor['health_monitor']['id'])
            res = req.get_response(self.ext_api)
            self.assertEqual(webob.exc.HTTPBadRequest.code, res.status_int)

    def test_update_healthmonitor(self):
        keys = [('type', "TCP"),
                ('tenant_id', self._tenant_id),
                ('delay', 20),
                ('timeout', 20),
                ('max_retries', 2),
                ('admin_state_up', False)]
        with self.health_monitor() as monitor:
            data = {'health_monitor': {'delay': 20,
                                       'timeout': 20,
                                       'max_retries': 2,
                                       'admin_state_up': False}}
            req = self.new_update_request("health_monitors",
                                          data,
                                          monitor['health_monitor']['id'])
            res = self.deserialize(self.fmt, req.get_response(self.ext_api))
            for k, v in keys:
                self.assertEqual(res['health_monitor'][k], v)

    def test_delete_healthmonitor(self):
        with self.health_monitor(do_delete=False) as monitor:
            ctx = context.get_admin_context()
            qry = ctx.session.query(ldb.HealthMonitor)
            qry = qry.filter_by(id=monitor['health_monitor']['id'])
            self.assertIsNotNone(qry.first())

            req = self.new_delete_request('health_monitors',
                                          monitor['health_monitor']['id'])
            res = req.get_response(self.ext_api)
            self.assertEqual(res.status_int, webob.exc.HTTPNoContent.code)
            qry = ctx.session.query(ldb.HealthMonitor)
            qry = qry.filter_by(id=monitor['health_monitor']['id'])
            self.assertIsNone(qry.first())

    def test_delete_healthmonitor_with_associations_raises(self):
        lb_plugin = (manager.NeutronManager.
                 get_instance().
                 get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            #some exception that can show up in port creation
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                #some exception that can show up in port creation
                ps.return_value = _subnet_id

                with mock.patch.object(
                    lb_plugin, '_get_cos_by_tenant_id') as gc:
                    #some exception that can show up in port creation
                    gc.return_value = "dev"

                    with self.health_monitor(type='HTTP') as monitor:
                        with self.pool() as pool:
                            data = {
                                'health_monitor': {
                                    'id': monitor['health_monitor']['id'],
                                    'tenant_id': self._tenant_id
                                }
                            }
                            req = self.new_create_request(
                                'pools',
                                data,
                                fmt=self.fmt,
                                id=pool['pool']['id'],
                                subresource='health_monitors')
                            res = req.get_response(self.ext_api)
                            self.assertEqual(res.status_int, webob.exc.HTTPCreated.code)

                            ctx = context.get_admin_context()

                            # check if we actually have corresponding Pool associations
                            qry = ctx.session.query(ldb.PoolMonitorAssociation)
                            qry = qry.filter_by(monitor_id=monitor['health_monitor']['id'])
                            self.assertTrue(qry.all())
                            # try to delete the HealthMonitor instance
                            req = self.new_delete_request(
                                'health_monitors',
                                monitor['health_monitor']['id']
                            )
                            res = req.get_response(self.ext_api)
                            self.assertEqual(res.status_int, webob.exc.HTTPConflict.code)

                            qry = ctx.session.query(ldb.HealthMonitor)
                            qry = qry.filter_by(id=monitor['health_monitor']['id'])
                            self.assertIsNotNone(qry.first())
                            # check if all corresponding Pool associations are not deleted
                            qry = ctx.session.query(ldb.PoolMonitorAssociation)
                            qry = qry.filter_by(monitor_id=monitor['health_monitor']['id'])
                            self.assertTrue(qry.all())

    def test_show_healthmonitor(self):
        with self.health_monitor() as monitor:
            keys = [('type', "TCP"),
                    ('tenant_id', self._tenant_id),
                    ('delay', 30),
                    ('timeout', 10),
                    ('max_retries', 3),
                    ('admin_state_up', True)]
            req = self.new_show_request('health_monitors',
                                        monitor['health_monitor']['id'],
                                        fmt=self.fmt)
            res = self.deserialize(self.fmt, req.get_response(self.ext_api))
            for k, v in keys:
                self.assertEqual(res['health_monitor'][k], v)

    def test_list_healthmonitors_with_sort_emulated(self):
        with contextlib.nested(self.health_monitor(delay=30),
                               self.health_monitor(delay=31),
                               self.health_monitor(delay=32)
                               ) as (m1, m2, m3):
            self._test_list_with_sort('health_monitor', (m3, m2, m1),
                                      [('delay', 'desc')])

    def test_list_healthmonitors_with_pagination_emulated(self):
        with contextlib.nested(self.health_monitor(delay=30),
                               self.health_monitor(delay=31),
                               self.health_monitor(delay=32)
                               ) as (m1, m2, m3):
            self._test_list_with_pagination('health_monitor',
                                            (m1, m2, m3),
                                            ('delay', 'asc'), 2, 2)

    def test_list_healthmonitors_with_pagination_reverse_emulated(self):
        with contextlib.nested(self.health_monitor(delay=30),
                               self.health_monitor(delay=31),
                               self.health_monitor(delay=32)
                               ) as (m1, m2, m3):
            self._test_list_with_pagination_reverse('health_monitor',
                                                    (m1, m2, m3),
                                                    ('delay', 'asc'), 2, 2)

    def test_update_pool_stats_with_no_stats(self):
        keys = ["bytes_in", "bytes_out",
                "active_connections",
                "total_connections"]
        lb_plugin = (manager.NeutronManager.
                     get_instance().
                     get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            #some exception that can show up in port creation
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                #some exception that can show up in port creation
                ps.return_value = self._subnet_id
                with self.pool() as pool:
                    pool_id = pool['pool']['id']
                    ctx = context.get_admin_context()
                    self.plugin.update_pool_stats(ctx, pool_id)
                    pool_obj = ctx.session.query(ldb.Pool).filter_by(id=pool_id).one()
                    for key in keys:
                        self.assertEqual(pool_obj.stats.__dict__[key], 0)

    def test_update_pool_stats_with_negative_values(self):
        stats_data = {"bytes_in": -1,
                      "bytes_out": -2,
                      "active_connections": -3,
                      "total_connections": -4}
        lb_plugin = (manager.NeutronManager.
                     get_instance().
                     get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            #some exception that can show up in port creation
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                #some exception that can show up in port creation
                ps.return_value = self._subnet_id
                for k, v in stats_data.items():
                    self._test_update_pool_stats_with_negative_value(k, v)

    def _test_update_pool_stats_with_negative_value(self, k, v):
        with self.pool() as pool:
            pool_id = pool['pool']['id']
            ctx = context.get_admin_context()
            self.assertRaises(ValueError, self.plugin.update_pool_stats,
                              ctx, pool_id, {k: v})


    def test_update_pool_stats(self):
        stats_data = {"bytes_in": 1,
                      "bytes_out": 2,
                      "active_connections": 3,
                      "total_connections": 4}

        lb_plugin = (manager.NeutronManager.
                     get_instance().
                     get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            #some exception that can show up in port creation
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                #some exception that can show up in port creation
                ps.return_value = self._subnet_id
                with self.pool() as pool:
                    pool_id = pool['pool']['id']
                    ctx = context.get_admin_context()
                    self.plugin.update_pool_stats(ctx, pool_id, stats_data)
                    pool_obj = ctx.session.query(ldb.Pool).filter_by(id=pool_id).one()
                    for k, v in stats_data.items():
                        self.assertEqual(pool_obj.stats.__dict__[k], v)

    def test_update_pool_stats_members_statuses(self):
        lb_plugin = (manager.NeutronManager.
                     get_instance().
                     get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            #some exception that can show up in port creation
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                #some exception that can show up in port creation
                ps.return_value = self._subnet_id
                with self.pool() as pool:
                    pool_id = pool['pool']['id']
                    with self.member(pool_id=pool_id) as member:
                        member_id = member['member']['id']
                        stats_data = {'members': {
                            member_id: {
                                'status': 'INACTIVE'
                            }
                        }}
                        ctx = context.get_admin_context()
                        member = self.plugin.get_member(ctx, member_id)
                        self.assertEqual('PENDING_CREATE', member['status'])
                        self.plugin.update_pool_stats(ctx, pool_id, stats_data)
                        member = self.plugin.get_member(ctx, member_id)
                        self.assertEqual('INACTIVE', member['status'])

    def test_get_pool_stats(self):
        keys = [("bytes_in", 0),
                ("bytes_out", 0),
                ("active_connections", 0),
                ("total_connections", 0)]

        lb_plugin = (manager.NeutronManager.
                     get_instance().
                     get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            #some exception that can show up in port creation
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                #some exception that can show up in port creation
                ps.return_value = self._subnet_id
                with self.pool() as pool:
                    req = self.new_show_request("pools",
                                                pool['pool']['id'],
                                                subresource="stats",
                                                fmt=self.fmt)
                    res = self.deserialize(self.fmt, req.get_response(self.ext_api))
                    for k, v in keys:
                        self.assertEqual(res['stats'][k], v)

    def test_create_healthmonitor_of_pool(self):
        lb_plugin = (manager.NeutronManager.
                     get_instance().
                     get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            #some exception that can show up in port creation
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                #some exception that can show up in port creation
                ps.return_value = self._subnet_id

                with self.health_monitor(type="TCP") as monitor1:
                    with self.health_monitor(type="HTTP") as monitor2:
                        with self.pool() as pool:
                            data = {"health_monitor": {
                                    "id": monitor1['health_monitor']['id'],
                                    'tenant_id': self._tenant_id}}
                            req = self.new_create_request(
                                "pools",
                                data,
                                fmt=self.fmt,
                                id=pool['pool']['id'],
                                subresource="health_monitors")
                            res = req.get_response(self.ext_api)
                            self.assertEqual(res.status_int,
                                             webob.exc.HTTPCreated.code)

                            data = {"health_monitor": {
                                    "id": monitor2['health_monitor']['id'],
                                    'tenant_id': self._tenant_id}}
                            req = self.new_create_request(
                                "pools",
                                data,
                                fmt=self.fmt,
                                id=pool['pool']['id'],
                                subresource="health_monitors")
                            res = req.get_response(self.ext_api)
                            self.assertEqual(res.status_int,
                                             webob.exc.HTTPCreated.code)

                            req = self.new_show_request(
                                'pools',
                                pool['pool']['id'],
                                fmt=self.fmt)
                            res = self.deserialize(
                                self.fmt,
                                req.get_response(self.ext_api)
                            )
                            self.assertIn(monitor1['health_monitor']['id'],
                                          res['pool']['health_monitors'])
                            self.assertIn(monitor2['health_monitor']['id'],
                                          res['pool']['health_monitors'])
                            expected = [
                                {'monitor_id': monitor1['health_monitor']['id'],
                                 'status': 'PENDING_CREATE',
                                 'status_description': None},
                                {'monitor_id': monitor2['health_monitor']['id'],
                                 'status': 'PENDING_CREATE',
                                 'status_description': None}]
                            self.assertEqual(
                                sorted(expected),
                                sorted(res['pool']['health_monitors_status']))

    def test_delete_healthmonitor_of_pool(self):
        lb_plugin = (manager.NeutronManager.
                     get_instance().
                     get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            #some exception that can show up in port creation
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                #some exception that can show up in port creation
                ps.return_value = self._subnet_id

                with self.health_monitor(type="TCP") as monitor1:
                    with self.health_monitor(type="HTTP") as monitor2:
                        with self.pool() as pool:
                            # add the monitors to the pool
                            data = {"health_monitor": {
                                    "id": monitor1['health_monitor']['id'],
                                    'tenant_id': self._tenant_id}}
                            req = self.new_create_request(
                                "pools",
                                data,
                                fmt=self.fmt,
                                id=pool['pool']['id'],
                                subresource="health_monitors")
                            res = req.get_response(self.ext_api)
                            self.assertEqual(res.status_int,
                                             webob.exc.HTTPCreated.code)

                            data = {"health_monitor": {
                                    "id": monitor2['health_monitor']['id'],
                                    'tenant_id': self._tenant_id}}
                            req = self.new_create_request(
                                "pools",
                                data,
                                fmt=self.fmt,
                                id=pool['pool']['id'],
                                subresource="health_monitors")
                            res = req.get_response(self.ext_api)
                            self.assertEqual(res.status_int,
                                             webob.exc.HTTPCreated.code)

                            # remove one of healthmonitor from the pool
                            req = self.new_delete_request(
                                "pools",
                                fmt=self.fmt,
                                id=pool['pool']['id'],
                                sub_id=monitor1['health_monitor']['id'],
                                subresource="health_monitors")
                            res = req.get_response(self.ext_api)
                            self.assertEqual(res.status_int,
                                             webob.exc.HTTPNoContent.code)

                            req = self.new_show_request(
                                'pools',
                                pool['pool']['id'],
                                fmt=self.fmt)
                            res = self.deserialize(
                                self.fmt,
                                req.get_response(self.ext_api)
                            )
                            self.assertNotIn(monitor1['health_monitor']['id'],
                                             res['pool']['health_monitors'])
                            self.assertIn(monitor2['health_monitor']['id'],
                                          res['pool']['health_monitors'])
                            expected = [
                                {'monitor_id': monitor2['health_monitor']['id'],
                                 'status': 'PENDING_CREATE',
                                 'status_description': None}
                            ]
                            self.assertEqual(expected,
                                             res['pool']['health_monitors_status'])

    def test_create_loadbalancer(self):
        vip_name = "vip3"
        pool_name = "pool3"

        with self.subnet(cidr="10.0.7.0/24") as subnet:

            lb_plugin = (manager.NeutronManager.
                     get_instance().
                     get_service_plugins()[constants.LOADBALANCER])
            with mock.patch.object(
                lb_plugin, '_get_tenant_vpc') as gt:
                #some exception that can show up in port creation
                gt.return_value = "dev"

                with mock.patch.object(
                    lb_plugin, 'pick_subnet_id') as ps:
                    #some exception that can show up in port creation
                    ps.return_value = subnet['subnet']['id']

                    with mock.patch.object(
                        lb_plugin, '_get_cos_by_tenant_id') as gc:
                        #some exception that can show up in port creation
                        gc.return_value = "dev"

                        with self.pool(name=pool_name) as pool:
                            with self.vip(name=vip_name, pool=pool) as vip:
                                pool_id = pool['pool']['id']
                                vip_id = vip['vip']['id']
                                # Add two members
                                res1 = self._create_member(self.fmt,
                                                           '192.168.1.100',
                                                           '80',
                                                           True,
                                                           pool_id=pool_id,
                                                           weight=1)
                                res2 = self._create_member(self.fmt,
                                                           '192.168.1.101',
                                                           '80',
                                                           True,
                                                           pool_id=pool_id,
                                                           weight=2)
                                # Add a health_monitor
                                req = self._create_health_monitor(self.fmt,
                                                                  'HTTP',
                                                                  '10',
                                                                  '10',
                                                                  '3',
                                                                  True)
                                health_monitor = self.deserialize(self.fmt, req)
                                self.assertEqual(req.status_int, webob.exc.HTTPCreated.code)

                                # Associate the health_monitor to the pool
                                data = {"health_monitor": {
                                        "id": health_monitor['health_monitor']['id'],
                                        'tenant_id': self._tenant_id}}
                                req = self.new_create_request("pools",
                                                              data,
                                                              fmt=self.fmt,
                                                              id=pool['pool']['id'],
                                                              subresource="health_monitors")
                                res = req.get_response(self.ext_api)
                                self.assertEqual(res.status_int, webob.exc.HTTPCreated.code)

                                # Get pool and vip
                                req = self.new_show_request('pools',
                                                            pool_id,
                                                            fmt=self.fmt)
                                pool_updated = self.deserialize(
                                    self.fmt,
                                    req.get_response(self.ext_api)
                                )
                                member1 = self.deserialize(self.fmt, res1)
                                member2 = self.deserialize(self.fmt, res2)
                                self.assertIn(member1['member']['id'],
                                              pool_updated['pool']['members'])
                                self.assertIn(member2['member']['id'],
                                              pool_updated['pool']['members'])
                                self.assertIn(health_monitor['health_monitor']['id'],
                                              pool_updated['pool']['health_monitors'])
                                expected = [
                                    {'monitor_id': health_monitor['health_monitor']['id'],
                                     'status': 'PENDING_CREATE',
                                     'status_description': None}
                                ]
                                self.assertEqual(
                                    expected, pool_updated['pool']['health_monitors_status'])

                                req = self.new_show_request('vips',
                                                            vip_id,
                                                            fmt=self.fmt)
                                vip_updated = self.deserialize(
                                    self.fmt,
                                    req.get_response(self.ext_api)
                                )
                                self.assertEqual(vip_updated['vip']['pool_id'],
                                                 pool_updated['pool']['id'])

                                # clean up
                                # disassociate the health_monitor from the pool first
                                req = self.new_delete_request(
                                    "pools",
                                    fmt=self.fmt,
                                    id=pool['pool']['id'],
                                    subresource="health_monitors",
                                    sub_id=health_monitor['health_monitor']['id'])
                                res = req.get_response(self.ext_api)
                                self.assertEqual(res.status_int, webob.exc.HTTPNoContent.code)
                                self._delete('health_monitors',
                                             health_monitor['health_monitor']['id'])
                                self._delete('members', member1['member']['id'])
                                self._delete('members', member2['member']['id'])

    def test_create_pool_health_monitor(self):
        lb_plugin = (manager.NeutronManager.
                             get_instance().
                             get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            #some exception that can show up in port creation
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                #some exception that can show up in port creation
                ps.return_value = self._subnet_id

                with contextlib.nested(
                    self.health_monitor(),
                    self.health_monitor(),
                    self.pool(name="pool")
                ) as (health_mon1, health_mon2, pool):
                        res = self.plugin.create_pool_health_monitor(
                            context.get_admin_context(),
                            health_mon1, pool['pool']['id']
                        )
                        self.assertEqual({'health_monitor':
                                          [health_mon1['health_monitor']['id']]},
                                         res)

                        res = self.plugin.create_pool_health_monitor(
                            context.get_admin_context(),
                            health_mon2, pool['pool']['id']
                        )
                        self.assertEqual({'health_monitor':
                                          [health_mon1['health_monitor']['id'],
                                           health_mon2['health_monitor']['id']]},
                                         res)

                        res = self.plugin.get_pool_health_monitor(
                            context.get_admin_context(),
                            health_mon2['health_monitor']['id'], pool['pool']['id'])
                        self.assertEqual(res['tenant_id'],
                                         health_mon1['health_monitor']['tenant_id'])

    def test_driver_call_create_pool_health_monitor(self):
        lb_plugin = (manager.NeutronManager.
                     get_instance().
                     get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            #some exception that can show up in port creation
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                #some exception that can show up in port creation
                ps.return_value = self._subnet_id

                with mock.patch.object(self.plugin.drivers['lbaas'],
                                       'create_pool_health_monitor') as driver_call:
                    with contextlib.nested(
                        self.health_monitor(),
                        self.pool()
                    ) as (hm, pool):
                        data = {'health_monitor': {
                                'id': hm['health_monitor']['id'],
                                'tenant_id': self._tenant_id}}
                        self.plugin.create_pool_health_monitor(
                            context.get_admin_context(),
                            data, pool['pool']['id']
                        )
                        hm['health_monitor']['pools'] = [
                            {'pool_id': pool['pool']['id'],
                             'status': 'PENDING_CREATE',
                             'status_description': None}]
                        driver_call.assert_called_once_with(
                            mock.ANY, hm['health_monitor'], pool['pool']['id'])

    def test_pool_monitor_list_of_pools(self):
        lb_plugin = (manager.NeutronManager.
                     get_instance().
                     get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            #some exception that can show up in port creation
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                #some exception that can show up in port creation
                ps.return_value = self._subnet_id

                with contextlib.nested(
                    self.health_monitor(),
                    self.pool(name="poolmon1"),
                    self.pool(name="poolmon2")
                ) as (hm, p1, p2):
                    ctx = context.get_admin_context()
                    data = {'health_monitor': {
                            'id': hm['health_monitor']['id'],
                            'tenant_id': self._tenant_id}}
                    self.plugin.create_pool_health_monitor(
                        ctx, data, p1['pool']['id'])
                    self.plugin.create_pool_health_monitor(
                        ctx, data, p2['pool']['id'])
                    healthmon = self.plugin.get_health_monitor(
                        ctx, hm['health_monitor']['id'])
                    pool_data = [{'pool_id': p1['pool']['id'],
                                  'status': 'PENDING_CREATE',
                                  'status_description': None},
                                 {'pool_id': p2['pool']['id'],
                                  'status': 'PENDING_CREATE',
                                  'status_description': None}]
                    self.assertEqual(sorted(healthmon['pools']),
                                     sorted(pool_data))
                    req = self.new_show_request(
                        'health_monitors',
                        hm['health_monitor']['id'],
                        fmt=self.fmt)
                    hm = self.deserialize(
                        self.fmt,
                        req.get_response(self.ext_api)
                    )
                    self.assertEqual(sorted(hm['health_monitor']['pools']),
                                     sorted(pool_data))

    def test_create_pool_health_monitor_already_associated(self):
        lb_plugin = (manager.NeutronManager.
                     get_instance().
                     get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            #some exception that can show up in port creation
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                #some exception that can show up in port creation
                ps.return_value = self._subnet_id
                with contextlib.nested(
                    self.health_monitor(),
                    self.pool(name="pool")
                ) as (hm, pool):
                    res = self.plugin.create_pool_health_monitor(
                        context.get_admin_context(),
                        hm, pool['pool']['id']
                    )
                    self.assertEqual({'health_monitor':
                                      [hm['health_monitor']['id']]},
                                     res)
                    self.assertRaises(loadbalancer.PoolMonitorAssociationExists,
                                      self.plugin.create_pool_health_monitor,
                                      context.get_admin_context(),
                                      hm,
                                      pool['pool']['id'])

    def test_create_pool_healthmon_invalid_pool_id(self):
        with self.health_monitor() as healthmon:
            self.assertRaises(loadbalancer.PoolNotFound,
                              self.plugin.create_pool_health_monitor,
                              context.get_admin_context(),
                              healthmon,
                              "123-456-789"
                              )

    def test_update_status(self):
        lb_plugin = (manager.NeutronManager.
                 get_instance().
                 get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            #some exception that can show up in port creation
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                #some exception that can show up in port creation
                ps.return_value = _subnet_id

                with mock.patch.object(
                    lb_plugin, '_get_cos_by_tenant_id') as gc:
                    #some exception that can show up in port creation
                    gc.return_value = "dev"
                    with self.pool() as pool:
                        self.assertEqual(pool['pool']['status'], 'PENDING_CREATE')
                        self.assertFalse(pool['pool']['status_description'])

                        self.plugin.update_status(context.get_admin_context(), ldb.Pool,
                                                  pool['pool']['id'], 'ERROR', 'unknown')
                        updated_pool = self.plugin.get_pool(context.get_admin_context(),
                                                            pool['pool']['id'])
                        self.assertEqual(updated_pool['status'], 'ERROR')
                        self.assertEqual(updated_pool['status_description'], 'unknown')

                        # update status to ACTIVE, status_description should be cleared
                        self.plugin.update_status(context.get_admin_context(), ldb.Pool,
                                                  pool['pool']['id'], 'ACTIVE')
                        updated_pool = self.plugin.get_pool(context.get_admin_context(),
                                                            pool['pool']['id'])
                        self.assertEqual(updated_pool['status'], 'ACTIVE')
                        self.assertFalse(updated_pool['status_description'])

    def test_update_pool_health_monitor(self):
        lb_plugin = (manager.NeutronManager.
                     get_instance().
                     get_service_plugins()[constants.LOADBALANCER])
        with mock.patch.object(
            lb_plugin, '_get_tenant_vpc') as gt:
            #some exception that can show up in port creation
            gt.return_value = "dev"

            with mock.patch.object(
                lb_plugin, 'pick_subnet_id') as ps:
                #some exception that can show up in port creation
                ps.return_value = self._subnet_id
                with contextlib.nested(
                    self.health_monitor(),
                    self.pool(name="pool")
                ) as (hm, pool):
                    res = self.plugin.create_pool_health_monitor(
                        context.get_admin_context(),
                        hm, pool['pool']['id'])
                    self.assertEqual({'health_monitor':
                                      [hm['health_monitor']['id']]},
                                     res)

                    assoc = self.plugin.get_pool_health_monitor(
                        context.get_admin_context(),
                        hm['health_monitor']['id'],
                        pool['pool']['id'])
                    self.assertEqual(assoc['status'], 'PENDING_CREATE')
                    self.assertIsNone(assoc['status_description'])

                    self.plugin.update_pool_health_monitor(
                        context.get_admin_context(),
                        hm['health_monitor']['id'],
                        pool['pool']['id'],
                        'ACTIVE', 'ok')
                    assoc = self.plugin.get_pool_health_monitor(
                        context.get_admin_context(),
                        hm['health_monitor']['id'],
                        pool['pool']['id'])
                    self.assertEqual(assoc['status'], 'ACTIVE')
                    self.assertEqual(assoc['status_description'], 'ok')



class TestLoadBalancerXML(TestLoadBalancer):
    fmt = 'xml'


class ForceDeleteNoopLbaaSDriver(NoopLbaaSDriver):
    """
        Overriding the no op driver to not delete pool entity from the db.
    """
    def delete_pool(self, context, pool):
        pass


class TestLoadBalancerForceDelete(LoadBalancerPluginDbTestCase):

    def setUp(self, core_plugin=None, lb_plugin=None, lbaas_provider=None,
              ext_mgr=None):
        lbaas_provider = (constants.LOADBALANCER + ':lbaas_force_delete:'
                          + FORCEDELETE_NOOP_DRIVER_KLASS + ':default')
        cfg.CONF.set_override('service_provider',
                              [lbaas_provider],
                              'service_providers')
        super(TestLoadBalancerForceDelete, self).setUp(core_plugin=core_plugin, lb_plugin=lb_plugin,
                                                       lbaas_provider=lbaas_provider,ext_mgr=ext_mgr)

    def test_force_delete_flag_on_pool(self):

        with self.subnet(cidr="10.0.5.0/24") as subnet:
            ctx = context.get_admin_context()
            ctx.force_delete = True
            lb_plugin = (manager.NeutronManager.
                     get_instance().
                     get_service_plugins()[constants.LOADBALANCER])
            with mock.patch.object(
                lb_plugin, '_get_tenant_vpc') as gt:
                gt.return_value = "dev"

                with mock.patch.object(
                    lb_plugin, 'pick_subnet_id') as ps:
                    ps.return_value = subnet['subnet']['id']

                    with mock.patch.object(lb_plugin, '_get_cos_by_tenant_id') as gc:
                        gc.return_value = "dev"
                        pool = {'name': 'pool1',
                                'subnet_id': subnet['subnet']['id'],
                                'lb_method': 'ROUND_ROBIN',
                                'protocol': 'HTTP',
                                'admin_state_up': True,
                                'tenant_id': self._tenant_id,
                                'provider': 'lbaas_force_delete',
                                'label' : '',
                                'description': ''}
                        new_pool = lb_plugin.create_pool(ctx, {'pool': pool})
                        self.assertEquals(new_pool['status'], constants.PENDING_CREATE)

                        with mock.patch.object(lb_plugin, '_get_driver_for_provider') as provider:
                            provider.return_value = lb_plugin.drivers['lbaas_force_delete']

                            lb_plugin.delete_pool(ctx, new_pool['id'])
                            deleted_pool = lb_plugin.get_pool(ctx, new_pool['id'])
                            self.assertEquals(deleted_pool['status'], constants.PENDING_DELETE)

                            with mock.patch.object(lb_plugin, '_ensure_pool_delete_conditions') as ensure:
                                lb_plugin.delete_pool(ctx, new_pool['id'])
                                assert ensure.called

    def test_force_delete_flag_off_pool(self):

        with self.subnet(cidr="10.0.5.0/24") as subnet:
            ctx = context.get_admin_context()
            ctx.force_delete = False
            lb_plugin = (manager.NeutronManager.
                     get_instance().
                     get_service_plugins()[constants.LOADBALANCER])
            with mock.patch.object(
                lb_plugin, '_get_tenant_vpc') as gt:
                gt.return_value = "dev"

                with mock.patch.object(
                    lb_plugin, 'pick_subnet_id') as ps:
                    ps.return_value = subnet['subnet']['id']

                    with mock.patch.object(lb_plugin, '_get_cos_by_tenant_id') as gc:
                        gc.return_value = "dev"
                        pool = {'name': 'pool1',
                                'subnet_id': subnet['subnet']['id'],
                                'lb_method': 'ROUND_ROBIN',
                                'protocol': 'HTTP',
                                'admin_state_up': True,
                                'tenant_id': self._tenant_id,
                                'provider': 'lbaas_force_delete',
                                'label':'',
                                'description': ''}
                        new_pool = lb_plugin.create_pool(ctx, {'pool': pool})
                        self.assertEquals(new_pool['status'], constants.PENDING_CREATE)

                        with mock.patch.object(lb_plugin, '_get_driver_for_provider') as provider:
                            provider.return_value = lb_plugin.drivers['lbaas_force_delete']

                            lb_plugin.delete_pool(ctx, new_pool['id'])
                            deleted_pool = lb_plugin.get_pool(ctx, new_pool['id'])
                            self.assertEquals(deleted_pool['status'], constants.PENDING_DELETE)

                            with mock.patch.object(lb_plugin, '_ensure_pool_delete_conditions') as ensure:
                                lb_plugin.delete_pool(ctx, new_pool['id'])
                                assert not ensure.called
