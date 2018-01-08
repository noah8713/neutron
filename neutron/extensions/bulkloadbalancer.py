author__ = 'kugandhi'
import abc
import six
import copy

from neutron.api import extensions
from neutron.api.v2 import base
from neutron.api.v2 import resource as resource_creator
from neutron.plugins.common import constants as plugin_const
from neutron import manager
from neutron import policy
from neutron.services import service_base
from neutron import wsgi
from neutron.api.v2 import attributes as attr
from neutron.common import exceptions
import webob.exc
from neutron.api.v2 import resource_helper
from neutron.extensions import loadbalancer

RESOURCE_NAME = 'bulk_members'
RESOURCE_COLLECTION = 'bulk_members'

RESOURCE_ATTRIBUTE_MAP = {
    RESOURCE_COLLECTION: {
        'action': {
            'allow_post': True, 'allow_put': False,
            'validate': {'type:values': [base.Controller.DELETE, base.Controller.CREATE,
                                         base.Controller.UPDATE]},
            'is_visible': True
        },
        'members': {
            'allow_post': True, 'allow_put': False,
            'default': None,
            'convert_to': attr.convert_to_list,
            'is_visible': True
        },
        'tenant_id': {
            'allow_post': True, 'allow_put': False,
            'validate': {'type:string': None},
            'required_by_policy': True,
            'is_visible': True
        },
    }
}


class BulkLoadBalancerController(wsgi.Controller, base.Controller):
    """
        This API is the entry point for all bulk members.
        A sample bulk API request payload would be as follows:

        {
        "bulk_members" :
            {
            "action": "create",
            "members" : [
                        {"member":
                                {
                                 "name":"testmember",
                                 "address":"1.1.1.1"
                                 "port":"80"
                                 }
                        },...
                    ]
            }
        }

    The controller expects the load balancer plugin to have bulk methods implemented with the format
    <action>_<entity>_bulk. eg: for instance, a bulk create for members should have a method called
    "create_member_bulk" in loadbalancer plugin.
    """

    def __init__(self):
        self._plugin = manager.NeutronManager.get_service_plugins().get(plugin_const.LOADBALANCER)
        super(BulkLoadBalancerController, self).__init__(self._plugin, RESOURCE_NAME, RESOURCE_COLLECTION,
                                                         RESOURCE_ATTRIBUTE_MAP[RESOURCE_COLLECTION])
        ## copying the entity resource map from the load balancer extension and just allowing id's on puts.
        ## This is because for bulk updates, you include the id's in the payload as oppose the URI.
        self.entity_resource_attr_map = copy.deepcopy(loadbalancer.RESOURCE_ATTRIBUTE_MAP)
        self.plural_mappings = resource_helper.build_plural_mappings({}, loadbalancer.RESOURCE_ATTRIBUTE_MAP)
        for k, v in self.entity_resource_attr_map.items():
            v['id']['allow_put'] = True

    def create(self, request, body, **kwargs):
        policy.init()

        ## validating the bulk request body
        action = body[RESOURCE_NAME]['action']
        body = self.prepare_request_body(request.context, body, True,
                                         RESOURCE_NAME,
                                         RESOURCE_ATTRIBUTE_MAP[RESOURCE_COLLECTION])
        collection_name = 'members'
        resource_name = self.plural_mappings[collection_name]
        resources_body = body[RESOURCE_NAME][collection_name]

        ## validate and prepare resource body
        resources = []
        if action == base.Controller.DELETE:
            resources = resources_body
        else:
            for res in resources_body:
                resources.append(self.prepare_request_body(request.context, res,
                                                       True if action == base.Controller.CREATE else False,
                                                       resource_name,
                                                       self.entity_resource_attr_map[collection_name]))

        ## send start notification for each resource
        for _id in resources:
            self._notifier.info(request.context,
                                '%s.%s.start' %(resource_name, action),
                                {resource_name + '_id': _id})
            try:
                policy.enforce(request.context,
                               action,
                               None)
            except exceptions.PolicyNotAuthorized:
                msg = _('The resource could not be found.')
                raise webob.exc.HTTPNotFound(msg)

        ## invoke the bulk method.
        action_executor = getattr(self._plugin, '%s_%s_%s' % (action,
                                                              resource_name,
                                                              'bulk'))
        action_result = action_executor(request.context, {collection_name: resources}, **kwargs)

        ## construct view object for each of them..
        resource_views = []
        for rdata in action_result:
            rview = BulkLoadBalancerController\
                                  ._view(request.context, rdata, resource_name,
                                         self.entity_resource_attr_map[collection_name])
            resource_views.append(rview)

        notifier_method = '%s.%s.end' % (resource_name, action)
        if action == base.Controller.DELETE:

            ## send end notification for each resource id
            for res in resources:
                self._notifier.info(request.context,
                                    notifier_method,
                                    {resource_name + '_id': res})
        else:
            ## send end notification for each resource view.
            for rview in resource_views:
                self._notifier.info(request.context, notifier_method,
                                    {resource_name: rview})

        return {collection_name: resource_views}

    """
        The following three methods are the static versions of _view, _filter_attributes,
        and _exclude_attributes_by_policy method in base.Controller class. This is because
        these methods do not let you override the resource name and attribute info
    """
    @staticmethod
    def _view(context, data, resource_name, attr_info, fields_to_strip=None):
        """Build a view of an API resource.

        :param context: the neutron context
        :param data: the object for which a view is being created
        :param fields_to_strip: attributes to remove from the view

        :returns: a view of the object which includes only attributes
        visible according to API resource declaration and authZ policies.
        """
        fields_to_strip = ((fields_to_strip or []) +
                           BulkLoadBalancerController.\
                           _exclude_attributes_by_policy(context, data, resource_name, attr_info))
        return BulkLoadBalancerController._filter_attributes(context, data, fields_to_strip)

    @staticmethod
    def _filter_attributes(context, data, fields_to_strip=None):
        if not fields_to_strip:
            return data
        return dict(item for item in data.iteritems()
                    if (item[0] not in fields_to_strip))

    @staticmethod
    def _exclude_attributes_by_policy(context, data, resource_name, attr_info):
        """Identifies attributes to exclude according to authZ policies.

        Return a list of attribute names which should be stripped from the
        response returned to the user because the user is not authorized
        to see them.
        """
        attributes_to_exclude = []
        for attr_name in data.keys():
            attr_data = attr_info.get(attr_name)
            if attr_data and attr_data['is_visible']:
                if policy.check(
                    context,
                    '%s_%s:%s' % ('get',resource_name, attr_name),
                    data,
                    might_not_exist=True):
                    # this attribute is visible, check next one
                    continue
            # if the code reaches this point then either the policy check
            # failed or the attribute was not visible in the first place
            attributes_to_exclude.append(attr_name)
        return attributes_to_exclude



