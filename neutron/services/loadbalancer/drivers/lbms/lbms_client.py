import requests
import json
import neutron.services.loadbalancer.drivers.lbms.lbms_constants as lbms_constants
from neutron.openstack.common import log as logging
from neutron.common import exceptions
from oslo_config import cfg
from keystoneclient.v2_0.client import Client
import time


LOG = logging.getLogger(__name__)
__author__ = 'kugandhi'

CONF = cfg.CONF


class LbmsClientException(exceptions.NeutronException):
    message = _("An LBMS exception has occurred: %(reason)s, %(status_code)d")

    def __init__(self, **kwargs):
        super(LbmsClientException, self).__init__(**kwargs)


class LbmsClient(object):
    def __init__(self):
        self.service_endpoint = cfg.CONF.lbms_driver['lbms_uri']
        self.keystone_token_regeneration_interval = \
            int(cfg.CONF.lbms_driver['keystone_token_regeneration_interval'])
        self.request_max_retries = \
            int(cfg.CONF.lbms_driver['request_max_retries'])
        self.request_retries_interval = \
            int(cfg.CONF.lbms_driver['request_retries_interval'])
        self.lbms_job_max_retries = \
            int(cfg.CONF.lbms_driver['lbms_job_max_retries'])
        self.lbms_job_retries_interval = \
            int(cfg.CONF.lbms_driver['lbms_job_retires_interval'])
        self.last_time_keystone_token_generated = 0

        self.ks_token = self._get_keystone_token()

    def prepare_auth_url(self, auth_host, auth_port, protocol="https", version="v2.0"):
        auth_url = str(protocol) + "://" + str(auth_host) + ":" + str(auth_port) + "/" + str(version)
        return auth_url

    def _get_keystone_token(self):
        LOG.info('generating keystone token')

        auth_url = self.prepare_auth_url(cfg.CONF.keystone_authtoken['auth_host'],
                                         cfg.CONF.keystone_authtoken['auth_port'],
                                         protocol=cfg.CONF.keystone_authtoken['auth_protocol'])

        keystone_client = Client(username=cfg.CONF.lbms_driver['lbms_username'],
                             password=cfg.CONF.lbms_driver['lbms_password'],
                             project_name=cfg.CONF.lbms_driver['lbms_tenant'],
                             auth_url=auth_url)
        token = keystone_client.auth_token
        return token


    def get_pool(self, lb_name, pool_name):
        pool_endpoint = lbms_constants.POOL_PATH % (self.service_endpoint, lb_name, pool_name)
        response = self._lbms_request(pool_endpoint, "GET")
        return self._parse_get_response(response)

    def create_pool(self, lb_name, pool):
        pool_from_lbms = self.get_pool(lb_name, pool['name'])
        if (pool_from_lbms != None ) and (pool_from_lbms['pool']['name'] == pool['name']) :
            return

        pool_endpoint = lbms_constants.POOL_PATH % (self.service_endpoint, lb_name, pool['name'])
        pool_data = {
            "pool": {
                "name": pool['name'],
                "method": self._get_lbms_specific_lb_methods(pool['lb_method']),
                "protocol": self._get_lbms_specific_lb_protocol(pool['protocol']),
                "enabled": "true" if pool['admin_state_up'] == True else "false"
            }
        }
        response = self._lbms_request(pool_endpoint, "PUT", data=json.dumps(pool_data))
        self._parse_response(response)

    def update_pool(self, lb_name, pool):
        pool_from_lbms = self.get_pool(lb_name, pool['name'])
        if (pool_from_lbms == None ) or (pool_from_lbms['pool']['name'] != pool['name']) :
            raise LbmsClientException(status_code=0,
                                      reason="Trying to update a pool which doesn't exist in LBMS. Pool Name:" + pool['name'])

        pool_endpoint = lbms_constants.POOL_PATH % (self.service_endpoint, lb_name, pool['name'])
        if (pool['health_monitors'] == None) or (len(pool['health_monitors']) == 0):
            pool_data = {
                "pool": {
                    "name": pool['name'],
                    "method": self._get_lbms_specific_lb_methods(pool['lb_method']),
                    "enabled": "true" if pool['admin_state_up'] == True else "false"
                }
            }
        else:
            pool_data = {
                "pool": {
                    "name": pool['name'],
                    "method": self._get_lbms_specific_lb_methods(pool['lb_method']),
                    "monitors" : pool['health_monitors'],
                    "enabled": "true" if pool['admin_state_up'] == True else "false"
                }
            }

        response = self._lbms_request(pool_endpoint, "POST", data=json.dumps(pool_data))
        self._parse_response(response)


    def delete_pool(self, lb_name, pool):
        pool_from_lbms = self.get_pool(lb_name, pool['name'])
        if pool_from_lbms == None :
            return

        pool_endpoint = lbms_constants.POOL_PATH % (self.service_endpoint, lb_name, pool['name'])
        response = self._lbms_request(pool_endpoint, "DELETE")
        self._parse_response(response)

    def get_monitor(self, lb_name, monitor_name):
        monitor_endpoint = lbms_constants.MONITOR_PATH % (self.service_endpoint, lb_name, monitor_name)
        response = self._lbms_request(monitor_endpoint, "GET")
        return self._parse_get_response(response)

    def create_monitor(self, lb_name, monitor):
        monitor_from_lbms = self.get_monitor(lb_name, monitor['name'])
        if (monitor_from_lbms != None ) and (monitor_from_lbms['monitor']['name'] == monitor['name']) :
            return

        monitor_endpoint = lbms_constants.MONITOR_PATH % (self.service_endpoint, lb_name, monitor['name'])
        if monitor['type'] == "HTTP":
            monitor['type'] = "HTTP-ECV"

        monitor_data = {
            "monitor": {
                "name": monitor['name'],
                "type": monitor['type'],
                "interval": monitor['delay'],
                "timeout": monitor['timeout'],
                "downtime": monitor['max_retries'] * monitor['delay']
            }
        }

        if 'url_path' in monitor:
            monitor_data['monitor']['send'] = monitor['url_path']

        if 'response_string' in monitor:
            monitor_data['monitor']['rcv'] = monitor['response_string']

        response = self._lbms_request(monitor_endpoint, "PUT", data=json.dumps(monitor_data))
        self._parse_response(response)


    def update_monitor(self, lb_name, monitor):
        monitor_from_lbms = self.get_monitor(lb_name, monitor['name'])
        if (monitor_from_lbms == None ) or (monitor_from_lbms['monitor']['name'] != monitor['name']) :
            raise LbmsClientException(status_code=0,
                                      reason="Trying to update a monitor which doesn't exist in LBMS. Pool Name:" + monitor['name'])

        monitor_endpoint = lbms_constants.MONITOR_PATH % (self.service_endpoint, lb_name, monitor['name'])
        monitor_data = {
            "monitor": {
                "interval": monitor['delay'],
                "timeout": monitor['timeout'],
                "downtime": monitor['max_retries'] * monitor['delay']
            }
        }
        if 'url_path' in monitor:
            monitor_data['monitor']['send'] = monitor['url_path']

        if 'response_string' in monitor:
            monitor_data['monitor']['rcv'] = monitor['response_string']

        response = self._lbms_request(monitor_endpoint, "POST", data=json.dumps(monitor_data))
        self._parse_response(response)

    def delete_monitor(self, lb_name, monitor):
        monitor_from_lbms = self.get_monitor(lb_name, monitor['name'])
        if monitor_from_lbms == None :
            return

        monitor_endpoint = lbms_constants.MONITOR_PATH % (self.service_endpoint, lb_name, monitor['name'])
        response = self._lbms_request(monitor_endpoint, "DELETE")
        self._parse_response(response)


    def remove_monitor_from_pool(self, lb_name, pool, monitor):
        pool_from_lbms = self.get_pool(lb_name, pool['name'])
        if (pool_from_lbms == None):
            return

        pool_monitor_endpoint = lbms_constants.POOL_MONITOR_PATH % (self.service_endpoint, lb_name, pool['name'], monitor['name'])
        response = self._lbms_request(pool_monitor_endpoint, "DELETE")
        self._parse_response(response)


    def get_member(self, lb_name, pool_name, member_name):
        pool_member_endpoint = lbms_constants.MEMBER_PATH % (self.service_endpoint, lb_name, pool_name, member_name)
        response = self._lbms_request(pool_member_endpoint, "GET")
        return self._parse_get_response(response)


    def delete_member(self, lb_name, pool, member):
        pool_member_from_lbms = self.get_member(lb_name, pool['name'], self._get_member_name(member))
        if (pool_member_from_lbms == None) or (
            pool_member_from_lbms['service']['name'] != self._get_member_name(member)):
            LOG.info('Member doesnt exist in pool %s' % self._get_member_name(member))
            return

        pool_member_endpoint = lbms_constants.MEMBER_PATH % (self.service_endpoint, lb_name, pool['name'], self._get_member_name(member))
        response = self._lbms_request(pool_member_endpoint, "DELETE")
        return self._parse_response(response)

    def get_vip(self, lb_name, vip_name):
        vip_endpoint = lbms_constants.VIP_PATH % (self.service_endpoint, lb_name, vip_name)
        response = self._lbms_request(vip_endpoint, "GET")
        return self._parse_get_response(response)



    def create_vip(self, lb_name, vip, pool):
        vip_from_lbms = self.get_vip(lb_name, vip['name'])
        if (vip_from_lbms != None) and (vip_from_lbms['vip']['name'] == vip['name']):
            return

        vip_endpoint = lbms_constants.VIP_PATH % (self.service_endpoint, lb_name, vip['name'])

        vip_data = {
            "vip": {
                "name": vip['name'],
                "ip": vip['address'],
                "port": str(vip['protocol_port']),
                "protocol": self._get_lbms_specific_lb_protocol(vip['protocol']),
                "pools": {
                    "name": pool['name']
                },
                "enabled": "true" if vip['admin_state_up'] == True else "false"

            }
        }
        LOG.info('vip data %s' % vip_data)
        response = self._lbms_request(vip_endpoint, "PUT", data=json.dumps(vip_data))
        self._parse_response(response)


    def update_vip(self, lb_name, vip, pool):
        vip_from_lbms = self.get_vip(lb_name, vip['name'])
        if vip_from_lbms == None:
            raise LbmsClientException(status_code=0,
                                      reason="Trying to update a vip which doesn't exist in LBMS." +
                                             " Pool Name:" + pool['name'] + " vip:" + vip['name'])

        vip_member_endpoint = lbms_constants.VIP_PATH % (self.service_endpoint, lb_name, vip['name'])
        vip_data = {
            "vip": {
                "name": vip['name'],
                "enabled": "true" if vip['admin_state_up'] == True else "false"

            }
        }
        response = self._lbms_request(vip_member_endpoint, "POST", data=json.dumps(vip_data))
        self._parse_response(response)


    def delete_vip(self, lb_name, vip):
        vip_from_lbms = self.get_vip(lb_name, vip['name'])
        if vip_from_lbms == None:
            return
        vip_endpoint = lbms_constants.VIP_PATH % (self.service_endpoint, lb_name, vip['name'])
        response = self._lbms_request(vip_endpoint, "DELETE")
        return self._parse_response(response)


    def create_or_update_members(self, lb_name, pool, members):

        pool_member_endpoint = lbms_constants.POOL_PATH % (self.service_endpoint, lb_name, pool['name'])
        pool_member_data_list = []
        for member in members :
            if ('health_monitors' not in pool) or (len(pool['health_monitors']) == 0) :
                pool_member_data =  {
                        "name" : self._get_member_name(member),
                        "ip": member['address'],
                        "port" : member['protocol_port'],
                        "weight" : member['weight'],
                        "protocol": self._get_lbms_specific_lb_protocol(pool['protocol']),
                        "enabled" : "true" if member['admin_state_up'] == True else "false"

                    }

            else:
                pool_member_data = {
                        "name": self._get_member_name(member),
                        "ip": member['address'],
                        "port": member['protocol_port'],
                        "weight": member['weight'],
                        "protocol": self._get_lbms_specific_lb_protocol(pool['protocol']),
                        "monitors": pool['health_monitors'],
                        "enabled": "true" if member['admin_state_up'] == True else "false"

                    }
            pool_member_data_list.append(pool_member_data)

        pool_data = {
                "pool": {
                    "name": pool['name'],
                    "services": pool_member_data_list
                }
        }
        LOG.info(json.dumps(pool_data))
        response = self._lbms_request(pool_member_endpoint, "POST", data=json.dumps(pool_data))
        self._parse_response(response)

    def delete_members(self, lb_name, pool, members):
        for member in members:
            self.delete_member(lb_name, pool, member)

    def get_cert(self, cert_name):
        LOG.info("get cert")
        cert_endpoint = lbms_constants.CERT_PATH % (self.service_endpoint, cert_name)
        response = self._lbms_request(cert_endpoint, "GET")
        return self._parse_get_response(response)

    def get_lb_cert(self, lb_name, cert_name):
        LOG.info("get cert")
        cert_endpoint = lbms_constants.LB_CERT_PATH % (self.service_endpoint, lb_name, cert_name)
        response = self._lbms_request(cert_endpoint, "GET")
        return self._parse_get_response(response)


    def create_vip_ssl_certificate_association(self, lb_name, cert_db_record,
                                               key_db_record, vip_db_record):

        # Add cert to lbms
        cert_endpoint = lbms_constants.CERT_PATH % (self.service_endpoint, cert_db_record['name'])

        cert_data = {
            "cert": {
                "name": cert_db_record['name'],
                "certificate": cert_db_record['certificate'],
                "csrKey": {
                    "name": key_db_record['name'],
                    "key": key_db_record['key']
                }
            }
        }

        LOG.info(json.dumps(cert_data))
        response = self._lbms_request(cert_endpoint, "POST", data=json.dumps(cert_data))
        LOG.info(response.text)
        self._parse_response(response, async=False)

        # Add cert to lb
        lb_cert = self.get_lb_cert(lb_name, cert_db_record['name'])
        if lb_cert == None:
            lb_cert_associate_endpoint = lbms_constants.LB_CERT_PATH % (self.service_endpoint, lb_name,
                                                                         cert_db_record['name'])
            response = self._lbms_request(lb_cert_associate_endpoint, "POST", data=None)
            self._parse_response(response)


        # Add cert to vip
        vip_cert_associate_endpoint = lbms_constants.VIP_CERT_PATH % (self.service_endpoint, lb_name,
                                                                      vip_db_record['name'], cert_db_record['name'])
        response = self._lbms_request(vip_cert_associate_endpoint, "PUT", data=None)
        self._parse_response(response)

    def delete_vip_ssl_certificate_association(self, lb_name, cert_db_record, vip_db_record):
        # Remove vip cert assocation
        try:
            vip_cert_associate_endpoint = lbms_constants.VIP_CERT_PATH % (self.service_endpoint, lb_name,
                                                                      vip_db_record['name'], cert_db_record['name'])
            response = self._lbms_request(vip_cert_associate_endpoint, "DELETE", data=None)
            self._parse_response(response)

        except Exception as e:
            LOG.error("Error in removing vip ssl assoc vip = %(vip)s, cert = %(cert)s" %
                      {'vip': vip_db_record['name'], 'cert': cert_db_record['name']})

        # Remove cert from the lb
        lb_cert = self.get_lb_cert(lb_name, cert_db_record['name'])
        if (lb_cert != None):
            lb_cert_endpoint = lbms_constants.LB_CERT_PATH % (self.service_endpoint, lb_name, cert_db_record['name'])
            response = self._lbms_request(lb_cert_endpoint, "DELETE", data=None, async=False)
            self._parse_response(response, async=False)

        # Remove cert from lbms
        cert = self.get_cert(cert_db_record['name'])
        if ( cert != None):
            cert_endpoint = lbms_constants.CERT_PATH % (self.service_endpoint, cert_db_record['name'])
            response = self._lbms_request(cert_endpoint, "DELETE", data=None, async=False)
            self._parse_response(response, async=False)


    def get_lbms_health(self):
        LOG.info('getting lbms health')
        health_endpoint = self.service_endpoint
        LOG.info('endpoint %s' % health_endpoint)
        response = self._lbms_request(health_endpoint, "GET")
        return self._parse_get_response(response)

    def _lbms_headers(self, async=True):
        current_time = int(round(time.time()))
        if (self.last_time_keystone_token_generated + self.keystone_token_regeneration_interval
                < current_time) :
            self.ks_token = self._get_keystone_token()
            self.last_time_keystone_token_generated = current_time

        headers = {
            "X-Auth-Token": "%s" % (self.ks_token),
            "Content-Type": "application/json"
        }
        if async == True :
            headers['EXECUTION_MODE'] = "async"

        return headers

    def _parse_response(self, response, async=True):
        if response.status_code >= 400:
            LOG.error("Error in API status code = %(status_code)s, response.content = %(content)s" %
                      {'status_code': response.status_code, 'content': response.content})
            raise LbmsClientException(status_code=response.status_code, reason=response.content)

        LOG.info(response.text)

        # PUT, POST and DELETE jobs are async, so wait
        if (async == True):
            job_response = self._waiter(response)
            return job_response;

    def _parse_get_response(self, response):
        if response.status_code >= 400:
            # No need to throw exception
            LOG.error("Error in API status code = %(status_code)s, response.content = %(content)s" %
                      {'status_code' :response.status_code, 'content' :response.content})
            return

        LOG.info(response.text)
        return response.json();


    def _get_lbms_specific_lb_methods(self, lb_method):
        return {
            'ROUND_ROBIN': 'RoundRobin',
            'LEAST_CONNECTIONS': 'LeastConnection',
        }.get(lb_method, 'RoundRobin')

    def _get_lbms_specific_lb_protocol(self, lb_protocol):
        return {
            'HTTP': 'HTTP',
            'TCP': 'TCP',
            'HTTPS': 'SSL'
        }.get(lb_protocol, 'HTTP')


    def _get_member_name(self,  member):
        return member['address'] + ':' + str(member['protocol_port'])

    def _waiter(self, response):
        response_json = response.json()
        if response_json:
            remaining_tries = self.lbms_job_max_retries
            while remaining_tries > 0:
                job_endpoint = self.service_endpoint + response_json['href']
                LOG.debug("URL = %(url)s, lbms job retry_remaining = %(remaining_tries)s" %
                          {'url': job_endpoint, 'remaining_tries': remaining_tries})
                response = self._lbms_request(job_endpoint, "GET")
                response_json = self._parse_get_response(response)

                if response_json and (response_json['status'] == "finished"):
                    return str(response_json)
                elif ((response_json and (response_json['status'] == 'error'))
                      or (response_json and (response_json['status'] == 'cancelled'))
                      or (response_json and (response_json['status'] == 'paused'))):
                    LOG.error('lbms job failed %s' % str(response_json))
                    raise LbmsClientException(status_code=0, reason="LBMS Job failed")

                elif (response_json and response_json['status'] == 'inprogress'):
                    LOG.debug('lbms job status in progress %s' % response_json['href'])
                    time.sleep(self.lbms_job_retries_interval)
                    remaining_tries = remaining_tries - 1
                else:
                    LOG.error('lbms job status unknown %s' % str(response_json))
                    time.sleep(self.lbms_job_retries_interval)
                    remaining_tries = remaining_tries - 1


            raise LbmsClientException(status_code=0, reason="Job not successfully after waiting for %s seconds" %
                                     self.lbms_job_max_retries * self.lbms_job_retries_interval)


    def _lbms_request(self, url, method, data=None, async=True):
        remaining_tries = self.request_max_retries
        while remaining_tries > 0:
            try:
                LOG.debug("URL = %(url)s, method = %(method)s retry_remaining = %(remaining_tries)s" %
                          {'url': url, 'method': method, 'remaining_tries' : remaining_tries})
                headers = self._lbms_headers(async)
                response = requests.request(
                    method,
                    url,
                    data=data,
                    headers=headers,
                    verify = False)

                if response.status_code == 401:
                    LOG.debug("40k Error code Response %s" % response.text)
                    LOG.debug("key stone used %s" % self.ks_token)
                    self.ks_token = self._get_keystone_token()
                    remaining_tries = remaining_tries - 1
                else:
                    return response

            except Exception as e:
                LOG.error("throwing ConnectionFailed : %s", e)
                time.sleep(self.request_retries_interval)
                remaining_tries = remaining_tries - 1

        raise LbmsClientException(status_code=0, reason="Connection error in LBMS Driver")


