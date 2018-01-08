#
# Copyright 2013 Radware LTD.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
from neutron.api.v2 import attributes as attrs
from neutron.common import exceptions as n_exc
from neutron import context
from neutron.db import api as qdbapi
from neutron.db.loadbalancer import lbaas_ssl_db as ssldb
from neutron.db.loadbalancer import loadbalancer_db as ldb
from neutron.db import servicetype_db as st_db
from neutron.extensions import loadbalancer
from neutron.openstack.common import excutils
from neutron.openstack.common import log as logging
from neutron.plugins.common import constants
from neutron.services.loadbalancer import agent_scheduler
from neutron.services.loadbalancer.drivers import (
    abstract_ssl_extension_driver as abs_ssl_driver)
from neutron.services import provider_configuration as pconf
from neutron.services import service_base
from neutron.extensions import loadbalancer as lbaas
from neutron.extensions import lbaas_ssl
from oslo_config import cfg
from keystoneclient.v2_0.client import Client
from neutron.openstack.common import uuidutils
from keystoneclient.middleware import auth_token
import json
import re
from random import randint
from neutron.common import log
from neutron import quota
from neutron.db import quota_db as qdb
from neutron.extensions import bulkloadbalancer

# List of subnets per VPC
# The lbaas_vpc_vip_subnets is a dictionary of this form:
# {
#   'vpc_name1': ['subnet_uuid1', 'subnet_uuid2', ...],
#   'vpc_name2': ['subnet_uuid1', 'subnet_uuid2', ...]
#   ...
# }
lbaas_opts = [
    cfg.StrOpt('lbaas_vpc_vip_subnets',
                default='',
                help='Subnets that VIPs can belong to, for a VPC.'),
    cfg.StrOpt('lbaas_lbms_vpc_vip_subnets',
                default='',
                help='Subnets that VIPs can belong to lbms provider and for a VPC.'),
    cfg.BoolOpt('lbaas_read_only',
                              default=False,
                              help='If set to True, disables LBaaS control plane'),
    cfg.BoolOpt('lbaas_notification',
                default=False,
                help='A flag to turn-on/off LBaaS notification')
]

cfg.CONF.register_opts(lbaas_opts)

lbaas_vpc_quota_opts = [
    cfg.StrOpt('vpc_quota_vip',
               default='{}',
               help='Vip quota for a VPC.')
]

cfg.CONF.register_opts(lbaas_vpc_quota_opts, 'QUOTAS')

LOG = logging.getLogger(__name__)

STANDARD_MONITOR_LIST = ['http', 'https', 'tcp', 'ping']