class Bulkloadbalancer(extensions.ExtensionDescriptor):

    @classmethod
    def get_name(cls):
        return "Bulk Load balancer"

    @classmethod
    def get_alias(cls):
        return 'lbaas-bulk-operations'

    @classmethod
    def get_description(cls):
        return "Bulk Loadbalancer Operations"

    @classmethod
    def get_namespace(cls):
        return "http://wiki.openstack.org/neutron/LBaaS/API_1.0"

    @classmethod
    def get_updated(cls):
        return "2016-02-29T10:00:00-00:00"

    @classmethod
    def get_resources(cls):
        resources = []
        controller = resource_creator.Resource(BulkLoadBalancerController(), faults=base.FAULT_MAP)

        resource = extensions.ResourceExtension(RESOURCE_COLLECTION,
                                                controller,
                                                path_prefix=plugin_const.COMMON_PREFIXES[plugin_const.LOADBALANCER],
                                                attr_map=RESOURCE_ATTRIBUTE_MAP.get(RESOURCE_NAME))
        resources.append(resource)
        return resources

    @classmethod
    def get_plugin_interface(cls):
        return BulkLoadBalancerPluginBase

    def update_attributes_map(self, attributes):
        super(Bulkloadbalancer, self).update_attributes_map(attributes,
                                                            extension_attrs_map=RESOURCE_ATTRIBUTE_MAP)

    def get_extended_resources(self, version):
        if version == "2.0":
            return RESOURCE_ATTRIBUTE_MAP
        else:
            return {}


@six.add_metaclass(abc.ABCMeta)
class BulkLoadBalancerPluginBase(service_base.ServicePluginBase):

    def get_plugin_name(self):
        return plugin_const.LOADBALANCER

    def get_plugin_type(self):
        return plugin_const.LOADBALANCER

    def get_plugin_description(self):
        return 'LoadBalancer service plugin'

    @abc.abstractmethod
    def delete_member_bulk(self, context, member_ids):
        pass

    @abc.abstractmethod
    def create_member_bulk(self, context, member):
        pass

    @abc.abstractmethod
    def update_member_bulk(self, context, member):
        pass
