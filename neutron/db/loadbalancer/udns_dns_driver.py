import json

from neutron.openstack.common import log as logging
from oslo_config import cfg
import requests
from requests import exceptions as req_exc
from neutron.extensions.loadbalancer import IAFTokenError, VIPAlreadyExistsInDNSException
from keystoneclient.v2_0.client import Client
import httplib2

CONF = cfg.CONF

_CLIENT = None

LOG = logging.getLogger(__name__)

CONF.register_group(cfg.OptGroup(name='dns', title='UDNS Configuration'))

UDNS_OPTS = [
    cfg.StrOpt("udns_api_host", default="http://udns-web-1.stratus.phx.qa.ebay.com"),
    cfg.StrOpt("udns_zone", default="dev:stratus.dev.ebay.com,ext:ebaystratus.com"),
    cfg.StrOpt("udns_view", default="dev:ebay-cloud,ext:public"),
    cfg.StrOpt("udns_user", default="_STRATUS_IAAS"),
    cfg.StrOpt("udns_password", default="xxxx"),
    cfg.StrOpt("udns_api_version", default="v1"),
    cfg.StrOpt("udns_tenant_name", default="udns_c3_dev")
]
cfg.CONF.register_opts(UDNS_OPTS, group='dns')

class UdnsClient(object):


    def __init__(self):
        self.udns_api_version = CONF['dns'].get('udns_api_version')
        self.keystone_token = self._get_keystone_token()


    def _get_APTR_rec_url(self, dns_zone, view, action):
        return "{0}/dns/views/{1}/zones/{2}/recordtypes/aptr/actions/{3}" \
            .format(CONF['dns'].get('udns_api_host'),
                    view,
                    dns_zone,
                    action)

    def _get_A_rec_url(self, view, zone, hostname):
        return "{0}/dns/views/{1}/zones/{2}/recordtypes/a/records/{3}" \
            .format(CONF['dns'].get('udns_api_host'),
                    view,
                    zone,
                    hostname)

    def _get_PTR_rec_url(self, view, zone, resource):
        return "{0}/dns/views/{1}/zones/{2}/recordtypes/ptr/records/{3}" \
            .format(CONF['dns'].get('udns_api_host'),
                    view,
                    zone,
                    resource)

    def _get_A_record(self, view, zone, hostname):
        headers = {
            "X-Auth-Token": self.keystone_token
        }
        response = requests.get(self._get_A_rec_url(view, zone, hostname),
                                headers=headers,
                                verify = False)

        # check if the status code is 404, which means A record does not exists
        if response.status_code == 404:
            return None

        # if status code is > 400 and not 404 then raise an exception.
        elif response.status_code >= 400:
            response.raise_for_status()

        # else return the ip address
        else:
            response_body = json.loads(response.content)
            return response_body['ipAddresses']

    def get_PTR_record(self, cos, ip_address):
        reverse_zone, resource_name = self._get_reverse_zone_name_and_resource_name(ip_address)
        headers = {
            "X-Auth-Token": self.keystone_token
        }
        response = requests.get(self._get_PTR_rec_url(self.view(cos), reverse_zone, resource_name),
                                headers=headers,
                                verify = False)

        # check if the status code is 404, which means PTR record does not exists
        if response.status_code == 404:
            return None

        # if status code is > 400 and not 404 then raise an exception.
        elif response.status_code >= 400:
            response.raise_for_status()

         # else return the fqdn name
        else:
            response_body = json.loads(response.content)
            return response_body['fullyQualifiedName']

    def _get_reverse_zone_name_and_resource_name(self, ip_address):
        ip_address_elements = ip_address.split('.')
        return (ip_address_elements[2] + "." + ip_address_elements[1] + "." + ip_address_elements[0] + ".in-addr.arpa",
                ip_address_elements[3])


    def _a_record_already_exists(self, view, zone, hostname):
        try:
            ip_addresses = self._get_A_record(view, zone, hostname)
        except req_exc.HTTPError as http_exec:
            LOG.error('an error in getting A record', http_exec)
            return True

        if ip_addresses is not None:
            return True
        else:
            return False

    def create_A_PTR_record(self, address, hostname, cos):
        return self._A_PTR_record(address, hostname, cos, action='update')

    def delete_A_PTR_record(self, address, hostname, cos):
        return self._A_PTR_record(address, hostname, cos, action='delete')

    def _A_PTR_record(self, address, hostname, cos, action):

        dns_zone = self.zone(cos)
        view = self.view(cos)

        if action == 'update' and self._a_record_already_exists(view, dns_zone, hostname):
            raise VIPAlreadyExistsInDNSException(vip_name=hostname)

        if not address:
            LOG.info('ip is None')
            return None
        elif not hostname:
            LOG.info('hostname is None')
            return None

        headers = {
            "X-Auth-Token": self.keystone_token,
            "Content-Type": "application/json",
            "FORCE_OPERATION": "true",
            "RUN_AS_ASYNC_MODE":"true"
        }

        fqdn = hostname
        if action == 'update':
            fqdn = hostname + '.' + dns_zone

        body = {"fqdn": "%s" % fqdn,
                "ipAddress": "%s" % address
                }

        LOG.info('udns APTR request payload [%s]' % (body))

        url = self._get_APTR_rec_url(dns_zone, view, action)
        response = requests.post(url,
                                 data=json.dumps(body),
                                 headers=headers,
                                 verify=False)

        str_action = 'created' if action == 'update' else 'deleted'

        if response.status_code == 202:
            LOG.info('UDNS response %s' % response.content)
            LOG.info('A & PTR record %s' % str_action)
            return fqdn
        else:
            LOG.error('Error %s A & PTR record. Error: %s' %
                      (str_action, response.content))
            LOG.error('Url %s' % url)
            LOG.error('Body %s' % body)
            return None


    def zone(self, cos):
        if cos is None:
            return None

        for network_str in CONF['dns'].get('udns_zone').split(','):
            co, sp, network = network_str.partition(':')
            if co.lower() == cos.lower():
                return network
        return None

    def view(self, cos):
        if cos is None:
            return None

        for network_str in CONF['dns'].get('udns_view').split(','):
            co, sp, network = network_str.partition(':')
            if co.lower() == cos.lower():
                return network
        return None


    '''
    v2 APIs.
    This code has been taken from the starch.git repo's unified_dnsv2.py.
    '''

    def prepare_auth_url(self, auth_host, auth_port, protocol="https",
                         version="v2.0"):
        auth_url = str(protocol) +"://" + str(auth_host) + ":" + str(auth_port)\
                   + "/" + str(version)
        return auth_url

    def _get_keystone_token(self):
        """
        Get token from keystone for each request
        :return token
        """
        #auth_url = "https://" + cfg.CONF.keystone_authtoken['auth_host'] +
        # ":PORT/v2.0"
        auth_url = self.prepare_auth_url(cfg.CONF.keystone_authtoken['auth_host'],
                                         cfg.CONF.keystone_authtoken['auth_port'],
                                         protocol = cfg.CONF.keystone_authtoken[
                                             'auth_protocol'])
        global _CLIENT
        if not _CLIENT:
            _CLIENT = Client(username=CONF['dns'].get('udns_user'),
                             password=CONF['dns'].get('udns_password'),
                             project_name=CONF['dns'].get('udns_tenant_name'),
                             auth_url=auth_url)
        token = _CLIENT.auth_token
        return token

    def _get_api_host(self):
        return "{0}/dnsv2/action/modify".format(CONF['dns'].get('udns_api_host'))


    def _get_header(self, use_token=True, use_cache=False):
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        if use_token:
            token = self._get_keystone_token()
            headers['X-Auth-Token'] = token
        if use_cache:
            headers['Use-Cache'] = 'true'
        return headers


    def _check_reverse_zone(self, zone, view):
        # generate headers
        headers = self._get_header(use_cache=True, use_token=False)
        # generate url
        route = '/dnsv2/views/%s/zones/%s/recordtypes/soa/records/@' % (view, zone)
        url = CONF['dns'].get('udns_api_host') + route
        # submit request and get a resp
        http = httplib2.Http()
        resp, content = http.request(url, "GET", headers=headers)
        LOG.debug('udns reverse zone lookup response [%s] [%s] [%s]' % (route, resp['status'], content))
        return (int(resp['status']) == 200)


    """
    Returns the first class of reverse zone found for the IP
    safe to assume and return first as we dont support subdomains in reverse zones
    """


    def _get_reverse_zone(self, ip, view):
        item = ip.split('.')
        resp = False
        i = len(item) -1
        zone = None
        while i > 0:
            octets = '.'.join(item[:i])
            reverse_octets = str(octets).split('.')[::-1]
            zone = '.'.join(reverse_octets) + '.in-addr.arpa'
            resp = self._check_reverse_zone(zone, view)
            if resp:
                break
            i -=1
        if not resp:
            raise Exception("Unable to find a proper reverse zone for the IP: %s" % ip)
        return zone


    def _generate_record_name(self, reverse_zone, ip):
        rev_zone_octets = len(reverse_zone.split('.')) - 2
        ip_octets = ip.split('.')[::-1][:(4 - rev_zone_octets)]
        return '.'.join(ip_octets)


    def _get_payload(self, view, zone, ip, fqdn, action):
        items = ip.split('.')
        if len(items) != 4:
            raise Exception("Invalid IP address %s" % ip)
        hostname = fqdn[:len(fqdn) - len(zone) - 1]

        # need to generate reverse zones to check for class B or C
        #LOG.debug('Finding reverse zones and generating record names')
        print 'Finding reverse zones and generating record names'
        reverse_zone = self._get_reverse_zone(ip, view)
        record_name = self._generate_record_name(reverse_zone, ip)
        print 'Reverse zones: %s and Record name: %s' % (reverse_zone, record_name)

        payload = {"resources": [
            {"viewName": view, "zoneName": zone,
             "records": [{"resourceType": "A",
                          "records": [
                              {"recordName": hostname,
                               "timeToLive": 300,
                               "ipAddresses": [ip],
                               "action": action}]}
             ]
            },
            {"viewName": view, "zoneName": reverse_zone,
             "records": [{"resourceType": "PTR",
                          "records": [
                              {"recordName": record_name,
                               "timeToLive": 300,
                               "fullyQualifiedName": fqdn,
                               "action": action}]}
             ]
            }]}
        return json.dumps(payload)


    def bind_fqdn(self, view, address, hostname, zone):
        http = httplib2.Http()
        headers = self._get_header()
        fqdn = hostname + '.' + zone
        body = self._get_payload(view, zone, address, fqdn, 'CREATE')

        resp, content = http.request(self._get_api_host(),
                                     "POST",
                                     body=body,
                                     headers=headers)
        if int(resp["status"]) != 200:
            raise Exception("Unable to bind %s for address %s, received response %s" % (hostname, address, resp['status']),
                            content)


    def unbind_fqdn(self, view, address, fqdn, zone):
        http = httplib2.Http()
        headers = self._get_header()

        body = self._get_payload(view, zone, address, fqdn, 'DELETE')

        resp, content = http.request(self._get_api_host(),
                                     "POST",
                                     body=body,
                                     headers=headers)
        if int(resp["status"]) != 200:
            raise Exception("Unable to unbind %s for address %s, received response %s" % (fqdn, address, resp['status']),
                            content)


    def create_A_PTR_record_v2(self, address, hostname, cos):
        dns_zone = self.zone(cos)
        dns_view = self.view(cos)
        return self.bind_fqdn(dns_view, address, hostname, dns_zone)

    def delete_A_PTR_record_v2(self, address, fqdn, cos):
        dns_zone = self.zone(cos)
        dns_view = self.view(cos)
        self.unbind_fqdn(dns_view, address, fqdn, dns_zone)