class LoadBalancerPlugin(ldb.LoadBalancerPluginDb,
                         agent_scheduler.LbaasAgentSchedulerDbMixin,
                         ssldb.LBaasSSLDbMixin,
                         bulkloadbalancer.BulkLoadBalancerPluginBase):

    """Implementation of the Neutron Loadbalancer Service Plugin.

    This class manages the workflow of LBaaS request/response.
    Most DB related works are implemented in class
    loadbalancer_db.LoadBalancerPluginDb.
    """
    supported_extension_aliases = ["lbaas",
                                   "lbaas_agent_scheduler",
                                   "service-type",
                                   "lbaas-ssl",
                                   "lbaas-bulk-operations"]

    # lbaas agent notifiers to handle agent update operations;
    # can be updated by plugin drivers while loading;
    # will be extracted by neutron manager when loading service plugins;
    agent_notifiers = {}
    __native_bulk_support = True

    def __init__(self):
        """Initialization for the loadbalancer service plugin."""

        self.service_type_manager = st_db.ServiceTypeManager.get_instance()
        self._load_drivers()

        self.keystone_client = None
        self.qdb_driver = qdb.DbQuotaDriver()

        try:
            self.authhost = cfg.CONF.keystone_authtoken['auth_host']
            self.keystone_admin_username = cfg.CONF.keystone_authtoken['admin_user']
            self.keystone_pwd = cfg.CONF.keystone_authtoken['admin_password']
            self.keystone_tenant_name = cfg.CONF.keystone_authtoken['admin_tenant_name']
            self.auth_uri = cfg.CONF.keystone_authtoken['auth_protocol'] + "://"+ \
                            self.authhost + ":" + str(cfg.CONF.keystone_authtoken['auth_port'])+"/v2.0"

            LOG.info('Keystone end point [%s] is used' % self.auth_uri)

            if (self.keystone_admin_username and self.keystone_pwd and self.keystone_tenant_name and self.auth_uri):
                self.keystone_client = Client(username=self.keystone_admin_username,
                                            password=self.keystone_pwd,
                                            tenant_name=self.keystone_tenant_name,
                                        auth_url=self.auth_uri)
        except Exception as e:
            LOG.info('Keystone config issue : %s' % e.__str__())

    def _load_drivers(self):
        """Loads plugin-drivers specified in configuration."""
        self.drivers, self.default_provider = service_base.load_drivers(
            constants.LOADBALANCER, self)



    def _get_driver_for_provider(self, provider):
        if provider in self.drivers:
            return self.drivers[provider]
        # raise if not associated (should never be reached)
        raise n_exc.Invalid(_("Error retrieving driver for provider %s") %
                            provider)

    def _get_driver_for_pool(self, context, pool_id):
        pool = self.get_pool(context, pool_id)
        try:
            return self.drivers[pool['provider']]
        except KeyError:
            raise n_exc.Invalid(_("Error retrieving provider for pool %s") %
                                pool_id)

    def _get_driver_for_vip_ssl(self, context, vip_id):
        vip = self.get_vip(context, vip_id)
        pool = self.get_pool(context, vip['pool_id'])
        if pool['provider']:
            try:
                driver = self.drivers[pool['provider']]
                if not issubclass(
                    driver.__class__,
                    abs_ssl_driver.LBaaSAbstractSSLDriver
                ):
                    raise n_exc.ExtensionNotSupportedByProvider(
                        extension_name='lbaas-ssl',
                        provider_name=pool['provider'])
                return driver
            except KeyError:
                raise n_exc.Invalid(_("Error retrieving provider for "
                                      "vip's %s SSL configuration"), vip_id)
        else:
            raise n_exc.Invalid(_("Error retrieving provider for vip %s"),
                                vip_id)

    def get_plugin_type(self):
        return constants.LOADBALANCER

    def get_plugin_description(self):
        return "Neutron LoadBalancer Service Plugin"

    @log.log
    def _get_tenant_vpc(self, tenant_id):
        tenant_info = None
        retry_count = 0
        if not self.keystone_client:
            raise n_exc.Invalid('Keystone not running OR configuration is not done properly!')

        while retry_count <= 3 and tenant_info is None:
            try:
                tenant_info = self.keystone_client.tenants.get(tenant_id=tenant_id)
            except Exception as ex:
                LOG.exception(_('An error in getting tenant [%s] information with message. '
                                +str(ex.message)+'.Retrying again..'), tenant_id)
                tenant_info = None
                retry_count += 1

        if not tenant_info:
            raise lbaas.ErrorInAccessingTenantInfo(tenant_id=tenant_id)

        tenant_info_dict = tenant_info.__dict__['_info']
        if 'vpc' in tenant_info_dict:
            tenant_vpc = tenant_info_dict['vpc']
        else:
            raise lbaas.TenantNotConfiguredWithVpc(tenant_id=tenant_id)
        return tenant_vpc

    @log.log
    def pick_subnet_id(self, context, entitybase, tenant_cos):

        # For vip request, if the subnet is not present in the request
        # select the subnet from the pool.
        label = None
        requested_subnet = None
        if 'pool' in entitybase:
            entityType = "pool"
            entity = entitybase['pool']
            if 'subnet_id' in entity:
                requested_subnet = entity['subnet_id']
            if 'provider' in entity :
                provider = entity['provider']
            if 'label' in entity:
                label = entity['label']


        else:
            entityType = 'vip'
            entity = entitybase['vip']
            if 'subnet_id' in entity:
                requested_subnet = entity['subnet_id']
            pool = self._get_resource(context, ldb.Pool, entity['pool_id'])
            # if no subnet passed for vip request, take the pool subnet and return
            if not requested_subnet:
                requested_subnet = pool['subnet_id']
                return requested_subnet
            else:
                if requested_subnet != pool['subnet_id'] :
                    LOG.error(_('requested subnet and pool subnet doesnt match. using pool subnet %s, '),
                    pool['subnet_id'])
                return pool['subnet_id']


            if 'provider' in pool:
                provider = pool['provider']['provider_name']
            if 'label' in pool :
                label = pool['label']

        if provider == 'lbms':
            all_labels_subnets_dict = json.loads(cfg.CONF.lbaas_lbms_vpc_vip_subnets)
            if label in all_labels_subnets_dict:
                all_cos_subnets_dict = all_labels_subnets_dict[label]
            else:
                # support only for secure (tcop) vips
                raise  lbaas.CouldNotPickSubnetForVip()

        else :
            all_cos_subnets_dict = json.loads(cfg.CONF.lbaas_vpc_vip_subnets)

        tenant_cos_lower = tenant_cos.lower()
        if tenant_cos_lower in  all_cos_subnets_dict:
            cos_subnet_list = all_cos_subnets_dict[tenant_cos_lower]
            if requested_subnet and \
                            requested_subnet not in cos_subnet_list:
                raise lbaas.NotAuthorizedToUseSubnet(entity=entityType)
        else:
            raise lbaas.COSSubnetsNotConfigured()

        if not requested_subnet:
            for subnet in all_cos_subnets_dict[tenant_cos_lower]:
                # Does subnet have free IPs?
                if self.subnet_has_free_ips(context, subnet):
                    requested_subnet = subnet
                    break

        if not requested_subnet:
            raise lbaas.CouldNotPickSubnetForVip()
        return requested_subnet

    def check_lbaas_read_only(self):
        if cfg.CONF.lbaas_read_only:
            raise lbaas.LBaaSinReadOnlyMode()

    def check_name_format(self, name, is_vip=False):
        if is_vip:
            if re.match("^[\.a-zA-Z0-9-]+$", name):
                return True
        elif re.match("^[\.a-zA-Z0-9_-]+$", name):
            return True
        else:
            return False

    def check_vpc_vip_quota(self, context, tenant_vpc, tenant_id):
        _quota = self.qdb_driver._get_quotas(context, tenant_id, quota.QUOTAS.resources,['vip'])
        # Only apply VPC level quota if tenant level quota is not configured
        if _quota['vip'] == int(cfg.CONF.QUOTAS.quota_vip) :
            vpc_vip_quota = json.loads(cfg.CONF.QUOTAS.vpc_quota_vip).get(tenant_vpc, None)
            if vpc_vip_quota:
                #get existing vip count for current tenant
                current_vip_count = self.get_vips_count(context, filters={'tenant_id':[tenant_id]})
                if (current_vip_count+1) > vpc_vip_quota :
                    raise lbaas.VPCQuotaExceeded(entity='Vip',vpc=tenant_vpc,
                                  in_use=current_vip_count, allowed_quota=vpc_vip_quota)
   
    @log.log
    def create_vip(self, context, vip):
        self.check_lbaas_read_only()
        tenant_id = vip['vip']['tenant_id']
        if vip['vip']['pool_id'] :
            vip['vip']['pool'] = self._get_resource(context, ldb.Pool, vip['vip']['pool_id'])
        tenant_vpc = vip['vip']['pool']['tenant_vpc']
        db_worker = super(LoadBalancerPlugin, self)
        if not tenant_vpc :
            tenant_vpc = self._get_tenant_vpc(tenant_id)
            vip['vip']['pool']['tenant_vpc'] = tenant_vpc
            db_worker.update_pool(context,vip['vip']['pool']['id'], vip['vip'])


        #vip quota check
        self.check_vpc_vip_quota(context, tenant_vpc, tenant_id)
        subnet_id = self.pick_subnet_id(context, vip, tenant_vpc)     
        vip['vip']['subnet_id'] = subnet_id
        vip_name = vip['vip']['name']
        if not vip_name:
            raise lbaas.LBNameEmpty(entity='Vip')


        # Check if the name has any special chars.
        name_format_ok = self.check_name_format(vip_name, is_vip=True)
        if not name_format_ok:
            raise lbaas.NameHasSpecialChars(name=vip_name)
        # Next, check if the name is unique.
        name_present = db_worker.is_name_present(context, vip_name, ldb.Vip)
        if name_present:
            raise lbaas.LBNameNotUnique(entity="Vip")
        v = db_worker.create_vip(context, vip)
        driver = self._get_driver_for_pool(context, v['pool_id'])
        driver.create_vip(context, v)
        return v

    @log.log
    def update_vip(self, context, id, vip):
        self.check_lbaas_read_only()
        if 'status' not in vip['vip']:
            vip['vip']['status'] = constants.PENDING_UPDATE
        old_vip = self.get_vip(context, id)
        v = super(LoadBalancerPlugin, self).update_vip(context, id, vip)
        driver = self._get_driver_for_pool(context, v['pool_id'])
        driver.update_vip(context, old_vip, v)
        return v

    def _delete_db_vip(self, context, id):
        self.check_lbaas_read_only()
        # proxy the call until plugin inherits from DBPlugin
        super(LoadBalancerPlugin, self).delete_vip(context, id)

     ## Validate if the resource is already in PENDING_DELETE
    def _validate_resource_delete(self, context, model, id):
        resource = self._get_resource(context, model, id)
        if resource and resource.status == constants.PENDING_DELETE:
            LOG.info(_('Resource [%s] with id [%s] is already in PENDING_DELETE state.'), model, id)
            if context.elevated() and context.force_delete:
                LOG.info(_('Found a force delete flag with an elevated context. '
                           'Allowing deletes of resources in PENDING_DELETE'))
                return True
            LOG.info(_('Skipping deletion of resources in PENDING_DELETE'))
            return False
        return True

    @log.log
    def delete_vip(self, context, id):
        self.check_lbaas_read_only()
        if self._validate_resource_delete(context, ldb.Vip, id):
            # First check if this vip has any ssl profiles
            # associated with it. If so, disallow its deletion.
            vip_ssl_assocs = self.find_vip_ssl_cert_assocs_by_vip_id(context, id)
            if vip_ssl_assocs and len(vip_ssl_assocs) > 0:
                # Delete these associations.
                #for vip_ssl_assoc in vip_ssl_assocs:
                #    self.delete_vip_ssl_certificate_association(context, vip_ssl_assoc['id'])
                raise lbaas_ssl.VipSSLCertificateAssociationExists()
            self.update_status(context, ldb.Vip,
                               id, constants.PENDING_DELETE)
            v = self.get_vip(context, id)
            driver = self._get_driver_for_pool(context, v['pool_id'])
            driver.delete_vip(context, v)

    @log.log
    def create_ssl_certificate(self, context, ssl_certificate):
        self.check_lbaas_read_only()
        ssl_cert = ssl_certificate['ssl_certificate']
        cert_name = ssl_cert['name']
        if not cert_name:
            raise lbaas_ssl.SSLNameEmpty(entity='Certificate')
        # Check if the name has any special chars.
        name_format_ok = self.check_name_format(cert_name)
        if not name_format_ok:
            raise lbaas.NameHasSpecialChars(name=cert_name)
        db_worker = super(LoadBalancerPlugin, self)
        name_present = db_worker.is_name_present(context, cert_name, ssldb.SSLCertificate)
        if name_present:
            raise lbaas_ssl.SSLNameNotUnique(entity='Certificate')

        new_cert = super(
            LoadBalancerPlugin,
            self).create_ssl_certificate(
            context,
            ssl_cert)
        return new_cert


    @log.log
    def create_ssl_certificate_chain(self, context, ssl_certificate_chain):
        self.check_lbaas_read_only()
        ssl_cert_chain = ssl_certificate_chain['ssl_certificate_chain']
        cert_chain_name = ssl_cert_chain['name']
        if not cert_chain_name:
            raise lbaas_ssl.SSLNameEmpty(entity='Cert Chain')
        # Check if the name has any special chars.
        name_format_ok = self.check_name_format(cert_chain_name)
        if not name_format_ok:
            raise lbaas.NameHasSpecialChars(name=cert_chain_name)
        db_worker = super(LoadBalancerPlugin, self)
        name_present = db_worker.is_name_present(context, cert_chain_name,
                                                 ssldb.SSLCertificateChain)
        if name_present:
            raise lbaas_ssl.SSLNameNotUnique(entity='Cert Chain')

        new_cert_chain = super(
            LoadBalancerPlugin,
            self).create_ssl_certificate_chain(
            context, ssl_cert_chain)
        return new_cert_chain

    @log.log
    def create_ssl_certificate_key(self, context, ssl_certificate_key):
        self.check_lbaas_read_only()
        ssl_cert_key = ssl_certificate_key['ssl_certificate_key']
        cert_key_name = ssl_cert_key['name']
        if not cert_key_name:
            raise lbaas_ssl.SSLNameEmpty(entity='Cert Key')
        # Check if the name has any special chars.
        name_format_ok = self.check_name_format(cert_key_name)
        if not name_format_ok:
            raise lbaas.NameHasSpecialChars(name=cert_key_name)
        db_worker = super(LoadBalancerPlugin, self)
        name_present = db_worker.is_name_present(context, cert_key_name,
                                                 ssldb.SSLCertificateKey)
        if name_present:
            raise lbaas_ssl.SSLNameNotUnique(entity='Cert Key')

        new_cert_key = super(
            LoadBalancerPlugin,
            self).create_ssl_certificate_key(
            context, ssl_cert_key)
        return new_cert_key

    def update_ssl_certificate_chain(self, context, id, ssl_certificate_chain):
        self.check_lbaas_read_only()
        # Don't support update for now.
        pass

    def update_vip_ssl_certificate_association(self, context, id, vip_ssl_certificate_association):
        self.check_lbaas_read_only()
        # Don't support update for now.
        pass

    @log.log
    def delete_ssl_certificate(self, context, id):
        self.check_lbaas_read_only()
        super(LoadBalancerPlugin, self).delete_ssl_certificate(context, id)

    @log.log
    def delete_ssl_certificate_chain(self, context, id):
        self.check_lbaas_read_only()
        super(LoadBalancerPlugin, self).delete_ssl_certificate_chain(context, id)

    @log.log
    def delete_ssl_certificate_key(self, context, id):
        self.check_lbaas_read_only()
        super(LoadBalancerPlugin, self).delete_ssl_certificate_key(context, id)

    def update_ssl_certificate_key(self, context, id, ssl_certificate_key):
        self.check_lbaas_read_only()
        # Don't support update for now.
        pass

    def get_ssl_certificate(self, context, cert_id, fields=None):
        res = super(
            LoadBalancerPlugin,
            self).get_ssl_certificate(
            context,
            cert_id,
            fields)
        return res

    def get_ssl_certificates(self, context, filters=None, fields=None):
        res = super(
            LoadBalancerPlugin,
            self).get_ssl_certificates(
            context,
            filters,
            fields)
        return res

    def update_ssl_certificate(self, context, id, ssl_certificate):
        self.check_lbaas_read_only()
        # Don't support update for now.
        pass

    @log.log
    def create_vip_ssl_certificate_association(self, context,
                                               vip_ssl_certificate_association):
        self.check_lbaas_read_only()
        assoc = vip_ssl_certificate_association['vip_ssl_certificate_association']
        vip_id = assoc['vip_id']
        ssl_profile_id = assoc['ssl_profile_id']
        tenant_id = assoc['tenant_id']
        # Check for empty fields in input.
        if not assoc['name']:
            raise lbaas_ssl.VipSSLCertificateAssociationNameEmpty()
        if not assoc['vip_id']:
            raise lbaas_ssl.VipSSLCertificateAssociationVipEmpty()
        if not assoc['ssl_profile_id']:
            raise lbaas_ssl.VipSSLCertificateAssociationProfileEmpty()

        # First check if this association already exists for this tenant.
        exists = super(LoadBalancerPlugin, self).find_vip_ssl_cert_assoc(context,
                                                                         vip_id,
                                                                         ssl_profile_id)
        if exists:
            raise lbaas_ssl.VipSSLCertificateAssociationExists()

        # Next, check if this vip is already associated with any profile at all.
        # Currently, we don't support the case where a VIP has associations with
        # multiple SSL profiles. When we intend to remove that, we can remove this
        # check. Note that when we do that, we'll need to take care of updates
        # carefully.
        vip_assoc = super(LoadBalancerPlugin, self)\
            .find_vip_ssl_cert_assocs_by_vip_id(context, vip_id)
        if vip_assoc:
            raise lbaas_ssl.VipSSLCertificateAssociationDisallowed()
        # Else go ahead and create it.
        # At this stage, assoc will not have device_ip to begin with. So set it
        # to none explicitly.
        assoc['device_ip'] = None
        assoc_db = super(
            LoadBalancerPlugin,
            self).create_vip_ssl_certificate_association(
            context,
            assoc)
        vip_db = self.get_vip(context, vip_id)
        # Get the cert, cert_chain and key IDs using the ssl profile ID.
        ssl_profile_db = self.get_ssl_profile(context, ssl_profile_id)
        cert_id = ssl_profile_db['cert_id']
        cert_chain_id = ssl_profile_db['cert_chain_id']
        key_id = ssl_profile_db['key_id']

        # If ssl profile is shared, use elevated context.
        if ssl_profile_db['shared'] == True:
            context = context.elevated()

        cert_db = self.get_ssl_certificate(context, cert_id)
        if cert_chain_id:
            cert_chain_db = self.get_ssl_certificate_chain(
                context,
                cert_chain_id)
        else:
            cert_chain_db = None
        key_db = self.get_ssl_certificate_key(context, key_id)
        driver = self._get_driver_for_vip_ssl(context, vip_id)
        driver.create_vip_ssl_certificate_association(
            context,
            assoc_db,
            ssl_profile_db,
            cert_db,
            key_db,
            vip_db,
            cert_chain_db)
        return assoc_db

    @log.log
    def delete_vip_ssl_certificate_association(
            self, context, vip_ssl_certificate_association):
        self.check_lbaas_read_only()
        assoc_id = vip_ssl_certificate_association
        # First, get the vip_id of this association.
        assoc_db = super(
            LoadBalancerPlugin,
            self).get_vip_ssl_cert_assoc_by_id(
            context,
            assoc_id)
        ssl_profile_id = assoc_db['ssl_profile_id']
        # Retrieve the ssl profile.
        ssl_profile_db = self.get_ssl_profile(context, ssl_profile_id)

        if ssl_profile_db['shared'] == True:
            context = context.elevated()

        vip_id = assoc_db['vip_id']
        cert_id = ssl_profile_db['cert_id']
        cert_chain_id = ssl_profile_db['cert_chain_id']
        key_id = ssl_profile_db['key_id']

        res = super(LoadBalancerPlugin, self).delete_vip_ssl_certificate_association(
            context, assoc_db)
        # The above call to delete marks the record as PENDING_DELETE
        vip_db = self.get_vip(context, vip_id)
        cert_db = self.get_ssl_certificate(context, cert_id)
        if cert_chain_id:
            cert_chain_db = self.get_ssl_certificate_chain(
                context,
                cert_chain_id)
        else:
            cert_chain_db = None
        key_db = self.get_ssl_certificate_key(context, key_id)
        driver = self._get_driver_for_vip_ssl(context, vip_id)
        # Check if key is used in any other association. If not,
        # mark it for deletion on the LB device.
        status_set = ['ACTIVE', 'PENDING_UPDATE', 'PENDING_CREATE']
        assoc_sets = self._get_vip_ssl_cert_assocs_by_key_id(context, key_id, status_set)
        if not assoc_sets:
            key_delete_flag = True
        else:
            key_delete_flag = False

        assoc_sets = self._get_vip_ssl_cert_assocs_by_cert_id(context, cert_id, status_set)
        if not assoc_sets:
            cert_delete_flag = True
        else:
            cert_delete_flag = False

        assoc_sets = self._get_vip_ssl_cert_assocs_by_cert_chain_id(context, cert_chain_id, status_set)
        if not assoc_sets and cert_chain_id:
            cert_chain_delete_flag = True
        else:
            cert_chain_delete_flag = False

        driver.delete_vip_ssl_certificate_association(
            context,
            assoc_db,
            ssl_profile_db,
            cert_db,
            key_db,
            vip_db,
            cert_chain_db,
            cert_delete_flag,
            cert_chain_delete_flag,
            key_delete_flag)
        return res

    def get_vip_ssl_certificate_association(
            self, context, assoc_id, fields=None):
        res = super(
            LoadBalancerPlugin,
            self).get_vip_ssl_certificate_association(
            context,
            assoc_id,
            fields)
        return res

    def get_vip_ssl_certificate_associations(
            self, context, filters=None, fields=None):
        res = super(
            LoadBalancerPlugin,
            self).get_vip_ssl_certificate_associations(
            context,
            filters,
            fields)
        return res

    def _get_provider_name(self, context, pool):
        if ('provider' in pool and
                pool['provider'] != attrs.ATTR_NOT_SPECIFIED):
            provider_name = pconf.normalize_provider_name(pool['provider'])
            self.validate_provider(provider_name)
            return provider_name
        else:
            if not self.default_provider:
                raise pconf.DefaultServiceProviderNotFound(
                    service_type=constants.LOADBALANCER)
            return self.default_provider

    def _get_agent_id(self, context, pool):
        agent_id = None
        if 'extra' in pool and pool['extra']:
            extra_params = json.loads(pool['extra'])
            if 'agent_id' in extra_params:
                agent_id = extra_params['agent_id']
        return agent_id

    @log.log
    def create_pool(self, context, pool):
        self.check_lbaas_read_only()
        p = pool['pool']
        pool_name = p['name']
        if not pool_name:
            raise lbaas.LBNameEmpty(entity='Pool')
        tenant_id = p['tenant_id']
        tenant_vpc = self._get_tenant_vpc(tenant_id)
        subnet_id = self.pick_subnet_id(context, pool, tenant_vpc)
        agent_id = self._get_agent_id(context, p)
        p['subnet_id'] = subnet_id
        p['tenant_vpc'] = tenant_vpc
        # Check if the name has any special chars.
        name_format_ok = self.check_name_format(pool_name)
        if not name_format_ok:
            raise lbaas.NameHasSpecialChars(name=pool_name)
        db_worker = super(LoadBalancerPlugin, self)
        name_present = db_worker.is_name_present(context, pool_name,
                                                 ldb.Pool)
        if name_present:
            raise lbaas.LBNameNotUnique(entity='Pool')

        provider_name = self._get_provider_name(context, pool['pool'])
        p = super(LoadBalancerPlugin, self).create_pool(context, pool)
        if agent_id:
            p['agent_id'] = agent_id

        self.service_type_manager.add_resource_association(
            context,
            constants.LOADBALANCER,
            provider_name, p['id'])
        # need to add provider name to pool dict,
        # because provider was not known to db plugin at pool creation
        p['provider'] = provider_name
        driver = self.drivers[provider_name]
        try:
            driver.create_pool(context, p)
        except loadbalancer.NoEligibleBackend:
            # that should catch cases when backend of any kind
            # is not available (agent, appliance, etc)
            self.update_status(context, ldb.Pool,
                               p['id'], constants.ERROR,
                               "No eligible backend")
            raise loadbalancer.NoEligibleBackend(pool_id=p['id'])
        return p

    @log.log
    def update_pool(self, context, id, pool):
        self.check_lbaas_read_only()
        if 'status' not in pool['pool']:
            pool['pool']['status'] = constants.PENDING_UPDATE
        old_pool = self.get_pool(context, id)
        p = super(LoadBalancerPlugin, self).update_pool(context, id, pool)
        driver = self._get_driver_for_provider(p['provider'])
        driver.update_pool(context, old_pool, p)
        return p

    def _delete_db_pool(self, context, id):
        # proxy the call until plugin inherits from DBPlugin
        # rely on uuid uniqueness:
        try:
            with context.session.begin(subtransactions=True):
                self.service_type_manager.del_resource_associations(
                    context, [id])
                super(LoadBalancerPlugin, self).delete_pool(context, id)
        except Exception:
            # that should not happen
            # if it's still a case - something goes wrong
            # log the error and mark the pool as ERROR
            LOG.error(_('Failed to delete pool %s, putting it in ERROR state'),
                      id)
            with excutils.save_and_reraise_exception():
                self.update_status(context, ldb.Pool,
                                   id, constants.ERROR)

    @log.log
    def delete_pool(self, context, id):
        self.check_lbaas_read_only()
        if self._validate_resource_delete(context, ldb.Pool, id):
            # check for delete conditions and update the status
            # within a transaction to avoid a race
            with context.session.begin(subtransactions=True):
                self.update_status(context, ldb.Pool,
                                   id, constants.PENDING_DELETE)
                self._ensure_pool_delete_conditions(context, id)
            p = self.get_pool(context, id)
            driver = self._get_driver_for_provider(p['provider'])
            driver.delete_pool(context, p)

    @log.log
    def create_member(self, context, member):
        self.check_lbaas_read_only()
        # Check if this member IP:port already exists
        # in the specified pool.
        mem = member['member']
        mem_ip = mem['address']
        mem_port = mem['protocol_port']
        pool_id = mem['pool_id']
        mem_ip_exists = self.find_pool_member_by_ip(context.elevated(), pool_id, mem_ip, mem_port)
        if mem_ip_exists:
            raise lbaas.MemberAlreadyExistsInPool(member=mem_ip, port=mem_port, pool=pool_id)
        m = super(LoadBalancerPlugin, self).create_member(context, member)
        driver = self._get_driver_for_pool(context, m['pool_id'])
        driver.create_member(context, m)
        return m

    def _validate_bulk_members_payload(self, context, members):
        pool_ids = set()
        for m in members:
            if 'pool_id' in m:
                pool_ids.add(m['pool_id'])
            else:
                pool_ids.add(m['member']['pool_id'])
        if len(pool_ids) > 1:
            raise lbaas.MembersFromDifferentPoolsNotSupported()
        return pool_ids.pop()

    @log.log
    def create_member_bulk(self, context, member):
        m = member.get('members')
        pool_id = self._validate_bulk_members_payload(context, m)
        members = self.create_members_bulk_native(context, m)
        driver = self._get_driver_for_pool(context, pool_id)
        driver.create_members(context, members)
        return members

    @log.log
    def delete_member_bulk(self, context, members):
        m = members.get('members')
        member_list = self.get_members(context, filters={'id' : m})
        pool_id = self._validate_bulk_members_payload(context, member_list)
        member_list = self.delete_members_bulk_native(context, member_list)
        driver = self._get_driver_for_pool(context, pool_id)
        driver.delete_members(context, member_list)
        return member_list

    @log.log
    def update_member_bulk(self, context, member):
        m = member.get('members')
        pool_id = self._validate_bulk_members_payload(context, m)
        old_member_list = self.get_members(context,
                                           filters={'id': [each_member['member']['id'] for each_member in m]})
        self._validate_bulk_members_payload(context, old_member_list)
        member_list = self.update_members_bulk_native(context, m)
        driver = self._get_driver_for_pool(context, pool_id)
        driver.update_members(context, old_member_list, member_list)
        return member_list

    @log.log
    def update_member(self, context, id, member):
        self.check_lbaas_read_only()
        if 'status' not in member['member']:
            member['member']['status'] = constants.PENDING_UPDATE
        old_member = self.get_member(context, id)
        m = super(LoadBalancerPlugin, self).update_member(context, id, member)
        driver = self._get_driver_for_pool(context, m['pool_id'])
        driver.update_member(context, old_member, m)
        return m


    def _delete_db_member(self, context, id):
        # proxy the call until plugin inherits from DBPlugin
        super(LoadBalancerPlugin, self).delete_member(context, id)

    @log.log
    def delete_member(self, context, id):
        self.check_lbaas_read_only()
        if self._validate_resource_delete(context, ldb.Member, id):
            if self._validate_delete_member(context, id):
                self.update_status(context, ldb.Member,
                                   id, constants.PENDING_DELETE)
                m = self.get_member(context, id)
                driver = self._get_driver_for_pool(context, m['pool_id'])
                driver.delete_member(context, m)

    def _validate_delete_member(self, context, id):
        member_resource = self._get_resource(context, ldb.Member, id)
        pool_resource = self._get_resource(context, ldb.Pool, member_resource.pool_id)
        if (pool_resource.provider.provider_name == "lbms") and (len(pool_resource.members) == 1):
            if (pool_resource.vip != None) and (pool_resource.vip.admin_state_up == True):
                LOG.info(_('Member with id [%s] is the last member of the pool [%s] and its vip is active'),
                         member_resource.id, pool_resource.id)
                raise lbaas.CouldNotDeleteTheLastMemberofPoolWhenVIPAdminStateUP()

        return True


    def _validate_hm_parameters(self, delay, timeout):
        if delay < timeout:
            raise loadbalancer.DelayOrTimeoutInvalid()

    @log.log
    def create_health_monitor(self, context, health_monitor):
        self.check_lbaas_read_only()

        new_hm = health_monitor['health_monitor']
        self._validate_hm_parameters(new_hm['delay'], new_hm['timeout'])

        uuid = uuidutils.generate_uuid()
        if not new_hm['name']:
            new_hm['name'] = "uuid_" + uuid
        # Check if the name has any special chars.
        name_format_ok = self.check_name_format(new_hm['name'])
        if not name_format_ok:
            raise lbaas.NameHasSpecialChars(name=new_hm['name'])
        db_worker = super(LoadBalancerPlugin, self)
        name_present = db_worker.is_name_present(context, new_hm['name'],
                                                 ldb.HealthMonitor)
        if name_present:
            raise lbaas.LBNameNotUnique(entity='Health Monitor')

        hm = super(LoadBalancerPlugin, self).create_health_monitor(
            context,
            health_monitor
        )
        return hm

    @log.log
    def update_health_monitor(self, context, id, health_monitor):
        self.check_lbaas_read_only()
        new_hm = health_monitor['health_monitor']
        old_hm = self.get_health_monitor(context, id)
        delay = new_hm.get('delay', old_hm.get('delay'))
        timeout = new_hm.get('timeout', old_hm.get('timeout'))
        self._validate_hm_parameters(delay, timeout)

        hm = super(LoadBalancerPlugin, self).update_health_monitor(
            context,
            id,
            health_monitor
        )

        with context.session.begin(subtransactions=True):
            qry = context.session.query(
                ldb.PoolMonitorAssociation
            ).filter_by(monitor_id=hm['id']).join(ldb.Pool)
            for assoc in qry:
                driver = self._get_driver_for_pool(context, assoc['pool_id'])
                driver.update_pool_health_monitor(context, old_hm,
                                                  hm, assoc['pool_id'])
        return hm

    def _delete_db_pool_health_monitor(self, context, hm_id, pool_id):
        super(LoadBalancerPlugin, self).delete_pool_health_monitor(context,
                                                                   hm_id,
                                                                   pool_id)

    def _delete_db_health_monitor(self, context, id):
        super(LoadBalancerPlugin, self).delete_health_monitor(context, id)

    @log.log
    def delete_health_monitor(self, context, id):
        with context.session.begin(subtransactions=True):
            hm = self.get_health_monitor(context, id)
            # If the name of the supplied health monitor is a standard name,
            # don't delete it.
            if hm['name'].lower() in STANDARD_MONITOR_LIST:
                raise lbaas.CannotDeleteStandardHealthMonitor(hm_name=hm['name'])

            """
            This query removes the pool-health monitor associations for any delete health monitor call.
            It invalidates the principal mentioned in the next call that health monitors that are
            asociated with the pool should not be deleted.
            """


            """qry = context.session.query(
                ldb.PoolMonitorAssociation
            ).filter_by(monitor_id=id).join(ldb.Pool)
            for assoc in qry:
                driver = self._get_driver_for_pool(context, assoc['pool_id'])
                driver.delete_pool_health_monitor(context,
                                                  hm,
                                                  assoc['pool_id'])"""
        super(LoadBalancerPlugin, self).delete_health_monitor(context, id)

    @log.log
    def create_pool_health_monitor(self, context, health_monitor, pool_id):
        self.check_lbaas_read_only()
        retval = super(LoadBalancerPlugin, self).create_pool_health_monitor(
            context,
            health_monitor,
            pool_id
        )
        monitor_id = health_monitor['health_monitor']['id']
        hm = self.get_health_monitor(context, monitor_id)
        driver = self._get_driver_for_pool(context, pool_id)
        driver.create_pool_health_monitor(context, hm, pool_id)
        return retval

    @log.log
    def delete_pool_health_monitor(self, context, id, pool_id):
        self.check_lbaas_read_only()
        self.update_pool_health_monitor(context, id, pool_id,
                                        constants.PENDING_DELETE)
        hm = self.get_health_monitor(context, id)
        driver = self._get_driver_for_pool(context, pool_id)
        driver.delete_pool_health_monitor(context, hm, pool_id)

    def stats(self, context, pool_id):
        driver = self._get_driver_for_pool(context, pool_id)
        stats_data = driver.stats(context, pool_id)
        # if we get something from the driver -
        # update the db and return the value from db
        # else - return what we have in db
        if stats_data:
            super(LoadBalancerPlugin, self).update_pool_stats(
                context,
                pool_id,
                stats_data
            )
        return super(LoadBalancerPlugin, self).stats(context,
                                                     pool_id)

    def populate_vip_graph(self, context, vip):
        """Populate the vip with: pool, members, healthmonitors."""

        pool = self.get_pool(context, vip['pool_id'])
        vip['pool'] = pool
        vip['members'] = [self.get_member(context, member_id)
                          for member_id in pool['members']]
        vip['health_monitors'] = [self.get_health_monitor(context, hm_id)
                                  for hm_id in pool['health_monitors']]
        return vip

    def validate_provider(self, provider):
        if provider not in self.drivers:
            raise pconf.ServiceProviderNotFound(
                provider=provider, service_type=constants.LOADBALANCER)

    def get_health_monitors(self, context, filters=None, fields=None):
        res = super(LoadBalancerPlugin,
                    self).get_health_monitors(context,filters,fields)
        return res

    def get_health_monitor(self, context, id, fields=None):
        res = super(
            LoadBalancerPlugin,
            self).get_health_monitor(
            context,
            id,
            fields)
        return res

    @log.log
    def create_ssl_profile(self, context, ssl_profile):
        self.check_lbaas_read_only()
        s_profile = ssl_profile['ssl_profile']
        cert_id = s_profile['cert_id']
        key_id = s_profile['key_id']
        cert_chain_id = s_profile['cert_chain_id']
        tenant_id = s_profile['tenant_id']

        if s_profile['name'] == '':
            s_profile['name'] = None
        if s_profile['description'] == '':
            s_profile['description'] = None
        if s_profile['cert_id'] == '':
            s_profile['cert_id'] = None
        if s_profile['cert_chain_id'] == '':
            s_profile['cert_chain_id'] = None
        if s_profile['key_id'] == '':
            s_profile['key_id'] = None
        if s_profile['shared'] == '':
            s_profile['shared'] = False

        # Now, some fields cannot be None. Raise
        # appropriate exceptions in such cases.
        if not s_profile['name']:
            raise lbaas_ssl.SSLProfileNameEmpty()
        if not s_profile['cert_id']:
            raise lbaas_ssl.SSLProfileCertIDEmpty()
        if not s_profile['key_id']:
            raise lbaas_ssl.SSLProfileCertKeyIDEmpty()

        ssl_profile_name = s_profile['name']
        if not ssl_profile_name:
            raise lbaas_ssl.SSLNameEmpty(entity='Profile')

        db_worker = super(LoadBalancerPlugin, self)

        # Check if any of the supplied IDs are not valid ones.
        cert_exists = db_worker.get_ssl_certificate(context, cert_id)
        if not cert_exists:
            raise lbaas_ssl.SSLCertificateNotFound(certificate_id=cert_id)
        if cert_chain_id:
            cert_chain_exists = db_worker.get_ssl_certificate_chain(context, cert_chain_id)
            if not cert_chain_exists:
                raise lbaas_ssl.SSLCertificateChainNotFound(ssl_cert_id=cert_chain_id)
        cert_key_exists = db_worker.get_ssl_certificate_key(context, key_id)
        if not cert_key_exists:
            raise lbaas_ssl.SSLCertificateKeyNotFound(ssl_key_id=key_id)

        # Check if the name has any special chars.
        name_format_ok = self.check_name_format(ssl_profile_name)
        if not name_format_ok:
            raise lbaas.NameHasSpecialChars(name=ssl_profile_name)
        db_worker = super(LoadBalancerPlugin, self)
        name_present = db_worker.is_name_present(context, ssl_profile_name,
                                                 ssldb.SSLProfile)
        if name_present:
            raise lbaas_ssl.SSLNameNotUnique(entity='Profile')

        # First check if this cert+id+key_id+chain_id combination already
        # exists for this tenant.
        exists = super(LoadBalancerPlugin,
                       self).find_ssl_profile_combination(context, cert_id,
                                                          key_id, cert_chain_id)
        if exists:
            raise lbaas_ssl.SSLProfileCombinationExists()
        # Else, go ahead and create this SSL profile.
        ssl_profile_db = super(
            LoadBalancerPlugin,
            self).create_ssl_profile(
            context,
            s_profile)
        return ssl_profile_db

    @log.log
    def update_ssl_profile(self, context, id, ssl_profile):
        self.check_lbaas_read_only()
        # Not supported. A user will need to delete and recreate an SSL profile.
        pass


    @log.log
    def delete_ssl_profile(self, context, id):
        self.check_lbaas_read_only()
        # Check if any association is using this ssl profile. If no, delete it.
        # If yes, raise exception.
        ssl_profile_in_use = super(LoadBalancerPlugin, self).is_ssl_profile_in_use(context, id)
        if ssl_profile_in_use:
            raise lbaas_ssl.SSLProfileinUse(ssl_profile_id=id)
        # Else, delete it.
        # We just need to delete this from the db and not the lB device because
        # it'll get deleted during disassociation in case it isn't used by any other VIP.
        super(LoadBalancerPlugin, self).delete_ssl_profile(context, id)
        return


    def get_ssl_profile(self, context, id, fields=None):
        res = super(
            LoadBalancerPlugin,
            self).get_ssl_profile(
            context,
            id,
            fields)
        return res

    def get_ssl_profiles(self, context, filters=None, fields=None):
        res = super(
            LoadBalancerPlugin,
            self).get_ssl_profiles(
            context,
            filters,
            fields)
        return res
